#!/usr/bin/env python3
"""生产服务器多数据库一键合流工具 (Production Database Merger).

用途:
  当生产服务器由于早期版本历史遗留或执行路径原因在 `runs/`、`data/` 或其他子目录
  生成了多个分立的 `alpha_research.db` 时，一键扫描并安全无损地将所有历史回测记录、
  表达式、检查结果与沉淀模板合流合并到权威主库 `data/alpha_research.db` 中。

使用方法:
  python scripts/merge_databases.py [--source <other_db_path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

# 自动定位项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alpha_operator_framework.database.config import DEFAULT_SQLITE_PATH, get_database_path


def get_all_db_candidates(root: Path) -> List[Path]:
    """扫描项目内所有可能的 sqlite 数据库文件."""
    main_db = DEFAULT_SQLITE_PATH.resolve()
    candidates: List[Path] = []
    for p in root.rglob("*.db"):
        if p.is_file() and p.resolve() != main_db:
            candidates.append(p)
    return candidates


def merge_single_db(source_db_path: Path, target_db_path: Path, dry_run: bool = False) -> dict:
    """将一个来源库中的所有核心表无损合并入目标主库."""
    stats = {
        "expressions_merged": 0,
        "details_merged": 0,
        "checks_merged": 0,
        "templates_merged": 0,
        "datafields_merged": 0,
    }

    if not source_db_path.exists():
        print(f"⚠️ 来源库不存在: {source_db_path}")
        return stats

    src_conn = sqlite3.connect(str(source_db_path))
    src_conn.row_factory = sqlite3.Row
    src_cur = src_conn.cursor()

    tgt_conn = sqlite3.connect(str(target_db_path))
    tgt_cur = tgt_conn.cursor()

    try:
        # 1. 检查来源库包含的表
        src_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        src_tables = {r[0] for r in src_cur.fetchall()}

        # 2. 合并 alpha_expressions (基于 expression_sha 去重)
        if "alpha_expressions" in src_tables:
            src_cur.execute("SELECT * FROM alpha_expressions")
            rows = src_cur.fetchall()
            for r in rows:
                cols = r.keys()
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                if not dry_run:
                    tgt_cur.execute(
                        f"INSERT OR IGNORE INTO alpha_expressions ({col_names}) VALUES ({placeholders})",
                        tuple(r)
                    )
                stats["expressions_merged"] += 1

        # 3. 合并 alpha_details (基于 alpha_id 去重)
        if "alpha_details" in src_tables:
            src_cur.execute("SELECT * FROM alpha_details")
            rows = src_cur.fetchall()
            for r in rows:
                cols = r.keys()
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                if not dry_run:
                    tgt_cur.execute(
                        f"INSERT OR IGNORE INTO alpha_details ({col_names}) VALUES ({placeholders})",
                        tuple(r)
                    )
                stats["details_merged"] += 1

        # 4. 合并 alpha_checks
        if "alpha_checks" in src_tables:
            src_cur.execute("SELECT * FROM alpha_checks")
            rows = src_cur.fetchall()
            for r in rows:
                cols = r.keys()
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                if not dry_run:
                    tgt_cur.execute(
                        f"INSERT OR IGNORE INTO alpha_checks ({col_names}) VALUES ({placeholders})",
                        tuple(r)
                    )
                stats["checks_merged"] += 1

        # 5. 合并 template_library (基于 name 去重)
        if "template_library" in src_tables:
            src_cur.execute("SELECT * FROM template_library")
            rows = src_cur.fetchall()
            for r in rows:
                cols = r.keys()
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                if not dry_run:
                    tgt_cur.execute(
                        f"INSERT OR IGNORE INTO template_library ({col_names}) VALUES ({placeholders})",
                        tuple(r)
                    )
                stats["templates_merged"] += 1

        # 6. 合并 datafields
        if "datafields" in src_tables:
            src_cur.execute("SELECT * FROM datafields")
            rows = src_cur.fetchall()
            for r in rows:
                cols = r.keys()
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                if not dry_run:
                    tgt_cur.execute(
                        f"INSERT OR IGNORE INTO datafields ({col_names}) VALUES ({placeholders})",
                        tuple(r)
                    )
                stats["datafields_merged"] += 1

        if not dry_run:
            tgt_conn.commit()

    finally:
        src_conn.close()
        tgt_conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="生产服务器多数据库合流迁移工具")
    parser.add_argument("--source", "-s", type=str, default=None, help="指定需要合并的外部数据库路径 (默认自动扫描 runs/ 等目录)")
    parser.add_argument("--target", "-t", type=str, default=str(DEFAULT_SQLITE_PATH), help="指定目标主库路径 (默认 data/alpha_research.db)")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，仅统计不写入")
    parser.add_argument("--cleanup", action="store_true", help="合流完成后将历史分散的旧 db 文件重命名为 .db.bak")
    args = parser.parse_args()

    target_db = Path(args.target).resolve()
    print("======================================================================")
    print("🚀 Alpha Factory 生产服务器数据库合流与治理中心")
    print(f"🎯 权威目标主库: {target_db}")
    print("======================================================================")

    if not target_db.parent.exists():
        target_db.parent.mkdir(parents=True, exist_ok=True)

    sources: List[Path] = []
    if args.source:
        sources.append(Path(args.source))
    else:
        sources = get_all_db_candidates(PROJECT_ROOT)
        # 也探测上级目录
        parent_candidate = PROJECT_ROOT.parent / "data" / "alpha_research.db"
        if parent_candidate.exists() and parent_candidate.resolve() != target_db:
            sources.append(parent_candidate)

    if not sources:
        print("✅ 未在项目内外发现其他分立数据库，当前主库唯一且完整！")
        return

    print(f"🔍 扫描到 {len(sources)} 个需要合并或核查的外部/历史数据库:")
    for s in sources:
        size_mb = s.stat().st_size / (1024 * 1024) if s.exists() else 0.0
        print(f"  • {s} ({size_mb:.2f} MB)")

    total_stats = {
        "expressions_merged": 0,
        "details_merged": 0,
        "checks_merged": 0,
        "templates_merged": 0,
        "datafields_merged": 0,
    }

    for s in sources:
        print(f"\n📦 正在合流: {s} ➔ {target_db} ...")
        stats = merge_single_db(s, target_db, dry_run=args.dry_run)
        for k, v in stats.items():
            total_stats[k] += v
        print(f"   已扫描条目: {stats}")

        if args.cleanup and not args.dry_run and s.exists():
            backup_path = s.with_suffix(".db.merged_bak")
            s.rename(backup_path)
            print(f"   🗑️ 已将旧库安全备份为: {backup_path.name}")

    print("\n======================================================================")
    print("🎉 数据库合流与归一化完成！全量统计如下:")
    print(f"  • 候选表达式: {total_stats['expressions_merged']} 条已入库/去重")
    print(f"  • 因子明细绩效: {total_stats['details_merged']} 条已入库/去重")
    print(f"  • 6维检查结果: {total_stats['checks_merged']} 条已入库/去重")
    print(f"  • 沉淀进化模板: {total_stats['templates_merged']} 个已入库/去重")
    print("======================================================================")
    print("💡 提示: 现已全局锁定绝对路径，后续无论从任何目录启动脚本，均会且仅会读写权威主库！")


if __name__ == "__main__":
    main()
