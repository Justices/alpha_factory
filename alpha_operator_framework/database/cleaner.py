"""数据库清理与维护工具 (Database Cleaner & Maintenance).

支持清理失败任务、剪枝表达式、孤儿记录、全量重置数据及 VACUUM 磁盘空间释放。
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from alpha_operator_framework.database.config import get_database_path
from alpha_operator_framework.database.connection import DatabaseConnectionManager
from alpha_operator_framework.infrastructure.storage import StorageConfig

logger = logging.getLogger("clean_db")

# 默认数据库路径 (支持环境变量配置)
DEFAULT_DB_PATH = get_database_path()


@dataclass
class CleanReport:
    """清理统计报告."""

    deleted_expressions: int = 0
    deleted_details: int = 0
    deleted_checks: int = 0
    deleted_batches: int = 0
    deleted_sim_results: int = 0
    deleted_opt_queue: int = 0
    deleted_super_candidates: int = 0
    deleted_event_logs: int = 0
    vacuumed: bool = False
    size_before_bytes: int = 0
    size_after_bytes: int = 0

    def summary_text(self) -> str:
        """获取清理统计报告的格式化摘要文本。"""
        saved_mb = (self.size_before_bytes - self.size_after_bytes) / (1024 * 1024)
        lines = [
            "🧹 数据库清理与维护完成:",
            f"   • 清理表达式 (alpha_expressions):      {self.deleted_expressions}",
            f"   • 清理回测详情 (alpha_details):         {self.deleted_details}",
            f"   • 清理检查项 (alpha_checks):            {self.deleted_checks}",
            f"   • 清理仿真批次 (simulation_batches):   {self.deleted_batches}",
            f"   • 清理单项结果 (simulation_results):   {self.deleted_sim_results}",
            f"   • 清理优化队列 (alpha_optimization_queue): {self.deleted_opt_queue}",
            f"   • 清理超级因子 (super_alpha_candidates): {self.deleted_super_candidates}",
            f"   • 清理事件日志 (event_log):            {self.deleted_event_logs}",
            f"   • 磁盘空间整理 (VACUUM):               {'已完成' if self.vacuumed else '未执行'}",
            f"   • 文件大小变化:                        {self.size_before_bytes / 1024 / 1024:.2f} MB ➔ {self.size_after_bytes / 1024 / 1024:.2f} MB (释放 {max(0.0, saved_mb):.2f} MB)",
        ]
        return "\n".join(lines)


class DatabaseCleaner:
    """数据库清理与维护器，支持多种细粒度数据修剪模式。"""

    def __init__(self, db_path: Path | StorageConfig = DEFAULT_DB_PATH):
        """初始化清理与维护工具。

        Args:
            db_path: 数据库路径或存储配置。
        """
        self.storage = db_path if isinstance(db_path, StorageConfig) else StorageConfig.from_mapping({"driver": "sqlite", "path": str(db_path)})
        self.db_path = Path(self.storage.url.removeprefix("sqlite:///")) if self.storage.driver == "sqlite" else None

    def _get_size(self) -> int:
        total = 0
        for ext in ("", "-wal", "-shm"):
            if self.db_path is None:
                return 0
            f = Path(str(self.db_path) + ext)
            if f.exists():
                total += f.stat().st_size
        return total

    def vacuum_only(self, verbose: bool = True) -> CleanReport:
        """仅执行 WAL Checkpoint 与 VACUUM 回收磁盘物理空间，不删除任何业务数据。"""
        logger.info("触发仅空间收缩 (VACUUM) 维护模式")
        return self.clean(mode="vacuum", dry_run=False, vacuum=True, verbose=verbose)

    def clean(
        self,
        mode: str = "failed",
        dry_run: bool = False,
        vacuum: bool = True,
        verbose: bool = True,
    ) -> CleanReport:
        """执行数据清理与维护。

        Args:
            mode: 清理模式:
                  - 'failed': 仅清理失败/异常任务 (status='failed', alpha_id LIKE 'FAILED_%')
                  - 'pruned': 清理被剪枝淘汰的表达式
                  - 'pending': 清理未回测的 pending 任务
                  - 'stale': 综合清理 failed + pruned + 孤儿记录
                  - 'all_data': 清空所有回测数据与事件 (保留表结构、模板库与剪枝规则)
                  - 'vacuum': 不删除任何业务数据，仅执行 WAL checkpoint 与 VACUUM 释放磁盘空间
            dry_run: 若为 True，仅统计将删除的行数，不实际执行 DELETE
            vacuum: 清理后是否执行 VACUUM 释放物理磁盘空间
            verbose: 是否打印输出

        Returns:
            CleanReport: 包含清理条目数与空间变化的统计报告。
        """
        logger.info("启动数据库清理工作，模式=%s, dry_run=%s, vacuum=%s", mode, dry_run, vacuum)

        if self.db_path is not None and not self.db_path.exists():
            logger.warning("数据库文件不存在，取消清理: %s", self.db_path)
            if verbose:
                print(f"❌ 数据库文件不存在: {self.db_path}")
            return CleanReport()

        report = CleanReport(size_before_bytes=self._get_size())
        manager = DatabaseConnectionManager(self.storage)
        conn = manager.get_connection()
        if self.storage.driver == "sqlite":
            conn.execute("PRAGMA foreign_keys = ON")

        try:
            cursor = conn.cursor()
            existing_tables = set(inspect(manager.engine).get_table_names())

            if mode == "vacuum":
                logger.info("真空收缩维护模式，不删除任何数据")
                pass

            elif mode == "failed":
                logger.info("准备清理失败或异常的因子回测数据...")
                if "alpha_details" in existing_tables:
                    cursor.execute("SELECT alpha_id FROM alpha_details WHERE alpha_id LIKE 'FAILED_%' OR grade = 'FAILED'")
                    failed_alpha_ids = [r[0] for r in cursor.fetchall()]

                    if failed_alpha_ids:
                        logger.info("发现 %d 个失败的因子详情记录待清除", len(failed_alpha_ids))
                        placeholders = ",".join("?" for _ in failed_alpha_ids)
                        if "alpha_checks" in existing_tables:
                            cursor.execute(f"SELECT COUNT(*) FROM alpha_checks WHERE alpha_id IN ({placeholders})", failed_alpha_ids)
                            report.deleted_checks = cursor.fetchone()[0]
                            if not dry_run:
                                cursor.execute(f"DELETE FROM alpha_checks WHERE alpha_id IN ({placeholders})", failed_alpha_ids)

                        cursor.execute(f"SELECT COUNT(*) FROM alpha_details WHERE alpha_id IN ({placeholders})", failed_alpha_ids)
                        report.deleted_details = cursor.fetchone()[0]
                        if not dry_run:
                            cursor.execute(f"DELETE FROM alpha_details WHERE alpha_id IN ({placeholders})", failed_alpha_ids)

                # 清理 status='failed' 的表达式
                if "alpha_expressions" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM alpha_expressions WHERE status = 'failed'")
                    report.deleted_expressions = cursor.fetchone()[0]
                    if not dry_run:
                        cursor.execute("DELETE FROM alpha_expressions WHERE status = 'failed'")

                # 清理 status='failed' 的批次
                if "simulation_batches" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM simulation_batches WHERE status = 'failed'")
                    report.deleted_batches = cursor.fetchone()[0]
                    if not dry_run:
                        if "simulation_results" in existing_tables:
                            cursor.execute("DELETE FROM simulation_results WHERE status = 'failed'")
                        cursor.execute("DELETE FROM simulation_batches WHERE status = 'failed'")

            elif mode == "pruned":
                logger.info("准备清理被剪枝的因子表达式...")
                if "alpha_expressions" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM alpha_expressions WHERE pruning_status = 'pruned'")
                    report.deleted_expressions = cursor.fetchone()[0]
                    if not dry_run:
                        cursor.execute("DELETE FROM alpha_expressions WHERE pruning_status = 'pruned'")

            elif mode == "pending":
                logger.info("准备清理处于待回测 (pending) 状态的任务...")
                if "alpha_expressions" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM alpha_expressions WHERE status = 'pending'")
                    report.deleted_expressions = cursor.fetchone()[0]
                    if not dry_run:
                        cursor.execute("DELETE FROM alpha_expressions WHERE status = 'pending'")

            elif mode == "stale":
                logger.info("综合清理过期、剪枝和失效孤儿记录...")
                # 清理 failed + pruned + 孤儿 checks
                if "alpha_expressions" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM alpha_expressions WHERE status = 'failed' OR pruning_status = 'pruned'")
                    report.deleted_expressions = cursor.fetchone()[0]
                    if not dry_run:
                        cursor.execute("DELETE FROM alpha_expressions WHERE status = 'failed' OR pruning_status = 'pruned'")

                if "alpha_checks" in existing_tables and "alpha_details" in existing_tables:
                    cursor.execute("SELECT COUNT(*) FROM alpha_checks WHERE alpha_id NOT IN (SELECT alpha_id FROM alpha_details)")
                    report.deleted_checks = cursor.fetchone()[0]
                    if not dry_run:
                        cursor.execute("DELETE FROM alpha_checks WHERE alpha_id NOT IN (SELECT alpha_id FROM alpha_details)")

            elif mode == "all_data":
                logger.info("⚠️ 警告：正在执行数据全量清空清扫...")
                # 清空所有实验数据 (保留 template_library, template_prune_rules, datafields, schema_version)
                tables_to_clear = [
                    ("alpha_checks", "deleted_checks"),
                    ("alpha_details", "deleted_details"),
                    ("alpha_expressions", "deleted_expressions"),
                    ("simulation_results", "deleted_sim_results"),
                    ("simulation_batches", "deleted_batches"),
                    ("alpha_optimization_queue", "deleted_opt_queue"),
                    ("super_alpha_candidates", "deleted_super_candidates"),
                    ("event_log", "deleted_event_logs"),
                ]
                for table, rep_field in tables_to_clear:
                    if table in existing_tables:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        setattr(report, rep_field, cursor.fetchone()[0])
                        if not dry_run:
                            cursor.execute(f"DELETE FROM {table}")

            if not dry_run:
                conn.commit()
                logger.info("清理数据库数据成功，事务已提交")

            cursor.close()

            # 执行 VACUUM 释放磁盘物理空间
            if not dry_run and (vacuum or mode == "vacuum"):
                try:
                    logger.info("开始对数据库执行 VACUUM 收缩整理，重置 WAL 日志大小...")
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    old_iso = conn.isolation_level
                    conn.isolation_level = None
                    conn.execute("VACUUM")
                    conn.isolation_level = old_iso
                    report.vacuumed = True
                    logger.info("VACUUM 物理空间回收成功")
                except Exception as ve:
                    logger.exception("VACUUM 释放异常: %s", ve)

            report.size_after_bytes = self._get_size()
            logger.info("数据库清理流程结束。%s", report.summary_text().replace("\n", "; "))

            if verbose:
                if dry_run:
                    print("🔍 [Dry-Run 模式预览] 预计清理结果:")
                print(report.summary_text())

            return report

        except Exception as e:
            logger.exception("执行数据库清理维护异常失败: %s", e)
            if verbose:
                print(f"❌ 清理失败: {e}", file=sys.stderr)
            return report
        finally:
            manager.close_all()


def clean_alpha_research_db(
    db_path: Path | StorageConfig = DEFAULT_DB_PATH,
    mode: str = "failed",
    dry_run: bool = False,
    vacuum: bool = True,
    verbose: bool = True,
) -> CleanReport:
    """便捷清理与释放空间接口."""
    cleaner = DatabaseCleaner(db_path)
    return cleaner.clean(mode=mode, dry_run=dry_run, vacuum=vacuum, verbose=verbose)


def vacuum_database(
    db_path: Path | StorageConfig = DEFAULT_DB_PATH,
    verbose: bool = True,
) -> CleanReport:
    """便捷释放 SQLite 磁盘物理空间接口 (不删除任何业务数据)."""
    cleaner = DatabaseCleaner(db_path)
    return cleaner.vacuum_only(verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description="Alpha Factory 数据库清理与磁盘空间释放工具")
    parser.add_argument("--database", "--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite 数据库路径")
    parser.add_argument(
        "--mode",
        choices=["failed", "pruned", "pending", "stale", "all_data", "vacuum"],
        default="failed",
        help="清理模式: failed (默认失败任务) / pruned (剪枝条目) / pending (未跑任务) / stale (综合过期数据) / all_data (全量清空数据) / vacuum (仅释放磁盘空间)",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览将删除的条目数，不实际执行删除")
    parser.add_argument("--no-vacuum", action="store_true", help="不执行 VACUUM 磁盘空间释放")

    args = parser.parse_args()
    clean_alpha_research_db(
        db_path=args.database,
        mode=args.mode,
        dry_run=args.dry_run,
        vacuum=not args.no_vacuum,
    )


if __name__ == "__main__":
    main()
