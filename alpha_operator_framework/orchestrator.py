"""Compatibility CLI entry point for survey → deepen → submit orchestration."""

from __future__ import annotations

import argparse

from alpha_operator_framework.orchestration import cmd_deepen, cmd_run_all, cmd_submit, cmd_survey

def build_parser() -> argparse.ArgumentParser:
    """构建CLI解析器."""
    ap = argparse.ArgumentParser(
        description="Alpha Operator Framework — survey → deepen → submit",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common(p, simulate_default=True):
        """添加通用参数."""
        p.add_argument("--region", default="EUR")
        p.add_argument("--universe", default="TOP2500")
        p.add_argument("--delay", type=int, default=1)
        p.add_argument("--dataset", default="", help="数据集ID; 空=全字段")
        p.add_argument("--search", default="", help="字段搜索词")
        p.add_argument("--type", default="", help="字段类型过滤")
        p.add_argument("--fields-file", default=None,
                       help="本地字段文件（CSV 或 JSON 数组）；提供后不请求平台字段接口")
        p.add_argument("--field-source", choices=["auto", "local", "platform"], default="auto",
                       help="字段来源：auto=本地目录优先后平台，local=仅本地，platform=仅平台")
        p.add_argument("--fields-file-type", choices=["auto", "csv", "json"], default="auto",
                       help="本地目录读取的文件类型；指定 --fields-file 时也用于声明预期格式")
        p.add_argument("--force-refresh", action="store_true",
                       help="强制刷新缓存，重新从平台获取数据")
        p.add_argument("--page-delay", type=float, default=0.5,
                       help="平台翻页间隔(秒)，防429")
        p.add_argument("--min-coverage", type=float, default=0.0)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--backfill", type=int, default=120)
        p.add_argument("--winsorize-std", type=float, default=4.0)
        p.add_argument("--no-cold", action="store_true", help="不优先冷门字段")
        p.add_argument("--no-semantic-pairs", action="store_false", dest="semantic_pairs",
                       help="关闭 positive/negative 与 *_cap 的定向二元配对")
        p.add_argument("--pair", dest="pairs", action="append", default=[],
                       metavar="KIND:LEFT:RIGHT[:DENOMINATOR]",
                       help="Explicit binary base signal; repeat as needed")
        p.add_argument("--prune-fields", type=int, default=0,
                       help="语义剪枝: 每语义类保留字段代表数(0=关)")
        p.add_argument("--execute", action="store_true", help="实际消耗额度(默认dry-run)")
        p.add_argument("--poll-interval", type=float, default=5.0,
                       help="批次轮询间隔(秒)")
        p.add_argument("--max-wait", type=float, default=600.0,
                       help="每批次最大等待时间(秒)")

        if simulate_default:
            p.add_argument("--batch-size", type=int, default=8)
            p.add_argument("--neutralization", default="SUBINDUSTRY")

    # ═══════════════════════════════════════════════════════════════════
    # run-all 子命令 (一键运行)
    # ═══════════════════════════════════════════════════════════════════
    run_all = sub.add_parser("run-all", help="一键运行: Survey → Deepen → Submit")
    add_common(run_all)

    # Survey 参数
    run_all.add_argument("--survey-sample", type=int, default=80, help="Survey阶段字段池样本数")
    run_all.add_argument("--backtest-sample", type=int, default=0,
                         help="从一阶表达式目录随机抽样回测数量(<=0=全部)")

    # 策略相关参数
    run_all.add_argument("--strategy", choices=["multi_stage", "template", "test", "multivariate", "composite"],
                         default="template", help="任务生成策略类型")
    run_all.add_argument("--template-categories", nargs="*", default=None,
                         help="限制使用的模板/字段 category (如 pv analyst; 默认全匹配)")
    run_all.add_argument("--test-operators", nargs="*", default=["rank", "quantile"],
                         help="测试策略使用的算子 (rank quantile winsorize)")

    # 兼容旧参数 (deprecated)
    run_all.add_argument("--unary", action="store_true", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    run_all.add_argument("--raw-first-order", action="store_false", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    run_all.add_argument("--template-library", action="store_true", default=True,
                         help="[DEPRECATED] 使用 --strategy template")
    run_all.add_argument("--no-template-library", action="store_false", dest="template_library",
                         help="[DEPRECATED] 使用 --strategy multi_stage")
    run_all.add_argument("--binary", action="store_true", default=True)
    run_all.add_argument("--ternary", action="store_true", default=False)
    run_all.add_argument("--quaternary", action="store_true", default=False)
    run_all.add_argument("--groups", nargs="*", default=None, help="GROUP字段列表")
    run_all.add_argument("--top-n", type=int, default=3, help="输出top-N模板")

    # Deepen 参数
    run_all.add_argument("--deepen-sample", type=int, default=400, help="Deepen阶段字段池上限")
    run_all.add_argument("--sharpe", type=float, default=1.58)
    run_all.add_argument("--fitness", type=float, default=1.0)
    run_all.add_argument("--margin", type=float, default=0.0005)
    run_all.add_argument("--min-turnover", type=float, default=0.01)
    run_all.add_argument("--max-turnover", type=float, default=0.70)
    run_all.add_argument("--prune-per-field", type=int, default=0,
                         help="同字段top-k剪枝: 每字段保留alpha数(0=关)")

    # Submit 参数
    run_all.add_argument("--local-sc", action="store_true",
                         help="check前本地计算SC, 按阈值分级减少平台调用")
    run_all.add_argument("--sc-threshold", type=float, default=0.7,
                         help="SC阈值 (默认0.7, >= 此值标记绿色跳过check)")
    run_all.add_argument("--sc-marginal", type=float, default=0.05,
                         help="SC边缘带 (默认0.05, threshold-marginal~threshold 标记黄色)")
    run_all.add_argument("--os-alpha-count", type=int, default=100,
                         help="拉取已提交alpha数量用于SC计算 (默认100)")
    run_all.add_argument("--prune-corr", action="store_true",
                         help="提交前做相关性剪枝(拉PnL去重, 只读不耗额度)")
    run_all.add_argument("--use-datapack", default="runs/WebData_20260219_V0.10.9.zip",
                         help="使用本地数据包预筛数据集 (默认: runs/WebData_20260219_V0.10.9.zip)")
    run_all.add_argument("--datapack-dataset-mode", default="sweet_spot",
                         choices=["sweet_spot", "top_n", "all"],
                         help="数据集筛选模式: sweet_spot=甜点区, top_n=提交最多, all=全部")
    run_all.add_argument("--datapack-dataset-top", type=int, default=10,
                         help="数据包预筛: 数据集数量上限")

    run_all.set_defaults(func=cmd_run_all)

    # ═══════════════════════════════════════════════════════════════════
    # survey 子命令
    # ═══════════════════════════════════════════════════════════════════
    survey = sub.add_parser("survey", help="调研: 字段池×全模板 → 密度 → top-N")
    add_common(survey)
    survey.add_argument("--sample", type=int, default=80, help="字段池样本数")
    survey.add_argument("--backtest-sample", type=int, default=0,
                        help="从一阶表达式目录随机抽样回测数量(<=0=全部)")
    survey.add_argument("--all-combinations", action="store_true", default=True,
                        help="第一阶段计算已选字段的全部二元/三元/四元组合(默认开启)")
    # --- 策略相关参数 ---
    survey.add_argument("--strategy", choices=["multi_stage", "template", "test", "multivariate", "composite"],
                         default="template", help="任务生成策略类型")
    survey.add_argument("--template-categories", nargs="*", default=None,
                         help="限制使用的模板/字段 category (如 pv analyst; 默认全匹配)")
    survey.add_argument("--test-operators", nargs="*", default=["rank", "quantile"],
                         help="测试策略使用的算子 (rank quantile winsorize)")

    # --- 兼容旧参数 (deprecated) ---
    survey.add_argument("--template-library", action="store_true", default=True,
                         help="[DEPRECATED] 使用 --strategy template")
    survey.add_argument("--no-template-library", action="store_false", dest="template_library",
                         help="[DEPRECATED] 使用 --strategy multi_stage")
    survey.add_argument("--unary", action="store_true", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--raw-first-order", action="store_false", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--binary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--ternary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--quaternary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--groups", nargs="*", default=None, help="GROUP字段列表")
    survey.add_argument("--top-n", type=int, default=3)
    survey.add_argument("--tasks-out", default="survey_tasks.json")
    survey.add_argument("--results-out", default="survey_results.json")
    survey.add_argument("--density-out", default="survey_density.json")
    survey.add_argument("--use-datapack", default=None,
                        help="使用本地数据包预筛数据集 (如: runs/WebData_20260219_V0.10.9.zip)")
    survey.add_argument("--datapack-dataset-mode", default="sweet_spot",
                        choices=["sweet_spot", "top_n", "all"],
                        help="数据集筛选模式: sweet_spot=甜点区, top_n=提交最多, all=全部")
    survey.add_argument("--datapack-dataset-top", type=int, default=10,
                        help="数据包预筛: 数据集数量上限")
    survey.set_defaults(func=cmd_survey)

    # deepen子命令
    deepen = sub.add_parser("deepen", help="深挖: top-N模板×全字段 → 质量门")
    add_common(deepen)
    deepen.add_argument("--density-out", required=True, help="survey产出的密度报告")
    deepen.add_argument("--sample", type=int, default=400, help="深挖字段池上限")
    deepen.add_argument("--sharpe", type=float, default=1.2)
    deepen.add_argument("--fitness", type=float, default=0.7)
    deepen.add_argument("--margin", type=float, default=5.0)
    deepen.add_argument("--min-turnover", type=float, default=0.01)
    deepen.add_argument("--max-turnover", type=float, default=0.70)
    deepen.add_argument("--tasks-out", default="deepen_tasks.json")
    deepen.add_argument("--results-out", default="deepen_results.json")
    deepen.add_argument("--kept-out", default="deepen_kept.json")
    deepen.add_argument("--prune-per-field", type=int, default=0,
                        help="同字段top-k剪枝: 每字段保留alpha数(0=关)")
    deepen.set_defaults(func=cmd_deepen)

    # submit子命令
    submit = sub.add_parser("submit", help="提交: 列出kept → dry-run → check")
    submit.add_argument("--kept-out", required=True, help="deepen产出的kept文件")
    submit.add_argument("--execute", action="store_true", help="实际触发check")
    submit.add_argument("--prune-corr", action="store_true",
                        help="提交前做相关性剪枝(拉PnL去重, 只读不耗额度)")
    submit.add_argument("--local-sc", action="store_true",
                        help="check前本地计算SC, 按阈值分级减少平台调用")
    submit.add_argument("--sc-threshold", type=float, default=0.7,
                        help="SC阈值 (默认0.7, >= 此值标记绿色跳过check)")
    submit.add_argument("--sc-marginal", type=float, default=0.05,
                        help="SC边缘带 (默认0.05, threshold-marginal~threshold 标记黄色)")
    submit.add_argument("--os-alpha-count", type=int, default=100,
                        help="拉取已提交alpha数量用于SC计算 (默认100)")
    submit.add_argument("--database", default=None,
                        help="指定研究数据库路径 (可选, 默认自动获取配置)")
    submit.set_defaults(func=cmd_submit)

    return ap


def main() -> None:
    """CLI入口."""
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()


__all__ = [
    "cmd_survey",
    "cmd_deepen",
    "cmd_submit",
    "cmd_run_all",
    "build_parser",
    "main",
]
