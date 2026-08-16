"""三阶段剪枝逻辑 — survey→deepen→submit 各阶段的数据压缩.

整合 quant 中分散的三处剪枝方法论:

  1. 语义剪枝 (字段级, 回测前)
     源: knowledge_base/field_classification_alpha_guide.md 五步管线第⑤步
     作用: 字段池按语义类别分组, 每类留代表, 压缩搜索空间 (2036→707→39).

  2. 同字段 top-k 剪枝 (结果级, 回测后)
     源: quant/scripts/machine_lib.py::prune
     作用: 每个 datafield 只留 sharpe 最高的 keep_num 个, 防一字段垄断候选.

  3. 相关性剪枝 (候选级, 提交前)
     源: quant/runs/chn_recent_alpha_optimization_20260807/prune_correlations.py
     作用: 按日 PnL 差分做贪心相关性去重, 两两相关 >= threshold 剔除.

设计红线:
  * 本模块不 import alpha_machine、不碰网络 (相关性剪枝的 brain_client 函数内延迟导入)
  * 全部纯函数, 便于离线单测; 输入为字段规格列表 / 模拟结果行列表
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence, Tuple

from .operators import (
    ACCESS_LIMITED_OPS,
    basic_ops,
    extended_ops,
    group_ops,
    ts_ops,
    vec_ops,
)

# ---------------------------------------------------------------------------
# 通用工具 — 与 alpha_machine._metric 同语义 (顶层优先, is 子键兜底)
# ---------------------------------------------------------------------------

def _metric(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    is_block = row.get("is") or {}
    return is_block.get(key)


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


# ---------------------------------------------------------------------------
# 1. 语义剪枝 — 字段级, 回测前
# ---------------------------------------------------------------------------

# 语义类别关键词表. (类别, 关键词集合); 命中先后顺序即优先级.
# 关键词匹配 dataset_id + description (小写).
CATEGORY_RULES: Tuple[Tuple[str, frozenset[str]], ...] = (
    ("market", frozenset({
        "pv1", "pv2", "pv3", "model_raw", "price", "volume", "returns", "close",
        "cap", "trade", "quote", "bid", "ask", "open", "high", "low",
    })),
    ("analyst", frozenset({
        "analyst", "estimate", "target", "recommendation", "consensus", "broker",
        "revision", "rating", "eps_est", "surprise",
    })),
    ("fundamental", frozenset({
        "fundamental", "fund", "income", "balance", "cashflow", "assets", "equity",
        "earnings", "sales", "ebit", "eps", "bps", "dps", "roe", "roa", "margin",
        "revenue", "debt", "dividend", "book",
    })),
    ("model", frozenset({
        "mdl", "model", "ml", "predict", "score", "pca", "factor", "risk",
        "momentum", "value", "quality", "growth", "volatility", "skew",
    })),
    ("alternative", frozenset({
        "news", "sentiment", "social", "search", "option", "emo", "analyst_call",
        "web", "consumer", "supply", "satellite", "transaction",
    })),
    ("structural", frozenset({
        "industry", "sector", "group", "gics", "subindustry", "sta", "universe",
        "classification", "listing", "exchange", "index", "member",
    })),
)

FALLBACK_CATEGORY = "other"


def classify_field(field: Any) -> str:
    """按 dataset_id + description 关键词把字段归到语义类.

    Args:
        field: 含 dataset_id/description 属性的字段对象 (fields.FieldSpec / alpha_machine.FieldSpec)

    Returns:
        语义类别 (market/analyst/fundamental/model/alternative/structural/other)
    """
    dataset = str(getattr(field, "dataset_id", "") or "").lower()
    description = str(getattr(field, "description", "") or "").lower()
    desc_words = set(re.split(r"[\s_\-/]+", description))
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in dataset or kw in description or kw in desc_words:
                return category
    return FALLBACK_CATEGORY


@dataclass(frozen=True)
class SemanticPruneConfig:
    """语义剪枝配置."""

    keep_per_category: int = 3      # 每类保留代表数
    min_coverage: float = 0.0       # 可选覆盖率闸
    prefer_cold: bool = True        # True: 低 userCount 优先 (蓝海降PC), 与 fields.candidate_scalars 一致
    category_rules: Tuple[Tuple[str, frozenset[str]], ...] = CATEGORY_RULES


def semantic_prune_fields(
    field_specs: Sequence[Any],
    config: SemanticPruneConfig = SemanticPruneConfig(),
) -> tuple[list[Any], list[dict[str, Any]]]:
    """字段池按语义类别剪枝: 每类留 keep_per_category 个代表.

    组内排序复用 fields.candidate_scalars 的冷门优先逻辑:
      - prefer_cold=True:  (user_count asc, coverage desc)
      - prefer_cold=False: (coverage desc, user_count asc)

    Args:
        field_specs: 字段规格列表 (需有 id/dataset_id/type/coverage/user_count/description)
        config: 剪枝配置

    Returns:
        (保留字段列表, 剪掉字段列表). 剪掉字段为 dict: {id, category, coverage, user_count}
    """
    keep_n = max(config.keep_per_category, 0)
    buckets: dict[str, list[Any]] = {}
    for f in field_specs:
        if f.type not in ("MATRIX", "VECTOR"):
            continue
        if (getattr(f, "coverage", 0) or 0) < config.min_coverage:
            continue
        buckets.setdefault(classify_field(f), []).append(f)

    kept: list[Any] = []
    pruned: list[dict[str, Any]] = []
    for category, items in buckets.items():
        if config.prefer_cold:
            items = sorted(items, key=lambda f: (f.user_count, -f.coverage, f.id))
        else:
            items = sorted(items, key=lambda f: (-f.coverage, f.user_count, f.id))
        for i, f in enumerate(items):
            if keep_n and i < keep_n:
                kept.append(f)
            else:
                pruned.append({
                    "id": f.id,
                    "category": category,
                    "coverage": getattr(f, "coverage", 0),
                    "user_count": getattr(f, "user_count", 0),
                })
    return kept, pruned


# ---------------------------------------------------------------------------
# 2. 同字段 top-k 剪枝 — 结果级, 回测后
# ---------------------------------------------------------------------------

# 从模板表达式提取底层字段id.
# 两种形态:
#   winsorize(ts_backfill(analyst4_fy1, 120), std=4)   → analyst4_fy1
#   winsorize(ts_backfill(vec_avg(close), 120), std=4)  → close
# 捕获字段名后跟 "," (ts_backfill 后续参数) 或 ")" (内层函数闭合), 二者皆可.
_FIELD_RE = re.compile(r"ts_backfill\((?:[a-zA-Z0-9_]*\()?([a-zA-Z][a-zA-Z0-9_]*)(?:,|\))")
_NO_FIELD = ("__no_field__",)


def extract_field_ids(expression: str) -> frozenset[str]:
    """从模板表达式提取底层字段id集合.

    Args:
        expression: 模拟结果行里的 expression (渲染后的模板)

    Returns:
        字段id frozenset; 解析不到则返回 frozenset(("__no_field__",))
    """
    matched = frozenset(_FIELD_RE.findall(expression or ""))
    return matched if matched else frozenset(_NO_FIELD)


# 已知算子/关键词黑名单, 用于全标识符扫描时的剔除
_KNOWN_OPS = frozenset(
    set(basic_ops) | set(ts_ops) | set(group_ops) | set(vec_ops) | set(extended_ops)
    | set(ACCESS_LIMITED_OPS)
    | {"winsorize", "ts_backfill", "densify", "bucket", "s_log_1p", "ts_step",
       "std", "limit_volume", "rettype", "weight", "range", "if_else"}
)


def extract_fields(expression: str) -> list[str]:
    """提取表达式用到的底层字段id列表(排序去重).

    优先用 ``extract_field_ids`` (ts_backfill 包裹形态); 解析不到时退化为
    全标识符扫描并剔除已知算子/关键词。对 ``ts_delta(close,252)/ts_delay(close,252)``
    这类无包裹表达式也能正确返回字段清单。

    Args:
        expression: alpha表达式

    Returns:
        字段id排序去重列表; 空表达式返回 []
    """
    matched = extract_field_ids(expression)
    if matched != frozenset(_NO_FIELD):
        return sorted(matched)
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression or "")
    return sorted(set(tokens) - _KNOWN_OPS)


@dataclass(frozen=True)
class FieldTopKConfig:
    """同字段 top-k 剪枝配置."""

    keep_per_field: int = 3          # 每个字段保留的 alpha 数
    by_metric: str = "sharpe"        # 组内排序指标
    split_by_sign: bool = True       # True: 正负 sharpe 分开计数 (移植自 machine_lib.py::prune)


def _sign_key(sharpe: float) -> str:
    """返回方向键: 正数 '', 负数 '-', 零视作正."""
    return "-" if sharpe < 0 else ""


def field_topk_prune(
    results: Iterable[dict[str, Any]],
    config: FieldTopKConfig = FieldTopKConfig(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按字段集合分组, 组内按指标降序留 top-k, 其余进剪掉列表.

    Args:
        results: 模拟结果行列表 (需含 expression; 指标在顶层或 is 子键)
        config: 剪枝配置

    Returns:
        (保留行, 剪掉行). 剪掉行附 prune_reason.

    Note:
        split_by_sign=True 时, 正负 sharpe 视为不同方向, 分开计数。
        这与 machine_lib.py::prune 的 "-field" 逻辑一致:
        rank(close) 和 -rank(close) 虽同字段但方向相反,不应归为同一桶。
    """
    keep_n = max(config.keep_per_field, 0)
    metric = config.by_metric
    buckets: dict[frozenset[str], list[dict[str, Any]]] = {}
    for row in results:
        fields_key = extract_field_ids(row.get("expression") or "")
        # 正负方向分开计数 (移植自 machine_lib.py::prune 的 "-field" 逻辑)
        if config.split_by_sign:
            sign = _sign_key(_num(_metric(row, metric)))
            fields_key = frozenset(f"{sign}{f}" for f in fields_key)
        buckets.setdefault(fields_key, []).append(row)

    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for fields_key, items in buckets.items():
        # 组内按指标绝对值降序 (正负方向已由 split_by_sign 分开, 组内同方向)
        items = sorted(items, key=lambda r: abs(_num(_metric(r, metric))), reverse=True)
        label = ", ".join(sorted(fields_key)) if fields_key != frozenset(_NO_FIELD) else "<无字段>"
        for i, row in enumerate(items):
            if keep_n and i < keep_n:
                kept.append(row)
            else:
                pruned.append({
                    **row,
                    "prune_reason": f"same_field_topk:{label}",
                })
    return kept, pruned


# ---------------------------------------------------------------------------
# 4. 本地 SC/PC 预检 — check 前的本地相关性计算
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocalCheckConfig:
    """本地 SC/PC 预检配置."""

    sc_threshold: float = 0.7         # SC 阈值: 与已提交 alpha 相关性 >= 此值标记绿色
    sc_marginal: float = 0.05         # SC 边缘带: threshold ± marginal 为黄色
    pc_threshold: float = 0.7         # PC 阈值 (需 API, 本地仅预留接口)
    pc_marginal: float = 0.05         # PC 边缘带
    years_window: int = 4             # PnL 窗口(年)
    min_periods: int = 100            # 相关矩阵最小重叠期
    concurrency: int = 4              # PnL 拉取并发


async def _fetch_pnl_series(alpha_id: str) -> Any:
    """获取单个 alpha 的日 PnL → 差分 returns Series."""
    import pandas as pd
    from cnhkmcp.untracked.platform_functions import brain_client

    try:
        result = await brain_client.get_alpha_pnl(alpha_id)
        return _pnl_returns(result)
    except Exception:
        return None


async def compute_self_correlation(
    candidate_ids: Sequence[str],
    submitted_ids: Sequence[str],
    config: LocalCheckConfig = LocalCheckConfig(),
) -> dict[str, dict[str, Any]]:
    """
    本地计算候选 alpha 与已提交 alpha 的 SC (Self Correlation).

    移植自 quant/scripts/adaptive_check_submission.py::local_self_correlation.

    流程:
      1. 并发拉取候选和已提交 alpha 的日 PnL → 差分 returns
      2. 计算 4 年窗口内的相关性矩阵
      3. 对每个候选, 取与已提交集的最大相关性
      4. 按阈值分级: green(失败) / yellow(边缘) / blue(通过)

    Args:
        candidate_ids: 候选 alpha ID 列表
        submitted_ids: 已提交 alpha ID 列表 (自己的 OS alpha)
        config: 预检配置

    Returns:
        dict[alpha_id, {"sc": float, "grade": str, "max_corr_with": str}]
        grade: "green"(不可提交) / "yellow"(边缘) / "blue"(可提交)
    """
    if not candidate_ids:
        return {}

    import pandas as pd
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    sem = asyncio.Semaphore(max(config.concurrency, 1))

    async def one(aid: str):
        async with sem:
            series = await _fetch_pnl_series(aid)
            return aid, series

    # 并发拉取候选 PnL
    cand_fetched = await asyncio.gather(*(one(aid) for aid in candidate_ids))
    cand_series: dict[str, Any] = {}
    for aid, s in cand_fetched:
        if s is not None and len(s) >= config.min_periods:
            cand_series[aid] = s

    # 并发拉取已提交 PnL (可选)
    os_series: dict[str, Any] = {}
    if submitted_ids:
        os_fetched = await asyncio.gather(*(one(aid) for aid in submitted_ids))
        for aid, s in os_fetched:
            if s is not None and len(s) >= config.min_periods:
                os_series[aid] = s

    # 时间窗口
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.DateOffset(years=config.years_window)

    # 构建 DataFrame
    all_series = {**cand_series, **os_series}
    if not all_series:
        return {aid: {"sc": None, "grade": "unknown", "error": "no_pnl"} for aid in candidate_ids}

    frame = pd.DataFrame(all_series)

    # 时间窗口过滤
    frame = frame[(frame.index >= start_date) & (frame.index <= end_date)]

    # 相关矩阵
    corr = frame.corr(min_periods=config.min_periods)

    results: dict[str, dict[str, Any]] = {}
    threshold = config.sc_threshold
    marginal = config.sc_marginal

    for aid in candidate_ids:
        if aid not in cand_series:
            results[aid] = {"sc": None, "grade": "unknown", "error": "no_pnl"}
            continue

        # 计算与已提交集的最大相关性
        max_corr = 0.0
        max_corr_with = ""
        for os_id in os_series:
            if os_id == aid:
                continue
            try:
                val = corr.loc[aid, os_id]
                if pd.notna(val):
                    val = abs(float(val))
                    if val > max_corr:
                        max_corr = val
                        max_corr_with = os_id
            except KeyError:
                pass

        # 分级
        if max_corr >= threshold:
            grade = "green"  # 不可提交, 跳过 check
        elif max_corr >= threshold - marginal:
            grade = "yellow"  # 边缘可优化
        else:
            grade = "blue"   # 可提交

        results[aid] = {
            "sc": round(max_corr, 4),
            "grade": grade,
            "max_corr_with": max_corr_with,
        }

    return results


async def local_sc_precheck(
    candidates: Sequence[dict[str, Any]],
    submitted_ids: Sequence[str] = (),
    config: LocalCheckConfig = LocalCheckConfig(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    本地 SC 预检: 按 SC 分级候选, 减少平台 check 调用.

    移植自 adaptive_check_submission.py 的 Layer 4 逻辑.

    Args:
        candidates: 候选行列表 (需含 alpha_id)
        submitted_ids: 已提交 alpha ID 列表 (空则自动拉取)
        config: 预检配置

    Returns:
        (blue_list, yellow_list, green_list)
        blue: SC < threshold - marginal → 可提交 (建议 check)
        yellow: SC 在边缘带 → 边缘可优化 (可选 check)
        green: SC >= threshold → 不可提交 (跳过 check)

    Note:
        submitted_ids 为空时, 需要调用方自己拉取已提交 alpha 列表.
        本函数只做纯本地计算, 不访问 correlations/prod API.
    """
    if not candidates:
        return [], [], []

    alpha_ids = [row.get("alpha_id") for row in candidates if row.get("alpha_id")]
    by_id = {row.get("alpha_id"): row for row in candidates if row.get("alpha_id")}

    sc_results = await compute_self_correlation(alpha_ids, submitted_ids, config)

    blue: list[dict[str, Any]] = []
    yellow: list[dict[str, Any]] = []
    green: list[dict[str, Any]] = []

    for aid in alpha_ids:
        row = by_id.get(aid)
        if row is None:
            continue
        result = sc_results.get(aid, {})
        grade = result.get("grade", "unknown")
        enriched = {**row, "local_sc": result.get("sc"), "local_sc_grade": grade}
        if grade == "blue":
            blue.append(enriched)
        elif grade == "yellow":
            yellow.append(enriched)
        elif grade == "green":
            green.append(enriched)
        else:
            # unknown → 放入 yellow 待处理
            yellow.append(enriched)

    return blue, yellow, green

@dataclass(frozen=True)
class CorrelationPruneConfig:
    """相关性剪枝配置."""

    threshold: float = 0.7            # 两两绝对相关 >= 此值剔除
    min_periods: int = 100            # 相关矩阵最小重叠期
    concurrency: int = 4              # PnL 拉取并发
    drop_if_pnl_missing: bool = False  # True=缺PnL剪掉, False=保留但标注
    order_by: str = "sharpe"          # 贪心保留顺序指标


def _pnl_returns(payload: dict) -> Any:
    """解析平台 PnL payload → 日差分 returns Series. 移植自 prune_correlations.py."""
    import pandas as pd

    records = payload.get("records") or []
    schema = (payload.get("schema") or {}).get("properties") or []
    names = [item.get("name") if isinstance(item, dict) else item for item in schema]
    rows: list[dict] = []
    for record in records:
        if isinstance(record, dict):
            rows.append(record)
        elif names:
            rows.append(dict(zip(names, record)))
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    if not {"date", "pnl"}.issubset(frame.columns):
        return None
    frame["date"] = pd.to_datetime(frame["date"])
    pnl = frame.sort_values("date").set_index("date")["pnl"].astype(float)
    returns = pnl.diff().dropna()
    return returns if len(returns) >= 2 else None


async def correlation_prune(
    candidates: Sequence[dict[str, Any]],
    config: CorrelationPruneConfig = CorrelationPruneConfig(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按日 PnL 差分对候选做贪心相关性去重.

    流程 (移植 prune_correlations.py):
      1. 按 order_by 指标降序排序候选
      2. 并发拉取每个 alpha_id 的日 PnL → 差分 returns
      3. 贪心保留: 新候选与已保留者两两绝对相关 >= threshold 则剔除

    Args:
        candidates: 候选行列表 (需含 alpha_id; sharpe/fitness 顶层或 is 子键)
        config: 剪枝配置

    Returns:
        (保留行, 剪掉行). 剪掉行附 prune_reason (pairwise_corr / pnl_unavailable).
        缺 PnL 的行按 drop_if_pnl_missing 决定保留(标注)或剪掉.

    Note:
        brain_client 延迟导入; 本函数为 async, 由调用方 asyncio.run.
    """
    if not candidates:
        return [], []

    order_key = config.order_by
    ranked = sorted(
        candidates,
        key=lambda row: (_num(_metric(row, order_key)), _num(_metric(row, "fitness"))),
        reverse=True,
    )

    # 无 alpha_id 的行无法拉 PnL → 直接保留, 标注
    without_id = [row for row in ranked if not row.get("alpha_id")]
    ranked = [row for row in ranked if row.get("alpha_id")]

    # 延迟导入平台客户端 (只读, 不耗额度)
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    sem = asyncio.Semaphore(max(config.concurrency, 1))

    async def one(row: dict[str, Any]):
        alpha_id = row["alpha_id"]
        async with sem:
            try:
                result = await brain_client.get_alpha_pnl(alpha_id)
                return alpha_id, _pnl_returns(result), None
            except Exception as exc:  # 保留审计记录, 不静默丢弃
                return alpha_id, None, str(exc)

    fetched = await asyncio.gather(*(one(row) for row in ranked))
    series: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for alpha_id, values, error in fetched:
        if values is not None:
            series[alpha_id] = values
        elif error:
            errors[alpha_id] = error

    # 相关矩阵 (需要 pandas)
    import pandas as pd

    frame = pd.DataFrame(series)
    corr = frame.corr(min_periods=config.min_periods) if len(series) else pd.DataFrame()

    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for row in ranked:
        alpha_id = row["alpha_id"]
        if alpha_id not in series:
            if config.drop_if_pnl_missing:
                pruned.append({
                    **row,
                    "prune_reason": "pnl_unavailable",
                    "prune_detail": errors.get(alpha_id),
                })
            else:
                kept.append({
                    **row,
                    "prune_note": "pnl_unavailable",
                })
            continue
        conflicts = []
        for prior in kept:
            prior_id = prior["alpha_id"]
            if prior_id not in series:
                continue
            try:
                value = corr.loc[alpha_id, prior_id]
            except KeyError:
                value = float("nan")
            if pd.notna(value) and abs(float(value)) >= config.threshold:
                conflicts.append({"id": prior_id, "corr": round(float(value), 4)})
        if conflicts:
            pruned.append({
                **row,
                "prune_reason": "pairwise_corr",
                "prune_conflicts": conflicts,
            })
        else:
            kept.append(row)

    # 无 alpha_id 的行排回保留列表末尾
    kept.extend(without_id)
    return kept, pruned


__all__ = [
    # 工具
    "classify_field",
    "extract_field_ids",
    "extract_fields",
    # 1. 语义剪枝
    "SemanticPruneConfig",
    "semantic_prune_fields",
    # 2. 同字段 top-k
    "FieldTopKConfig",
    "field_topk_prune",
    # 3. 相关性剪枝
    "CorrelationPruneConfig",
    "correlation_prune",
    # 4. 本地 SC/PC 预检
    "LocalCheckConfig",
    "compute_self_correlation",
    "local_sc_precheck",
]
