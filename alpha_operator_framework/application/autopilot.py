"""Autopilot use case, isolated from the command-line adapter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_autopilot(args: Any, config_path: Path) -> dict[str, Any]:
    """运行全自动研究、证据评审与可选的数据库存储清理流水线。

    Args:
        args: 命令行传入的参数对象，需包含 region、universe、execute、min_sharpe、min_fitness 等字段。
        config_path: 配置文件路径。

    Returns:
        dict[str, Any]: 包含研究摘要报告 markdown 字符串及审批通过的因子列表的字典：
            - "research": 研究报告的 Markdown 摘要
            - "approved": 审核通过并标记为 submission_ready 的因子字典列表
    """
    from alpha_operator_framework.domain.evidence import EvidenceLevel, SubmissionApprovalEngine, persistent_audit_evidence_record
    from alpha_operator_framework.infrastructure.maintenance import clean_storage, initialize_storage, open_alpha_database, storage_path, verify_storage

    logger.info("开始执行自动驾驶流程 (Autopilot)... 配置文件路径: %s", config_path)

    if not verify_storage(config_path):
        logger.info("存储校验未通过，正在初始化存储...")
        initialize_storage(config_path, reset=False)
    else:
        logger.info("存储校验通过")

    if getattr(args, "paper", None):
        logger.info("检测到文献参数，启动文献提炼流水线: %s", args.paper)
        from alpha_operator_framework.research import run_literature_research_pipeline
        result = run_literature_research_pipeline(literature_source=args.paper, region=args.region, universe=args.universe, neutralization=args.neutralization, delay=args.delay, decay=args.decay, datasets=[item.strip() for item in args.datasets.split(",") if item.strip()] if getattr(args, "datasets", None) else None, execute_on_platform=args.execute, database_path=storage_path(config_path), save_to_db=True, output_report_path=None)
    else:
        logger.info("未检测到文献参数，启动地毯式盲挖挖掘流水线...")
        from alpha_operator_framework.carpet import run_stratified_carpet_mining
        result = run_stratified_carpet_mining(region=args.region, universe=args.universe, datasets=[item.strip() for item in args.datasets.split(",") if item.strip()] if getattr(args, "datasets", None) else None, sample_per_family=args.sample_per_family, batch_size=args.batch_size, delay=args.delay, decay=args.decay, neutralization=args.neutralization, truncation=args.truncation, execute=args.execute, seed=getattr(args, "seed", None), output_report_path=None)
    
    logger.info("研究挖掘流水线执行完毕，开始提取潜在的高表现 Alpha 因子进行审核...")
    database = open_alpha_database(config_path)
    approved: list[dict[str, Any]] = []
    try:
        top_alphas = list(database.get_top_performing_alphas(min_sharpe=args.min_sharpe, min_fitness=args.min_fitness))
        logger.info("从数据库中检索出 %d 个待评估的高表现因子", len(top_alphas))
        for row in top_alphas:
            alpha_id = row["alpha_id"]
            stored_checks = database.get_alpha_checks(alpha_id)
            checks = [{"name": check.check_name, "result": check.result, "value": check.value} for check in stored_checks]
            evidence_record = persistent_audit_evidence_record(row, stored_checks)
            
            logger.info("正在评估因子 %s (Sharpe: %.4f, Fitness: %.4f)", alpha_id, row["sharpe"], row["fitness"])
            review = SubmissionApprovalEngine.evaluate(alpha_id=alpha_id, evidence_level=EvidenceLevel.PLATFORM_IS, is_metrics={key: row[key] for key in ("sharpe", "fitness", "turnover", "margin")}, checks=checks, sc_value=row["sc_value"], pc_value=row["pc_value"], judge_verdict="READY", evidence_record=evidence_record)
            
            stage = "submission_ready" if review.approved else "needs_optimization"
            logger.info("因子 %s 评估完成，审批通过: %s，更新工作流状态为: %s", alpha_id, review.approved, stage)
            database.update_wf_stage(alpha_id, stage)
            if review.approved: 
                approved.append(row)
    except Exception as e:
        logger.exception("自动驾驶审批逻辑中出现异常: %s", e)
        raise
    finally:
        database.close()
        logger.info("数据库连接已关闭")

    if args.execute and not getattr(args, "no_clean", False):
        logger.info("开始执行存储空间清理 (清除过期/无效数据)...")
        clean_storage(config_path, mode="stale", dry_run=False, vacuum=True)
        logger.info("存储空间清理完毕")

    logger.info("自动驾驶流程执行结束，本次共审批通过 %d 个因子", len(approved))
    return {"research": result.summary_markdown(), "approved": approved}
