"""Submission-stage orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alpha_operator_framework.cli.field_pipeline import _read_json, _write_json
from alpha_operator_framework.database import AlphaDatabase, persist_workflow_row
from alpha_operator_framework.database.repository import submission_wf_stage

from .survey import RUNS

def cmd_submit(args) -> None:
    """Submit: 列出候选 → dry-run → check触发.

    步骤:
      1. 读kept文件列出候选
      2. (可选) --execute触发trigger_submission_checks

    Args:
        args: CLI参数

    示例:
        python -m alpha_operator_framework.orchestrator submit \\
            --kept-out runs/cold_deepen_kept.json
    """
    kept_payload = _read_json(Path(args.kept_out))
    kept = (kept_payload.get("kept", kept_payload)
            if isinstance(kept_payload, dict) else kept_payload)

    # 相关性剪枝 (可选, 拉PnL只读去重, 不耗额度; 默认关)
    if getattr(args, "prune_corr", False):
        from alpha_operator_framework.domain.pruning_components.correlation import correlation_prune
        kept, pruned = asyncio.run(correlation_prune(kept))
        print(f"  相关性剪枝: 候选 {len(kept) + len(pruned)} → {len(kept)}")
        if pruned:
            _write_json(
                RUNS / "submit_pruned_corr.json",
                {"pruned": pruned},
            )

    # 本地 SC 预检 (可选, 在 check 前先计算本地相关性; 默认关)
    blue_list: list[dict[str, object]] = []
    yellow_list: list[dict[str, object]] = []
    green_list: list[dict[str, object]] = []
    if getattr(args, "local_sc", False):
        from alpha_operator_framework.domain.pruning_components.self_correlation import local_sc_precheck, LocalCheckConfig
        # 获取已提交 alpha ID 列表 (可选)
        submitted_ids = []
        if getattr(args, "os_alpha_count", 0) > 0:
            try:
                from cnhkmcp.untracked.platform_functions import get_user_alphas
                os_rows = asyncio.run(get_user_alphas(
                    stage="OS", limit=args.os_alpha_count
                ))
                submitted_ids = [r.get("id") for r in os_rows if r.get("id")]
            except Exception as e:
                print(f"  警告: 无法获取已提交 alpha 列表: {e}")

        config = LocalCheckConfig(
            sc_threshold=getattr(args, "sc_threshold", 0.7),
            sc_marginal=getattr(args, "sc_marginal", 0.05),
        )
        blue_list, yellow_list, green_list = asyncio.run(
            local_sc_precheck(kept, submitted_ids, config)
        )
        print(f"  本地 SC 预检: blue={len(blue_list)} yellow={len(yellow_list)} green={len(green_list)}")

        # 写入分级结果
        if green_list:
            _write_json(RUNS / "submit_sc_green.json", {"green": green_list})
        if yellow_list:
            _write_json(RUNS / "submit_sc_yellow.json", {"yellow": yellow_list})

        # green 列表的 alpha 跳过后续 check, 直接标记不可提交
        for row in green_list:
            row["local_sc_skip_check"] = True

        # 后续只处理 blue + yellow
        kept = blue_list + yellow_list

    alpha_ids = [row.get("alpha_id") for row in kept if row.get("alpha_id")]

    print(f"[submit] {len(alpha_ids)} 个候选 (from {args.kept_out})")

    for row in kept:
        print(f"  {row.get('alpha_id')}  sharpe={row.get('sharpe'):.2f} "
              f"fitness={row.get('fitness'):.2f}  {row.get('expression', '')[:60]}")

    if not alpha_ids:
        print("  无候选可提交")
        return

    # 数据库: 刷新 checks 并判断 SC/PC 是否通过 (本地读操作, dry-run 也可执行)
    db = AlphaDatabase()  # 使用默认路径 data/alpha_research.db
    try:
        for row in kept:
            alpha_id = row.get("alpha_id")
            if not alpha_id:
                continue

            persist_workflow_row(db, row, {}, stage="submit", status="check")

            # 从数据库读取 SC/PC 判定
            checks = {c["name"]: c for c in db.get_checks(alpha_id)}
            sc = checks.get("SELF_CORRELATION")
            pc = checks.get("PROD_CORRELATION")
            sc_ok = sc is None or sc.get("result") in ("PASS", "WARNING")
            pc_ok = pc is None or pc.get("result") in ("PASS", "WARNING")

            status = "ready" if (sc_ok and pc_ok) else "optimize"
            db.update_alpha_status(alpha_id, status)  # 保留原 status_platform 行为 (兼容)
            db.update_wf_stage(alpha_id, submission_wf_stage(
                sc.get("result") if sc else None,
                pc.get("result") if pc else None,
            ))

            print(f"  {alpha_id}: SC={sc.get('result') if sc else 'n/a'}"
                  f"  PC={pc.get('result') if pc else 'n/a'}  → {status}")
    finally:
        db.close()

    if not args.execute:
        print("\n  [DRY RUN] 未触发平台 check。确认候选后加 --execute 运行完整提交终审。")
        print("  所有提交候选均需经过 DecisionApprovalEngine 6 维证据核验与人工决策。")
        return

    # 触发 6 维决策终审治理
    print(f"\n  🛡️ 正在对 {len(alpha_ids)} 个 Alpha 执行 DecisionApprovalEngine 提交前 6 维证据审计...")
    from alpha_operator_framework.domain.evidence import DecisionApprovalEngine, EvidenceLevel, persistent_audit_evidence_record

    db = AlphaDatabase()
    try:
        ready_count = 0
        for aid in alpha_ids:
            details = db.get_alpha_details(aid)
            if not details:
                continue
            is_m = {
                "sharpe": getattr(details, "sharpe", 0.0),
                "fitness": getattr(details, "fitness", 0.0),
                "turnover": getattr(details, "turnover", 0.0),
                "margin": getattr(details, "margin", 0.0),
            }
            checks = db.get_alpha_checks(aid)
            checks_dicts = [{"name": c.check_name, "result": c.result, "value": c.value} for c in checks] if checks else []
            evidence_record = persistent_audit_evidence_record(details, checks)
            rep = DecisionApprovalEngine.evaluate(
                alpha_id=aid,
                evidence_level=EvidenceLevel.PLATFORM_IS,
                is_metrics=is_m,
                checks=checks_dicts,
                sc_value=getattr(details, "sc_value", None),
                pc_value=getattr(details, "pc_value", None),
                judge_verdict="READY" if getattr(details, "grade", "") == "READY" else "REVIEW",
                evidence_record=evidence_record,
            )
            if rep.approved:
                ready_count += 1
                db.update_wf_stage(aid, "submission_ready")
                print(f"    ✅ Alpha {aid}: 通过 6 维证据终审，已标记为 submission_ready")
            else:
                db.update_wf_stage(aid, "needs_optimization")
                print(f"    ⚠️ Alpha {aid}: 终审未通过 (原因: {'; '.join(rep.rejection_reasons)})")

        print(f"\n  📊 提交终审审计完成: {ready_count}/{len(alpha_ids)} 个 Alpha 达标 SUBMISSION_READY。")
    finally:
        db.close()

__all__ = ["cmd_submit"]
