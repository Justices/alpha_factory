#!/usr/bin/env python
"""
数据库使用示例 — 展示如何使用SQLite管理alpha

本示例展示:
  1. 插入alpha表达式
  2. 保存回测结果
  3. 查询和筛选alpha
  4. 批量导入CSV
  5. 集成到工作流
"""

import sys
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework.database import (
    AlphaDatabase,
    AlphaExpression,
    AlphaDetail,
)


# ---------------------------------------------------------------------------
# 示例1: 插入alpha表达式
# ---------------------------------------------------------------------------

def example_insert_expression():
    """示例: 插入alpha表达式."""
    print("\n" + "="*70)
    print("示例1: 插入alpha表达式")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    # 插入表达式
    expression = "group_neutralize(ts_rank(rank(close)/rank(volume), 10), industry)"
    settings = {
        "region": "EUR",
        "universe": "TOP2500",
        "delay": 1,
        "decay": 6.0,
        "neutralization": "SUBINDUSTRY",
        "truncation": 0.08
    }

    expr_id = db.insert_expression(expression, settings)
    print(f"\n表达式ID: {expr_id}")

    # 查询表达式
    expr_sha = db.compute_sha(expression)
    expr = db.get_expression_by_sha(expr_sha)

    if expr:
        print(f"表达式SHA: {expr.expression_sha}")
        print(f"表达式: {expr.expression[:50]}...")
        print(f"创建时间: {expr.created_at}")

    db.close()


# ---------------------------------------------------------------------------
# 示例2: 保存回测结果
# ---------------------------------------------------------------------------

def example_save_backtest_result():
    """示例: 保存回测结果."""
    print("\n" + "="*70)
    print("示例2: 保存回测结果")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    alpha_id = "alpha_001"
    expression = "ts_rank(close, 22)"
    result = {
        "sharpe": 1.85,
        "fitness": 1.45,
        "turnover": 0.05,
        "margin": 0.0035,
        "pnl": 8500000,
        "longCount": 75,
        "shortCount": 85,
        "checks": [
            {"name": "LOW_SHARPE", "result": "PASS"},
            {"name": "LOW_FITNESS", "result": "PASS"}
        ]
    }

    # 回测完成后直接保存到 alpha_details
    result["expression"] = expression
    db.save_result_with_checks(alpha_id, result, {
        "region": "EUR", "universe": "TOP2500", "delay": 1,
        "decay": 6.0, "neutralization": "SUBINDUSTRY",
        "truncation": 0.08, "stage": "backtest", "status": "pending",
    })
    print("\n回测结果已保存到 alpha_details")

    db.close()


# ---------------------------------------------------------------------------
# 示例3: 保存alpha详情
# ---------------------------------------------------------------------------

def example_save_alpha_detail():
    """示例: 保存alpha详情(平铺所有字段)."""
    print("\n" + "="*70)
    print("示例3: 保存alpha详情")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    # 构造详情
    detail = AlphaDetail(
        alpha_id="alpha_002",
        expression_sha=db.compute_sha("ts_rank(volume, 22)"),
        expression="ts_rank(volume, 22)",

        # 回测设置
        region="EUR",
        universe="TOP2500",
        delay=1,
        decay=6.0,
        neutralization="SUBINDUSTRY",
        truncation=0.08,

        # 回测指标
        sharpe=1.62,
        fitness=1.15,
        turnover=0.12,
        margin=0.0028,
        pnl=5200000,
        returns=0.165,
        drawdown=0.060,
        long_count=60,
        short_count=70,

        # 平台信息
        grade="AVERAGE",
        stage_platform="IS",
        status_platform="UNSUBMITTED"
    )

    # 保存详情
    detail_id = db.insert_alpha_detail(detail)
    print(f"\nAlpha详情ID: {detail_id}")

    db.close()


# ---------------------------------------------------------------------------
# 示例4: 查询和筛选alpha
# ---------------------------------------------------------------------------

def example_query_alphas():
    """示例: 查询和筛选alpha."""
    print("\n" + "="*70)
    print("示例4: 查询和筛选alpha")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    # 查询高质量alpha
    print("\n查询高质量alpha (sharpe≥1.58, fitness≥1.0):")
    high_quality = db.query_alphas(
        min_sharpe=1.58,
        min_fitness=1.0,
        limit=10
    )

    print(f"  找到{len(high_quality)}个")
    for detail in high_quality[:3]:
        print(f"    {detail.alpha_id}: sharpe={detail.sharpe:.2f} fitness={detail.fitness:.2f}")

    # 查询边缘alpha
    print("\n查询边缘alpha (sharpe在1.2-1.8之间):")
    marginal = db.query_alphas(
        min_sharpe=1.2,
        max_sharpe=1.8,
        limit=20
    )

    print(f"  找到{len(marginal)}个")
    for detail in marginal[:3]:
        print(f"    {detail.alpha_id}: sharpe={detail.sharpe:.2f}")

    # 查询特定地区
    print("\n查询EUR市场的alpha:")
    eur_alphas = db.query_alphas(
        region="EUR",
        limit=10
    )

    print(f"  找到{len(eur_alphas)}个")

    db.close()


# ---------------------------------------------------------------------------
# 示例5: 批量导入CSV
# ---------------------------------------------------------------------------

def example_import_csv():
    """示例: 从CSV批量导入."""
    print("\n" + "="*70)
    print("示例5: 批量导入CSV")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    csv_path = "runs/simulated_alphas_2025-07-29.csv"

    print(f"\n导入CSV: {csv_path}")

    try:
        count = db.import_from_csv(csv_path)
        print(f"成功导入: {count}条记录")
    except Exception as e:
        print(f"导入失败: {e}")
        print("(这是正常的,如果没有安装pandas或CSV不存在)")

    db.close()


# ---------------------------------------------------------------------------
# 示例7: 保存带完整 checks 指标的模拟结果
# ---------------------------------------------------------------------------

def example_save_result_with_checks():
    """示例: 保存带完整 checks 指标(含PC/SC)的模拟结果."""
    print("\n" + "="*70)
    print("示例7: 保存带完整 checks 的模拟结果")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    alpha_id = "alpha_003"
    settings = {
        "region": "EUR",
        "universe": "TOP2500",
        "delay": 1,
        "decay": 6.0,
        "neutralization": "SUBINDUSTRY",
        "truncation": 0.08,
    }
    # 平台 is 块: 标量 PC/SC + 完整 checks 数组
    is_block = {
        "sharpe": 1.85,
        "fitness": 1.45,
        "turnover": 0.05,
        "margin": 0.0035,
        "pnl": 8500000,
        "returns": 0.19,
        "drawdown": 0.052,
        "longCount": 750,
        "shortCount": 850,
        "selfCorrelation": 0.35,
        "prodCorrelation": 0.42,
        "checks": [
            {"name": "LOW_SHARPE", "result": "PASS", "limit": 1.58, "value": 1.85},
            {"name": "LOW_FITNESS", "result": "PASS", "limit": 1.0, "value": 1.45},
            {"name": "SELF_CORRELATION", "result": "PASS", "limit": 0.7, "value": 0.35},
            {"name": "PROD_CORRELATION", "result": "PASS", "limit": 0.7, "value": 0.42},
            {
                "name": "IS_LADDER_SHARPE", "result": "PASS",
                "year": 3, "startDate": "2022-01-01", "endDate": "2024-12-31", "value": 0.82,
            },
            {"name": "MATCHES_PYRAMID", "result": "PASS", "pyramids": 3, "value": 1.0},
            {"name": "MATCHES_THEMES", "result": "PASS", "themes": 2},
            {"name": "CONCENTRATED_WEIGHT", "result": "PASS", "limit": 0.3, "value": 0.15},
        ],
    }

    # 核心方法: 一次事务写 alpha_details + alpha_checks
    db.save_result_with_checks(alpha_id, is_block, settings)
    print(f"\n保存 {alpha_id}: SC={is_block['selfCorrelation']} PC={is_block['prodCorrelation']}")

    # 读回 checks (extra_json 已合并)
    checks = db.get_checks(alpha_id)
    print(f"\n{alpha_id} 共 {len(checks)} 条 checks:")
    for c in checks:
        extra = {k: v for k, v in c.items() if k not in ("name", "result", "limit", "value")}
        suffix = f"  {extra}" if extra else ""
        print(f"  {c['name']:<24} {c['result']:<8} value={c.get('value')}{suffix}")

    # 详情表里的 PC/SC 列
    for d in db.query_alphas(min_sharpe=1.5, limit=50):
        if d.alpha_id == alpha_id:
            print(f"\nalpha_details: sc_result={d.sc_result} sc_value={d.sc_value} "
                  f"pc_result={d.pc_result} pc_value={d.pc_value}")
            print(f"  checks_json 非空: {bool(d.checks_json)}")

    db.close()


# ---------------------------------------------------------------------------
# 示例6: 集成到工作流
# ---------------------------------------------------------------------------

def example_workflow_integration():
    """示例: 集成数据库到工作流."""
    print("\n" + "="*70)
    print("示例6: 集成到工作流")
    print("="*70)

    db = AlphaDatabase("runs/alpha_research.db")

    print("\n典型工作流:")
    print("  1. Survey阶段:")
    print("     - 插入表达式 → insert_expression()")
    print("     - 回测完成后统一保存 → alpha_details")

    print("\n  2. Deepen阶段:")
    print("     - 查询候选 → query_alphas(min_sharpe=1.2, max_sharpe=1.8)")
    print("     - 更新状态 → alpha_details.status_platform='optimize'")

    print("\n  3. Submit阶段:")
    print("     - 查询可提交 → query_alphas(min_sharpe=1.58)")
    print("     - 更新状态 → alpha_details.status_platform='submit'")

    db.close()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main():
    """运行所有示例."""
    print("\n" + "="*70)
    print("数据库使用示例 — Alpha Operator Framework")
    print("="*70)

    example_insert_expression()
    example_save_backtest_result()
    example_save_alpha_detail()
    example_query_alphas()
    example_import_csv()
    example_workflow_integration()
    example_save_result_with_checks()

    print("\n" + "="*70)
    print("所有示例完成!")
    print("="*70)

    print("\n数据库位置: runs/alpha_research.db")
    print("\n表结构:")
    print("  1. alpha_expressions (表达式表, 基于expression_sha去重)")
    print("  2. alpha_details (回测详情表, 平铺所有字段便于查询, 含PC/SC/checks)")
    print("  3. alpha_checks (检查子表, 平台全部提交检查项, 1:N)")


if __name__ == "__main__":
    main()
