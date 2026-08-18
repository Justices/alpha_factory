"""真实闭环验证: loop.run_research_loop 跑 2 轮, 验证字段加权回流+模板蒸馏+配对沉淀三根管道."""
import asyncio
import traceback

from alpha_operator_framework.loop import LoopConfig, run_research_loop
from alpha_operator_framework.database import AlphaDatabase


async def main():
    db = AlphaDatabase("data/alpha_research.db")
    try:
        config = LoopConfig(
            rounds=2,
            region="GBR", universe="TOP700", delay=1,
            top_k_fields=20,        # 字段池 20 个 (控制任务基数)
            backtest_sample_n=8,    # 每轮真实回测 8 个表达式 (1 批, 等待可控)
            execute=True,
            seed=42,
        )
        print("=== 开始 2 轮真实闭环 (GBR/TOP700, 每轮 8 表达式) ===", flush=True)
        history = await run_research_loop(db, config)

        print("\n=== 闭环历史 ===", flush=True)
        for h in history:
            print(f"round={h['round']} 回测结果={h['distilled_stats']} "
                  f"模板蒸馏={h['distilled_templates']} 配对沉淀={h['distilled_pairs']} "
                  f"下一轮字段={len(h['planned_next_fields'])}", flush=True)

        print("\n=== 字段信号沉淀 (round 0) ===", flush=True)
        stats = db.get_field_signal_stats(region="GBR", round_n=0)
        for s in sorted(stats, key=lambda x: -x["hit_rate"])[:8]:
            print(f"  {s['field_id']:30s} trials={s['trials']} signals={s['signal_count']} hit_rate={s['hit_rate']:.2f}", flush=True)

        print("\n=== 蒸馏模板 (distilled 族) ===", flush=True)
        tpls = db.list_templates(families=["distilled"])
        for t in tpls[:8]:
            print(f"  {t.expression_template}", flush=True)

        print("\n=== 配对信号沉淀 ===", flush=True)
        pairs = db.get_pair_signal_stats(region="GBR")
        for p in pairs[:8]:
            print(f"  {p.get('pair_kind')}: {p.get('pair_spec')} hit_rate={p.get('hit_rate')}", flush=True)

        db.close()
    except Exception:
        traceback.print_exc()


try:
    asyncio.run(main())
except Exception:
    traceback.print_exc()
print("\nDONE", flush=True)
