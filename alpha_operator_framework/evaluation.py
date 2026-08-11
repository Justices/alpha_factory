"""Alpha 评价模块 — 整合 WebDataScope 数据质量预筛与 Failed Gate 计数.

来源:
  - wqb-share-03/.claude/skills/brain-alpha-orchestrator/references/webdatascope-failed-gates.md
  - wqb-share-03/.claude/skills/brain-alpha-research/references/webdatascope-data-quality.md
  - wqb-share-03/tools/webdata_quality.py

核心功能:
  1. Failed RA/PPA 计数: 从 is.checks 数组计算失败检查项数量
  2. 数据集质量预筛: 基于 WebDataScope 数据包的社区先验
  3. Alpha 评级: 按指标和检查结果分级
"""

from __future__ import annotations

import json
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量 — 来自 WebDataScope failed-gates.md
# ---------------------------------------------------------------------------

PASS_STATES = {"PASS", "PENDING"}

# Failed RA 清单 (17 项)
RA_CHECK_NAMES = {
    "HIGH_TURNOVER",
    "LOW_TURNOVER",
    "LOW_FITNESS",
    "LOW_RETURNS",
    "LOW_SHARPE",
    "LOW_GLB_AMER_SHARPE",
    "LOW_GLB_APAC_SHARPE",
    "LOW_GLB_EMEA_SHARPE",
    "LOW_ASI_JPN_SHARPE",
    "IS_LADDER_SHARPE",
    "LOW_2Y_SHARPE",
    "LOW_SUB_UNIVERSE_SHARPE",
    "LOW_ROBUST_UNIVERSE_SHARPE",
    "LOW_AFTER_COST_ILLIQUID_UNIVERSE_SHARPE",
    "LOW_INVESTABILITY_CONSTRAINED_SHARPE",
    "LOW_ROBUST_UNIVERSE_RETURNS",
    "CONCENTRATED_WEIGHT",
}

# Failed PPA 清单 (7 项)
PPA_CHECK_NAMES = {
    "LOW_TURNOVER",
    "HIGH_TURNOVER",
    "LOW_SUB_UNIVERSE_SHARPE",
    "LOW_ROBUST_UNIVERSE_SHARPE",
    "LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO",
    "LOW_ROBUST_UNIVERSE_RETURNS",
    "LOW_INVESTABILITY_CONSTRAINED_SHARPE",
}


# ---------------------------------------------------------------------------
# WebDataScope 数据包解析
# ---------------------------------------------------------------------------

def _load_bin(zf: zipfile.ZipFile, name: str) -> Any:
    """解压并反序列化 .bin 文件."""
    try:
        import msgpack
        return msgpack.unpackb(zlib.decompress(zf.read(name)), strict_map_key=False)
    except ImportError:
        raise ImportError("需要安装 msgpack: pip install msgpack")


def extract_datapack_stats(
    zip_path: str,
    region: str,
    delay: int,
) -> Dict[str, Any]:
    """
    从 WebDataScope 数据包提取数据集/字段质量统计.

    Args:
        zip_path: 数据包路径
        region: 区域 (USA/EUR/CHN/...)
        delay: 延迟 (0/1)

    Returns:
        dict 含:
          - datasets: 数据集排名列表
          - sweet_spot: 甜点区数据集
          - fields: 字段排名列表
          - mean_sharpe: 区域平均 sharpe
          - total_count: 总提交数
    """
    key = f"{region}_{delay}"
    with zipfile.ZipFile(zip_path) as zf:
        info = _load_bin(zf, 'data/oth/info_data.bin')

    if key not in info:
        available = sorted(info.keys())
        raise ValueError(f"{key} 不在数据包中, 可用: {available}")

    isos = info[key]['isos']
    neut = info[key]['neutralization']
    mean_sharpe = isos['mean']['sharpe_ratio']

    def best_neuts(nstats: Dict, min_n: int) -> List:
        rows = [
            (k, v['sharpe_ratio'], v['count'])
            for k, v in nstats.items()
            if v.get('count', 0) >= min_n
        ]
        return sorted(rows, key=lambda x: -x[1])[:3]

    # 数据集统计
    ds_rows = []
    for ds, s in isos['dataset'].items():
        bn = best_neuts(neut['dataset'].get(ds, {}), 20)
        ds_rows.append({
            'dataset': ds,
            'count': s.get('count', 0),
            'sharpe': round(s.get('sharpe_ratio', 0), 3),
            'fitness': round(s.get('fitness_ratio', 0), 3),
            'best_neuts': [
                {'neut': n, 'sharpe': round(sh, 3), 'count': c}
                for n, sh, c in bn
            ]
        })
    ds_rows.sort(key=lambda r: -r['count'])

    # 甜点区
    sweet = sorted(
        [
            r for r in ds_rows
            if 100 <= r['count'] <= 3000 and r['sharpe'] >= mean_sharpe * 1.1
        ],
        key=lambda r: -r['sharpe']
    )

    # 字段统计
    f_rows = []
    for f, s in isos['datafield'].items():
        bn = best_neuts(neut['datafield'].get(f, {}), 5)
        f_rows.append({
            'field': f,
            'count': s.get('count', 0),
            'sharpe': round(s.get('sharpe_ratio', 0), 3),
            'fitness': round(s.get('fitness_ratio', 0), 3),
            'best_neuts': [
                {'neut': n, 'sharpe': round(sh, 3), 'count': c}
                for n, sh, c in bn
            ]
        })
    f_rows.sort(key=lambda r: -r['count'])

    return {
        'region_delay': key,
        'mean_sharpe': mean_sharpe,
        'total_count': isos['total_count'],
        'window': f"{info[key]['sub_beg_time']} → {info[key]['sub_end_time']}",
        'datasets': ds_rows,
        'sweet_spot': sweet,
        'fields': f_rows,
    }


def filter_datasets_by_datapack(
    datapack_stats: Dict[str, Any],
    mode: str = "sweet_spot",
    top_n: int = 10,
) -> List[str]:
    """
    基于数据包统计筛选数据集.

    Args:
        datapack_stats: extract_datapack_stats 返回的统计
        mode: 筛选模式
          - "sweet_spot": 只返回甜点区 (100-3000提交, sharpe>=1.1x均值)
          - "top_n": 返回提交数最多的 N 个
          - "all": 返回全部
        top_n: mode="top_n" 时返回的数量

    Returns:
        数据集 ID 列表
    """
    if mode == "sweet_spot":
        return [r['dataset'] for r in datapack_stats['sweet_spot'][:top_n]]
    elif mode == "top_n":
        return [r['dataset'] for r in datapack_stats['datasets'][:top_n]]
    else:
        return [r['dataset'] for r in datapack_stats['datasets']]


def filter_fields_by_datapack(
    datapack_stats: Dict[str, Any],
    min_count: int = 10,
    min_sharpe: Optional[float] = None,
    top_n: int = 100,
) -> List[str]:
    """
    基于数据包统计筛选字段.

    Args:
        datapack_stats: extract_datapack_stats 返回的统计
        min_count: 最小提交数
        min_sharpe: 最小 sharpe (None 则使用区域均值)
        top_n: 返回数量

    Returns:
        字段 ID 列表
    """
    threshold = min_sharpe or datapack_stats['mean_sharpe']
    filtered = [
        r for r in datapack_stats['fields']
        if r['count'] >= min_count and r['sharpe'] >= threshold
    ]
    return [r['field'] for r in filtered[:top_n]]


# ---------------------------------------------------------------------------
# Failed Gate 计数
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FailedGateResult:
    """Failed Gate 计数结果."""

    failed_ra: int = 0
    failed_ppa: int = 0
    failed_ra_items: Tuple[Dict[str, Any], ...] = ()
    failed_ppa_items: Tuple[Dict[str, Any], ...] = ()
    qualifies_regular: bool = False
    qualifies_ppa: bool = False


def count_failed_gates(checks: List[Dict[str, Any]]) -> FailedGateResult:
    """
    计算Failed RA/PPA 计数.

    移植自 WebDataScope `background.js::getAlphaCheckStates`.

    Args:
        checks: is.checks 数组

    Returns:
        FailedGateResult 含计数和详细项

    规则:
      - REGULAR alpha 候选: Failed RA == 0 才合格
      - PPA 候选: Failed PPA == 0 才合格
      - 计数比只看 result=="FAIL" 严格: WARNING/ERROR 等状态一样计数
      - PPA 的 LOW_SHARPE 当 value < 1 时也计入失败
    """
    if not checks:
        return FailedGateResult(qualifies_regular=True, qualifies_ppa=True)

    failed_ra_items = []
    failed_ppa_items = []

    for check in checks:
        if not isinstance(check, dict):
            continue
        name = check.get("name", "")
        result = check.get("result", "")
        value = check.get("value")

        # 跳过 PASS 和 PENDING
        if result in PASS_STATES:
            continue

        # Failed RA 计数
        if name in RA_CHECK_NAMES:
            failed_ra_items.append({
                "name": name,
                "result": result,
                "value": value,
                "limit": check.get("limit"),
            })

        # Failed PPA 计数
        if name in PPA_CHECK_NAMES:
            failed_ppa_items.append({
                "name": name,
                "result": result,
                "value": value,
                "limit": check.get("limit"),
            })

        # PPA 特殊规则: LOW_SHARPE 当 value < 1 也计入
        if name == "LOW_SHARPE":
            try:
                if value is not None and float(value) < 1:
                    # 避免重复添加
                    if not any(i["name"] == "LOW_SHARPE" for i in failed_ppa_items):
                        failed_ppa_items.append({
                            "name": name,
                            "result": result,
                            "value": value,
                            "limit": check.get("limit"),
                            "reason": "value < 1",
                        })
            except (TypeError, ValueError):
                pass

    return FailedGateResult(
        failed_ra=len(failed_ra_items),
        failed_ppa=len(failed_ppa_items),
        failed_ra_items=tuple(failed_ra_items),
        failed_ppa_items=tuple(failed_ppa_items),
        qualifies_regular=len(failed_ra_items) == 0,
        qualifies_ppa=len(failed_ppa_items) == 0,
    )


# ---------------------------------------------------------------------------
# 数据集质量预筛 — 来自 WebDataScope 数据包
# ---------------------------------------------------------------------------

@dataclass
class DatasetQuality:
    """数据集质量评级."""

    dataset_id: str
    alpha_count: int = 0
    avg_sharpe: float = 0.0
    avg_fitness: float = 0.0
    region_mean_sharpe: float = 0.358  # USA_1 默认值

    @property
    def grade(self) -> str:
        """
        数据集评级.

        规则:
          - count < 50: "unverified" (社区未验证, 风险高)
          - count 100-3000 且 sharpe >= 1.1×区域均值: "sweet_spot" (甜点区)
          - count > 30000: "saturated" (饱和, 需非对称结构)
          - sharpe 明显低于区域均值: "low_quality" (社区踩坑)
          - 其他: "normal"
        """
        if self.alpha_count < 50:
            return "unverified"
        if 100 <= self.alpha_count <= 3000 and self.avg_sharpe >= self.region_mean_sharpe * 1.1:
            return "sweet_spot"
        if self.alpha_count > 30000:
            return "saturated"
        if self.avg_sharpe < self.region_mean_sharpe * 0.8:
            return "low_quality"
        return "normal"

    @property
    def recommendation(self) -> str:
        """数据集推荐动作."""
        grade = self.grade
        if grade == "sweet_spot":
            return "优先入围 (ProdCorr 死区风险低)"
        elif grade == "unverified":
            return "默认跳过; 仅作刻意去相关探索"
        elif grade == "saturated":
            return "冷启动避开; 需高度非对称结构"
        elif grade == "low_quality":
            return "跳过 (社区大量尝试仍失败)"
        else:
            return "正常探索"


def evaluate_dataset_quality(
    dataset_id: str,
    alpha_count: int,
    avg_sharpe: float,
    avg_fitness: float = 0.0,
    region_mean_sharpe: float = 0.358,
) -> DatasetQuality:
    """
    评估数据集质量.

    Args:
        dataset_id: 数据集 ID
        alpha_count: 社区提交 alpha 数量
        avg_sharpe: 平均 sharpe
        avg_fitness: 平均 fitness
        region_mean_sharpe: 区域平均 sharpe (USA_1 默认 0.358)

    Returns:
        DatasetQuality 含评级和推荐
    """
    return DatasetQuality(
        dataset_id=dataset_id,
        alpha_count=alpha_count,
        avg_sharpe=avg_sharpe,
        avg_fitness=avg_fitness,
        region_mean_sharpe=region_mean_sharpe,
    )


# ---------------------------------------------------------------------------
# Alpha 综合评价
# ---------------------------------------------------------------------------

@dataclass
class AlphaEvaluation:
    """Alpha 综合评价结果."""

    alpha_id: str
    expression: str = ""

    # 性能指标
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0

    # Failed Gate 计数
    failed_ra: int = 0
    failed_ppa: int = 0
    qualifies_regular: bool = False

    # 相关性
    sc_value: Optional[float] = None
    pc_value: Optional[float] = None

    # 评级
    grade: str = "unknown"  # submission_ready / needs_optimization / failed
    grade_reason: str = ""

    # 优化建议
    optimization_hints: List[str] = ()

    @property
    def can_submit(self) -> bool:
        """是否可以提交."""
        return self.grade == "submission_ready"


def evaluate_alpha(
    alpha_id: str,
    is_result: Dict[str, Any],
    expression: str = "",
    thresholds: Optional[Dict[str, float]] = None,
) -> AlphaEvaluation:
    """
    综合评价单个 alpha.

    Args:
        alpha_id: 平台 alpha ID
        is_result: is 块或完整结果行
        expression: 表达式
        thresholds: 阈值字典 (可选)

    Returns:
        AlphaEvaluation 含评级和建议

    阈值默认值:
        sharpe_min: 1.58
        fitness_min: 1.0
        turnover_min: 0.05
        turnover_max: 0.30
        margin_min: 0.0005 (5bp)
        sc_threshold: 0.7
        pc_threshold: 0.7
    """
    # 默认阈值
    th = {
        "sharpe_min": 1.58,
        "fitness_min": 1.0,
        "turnover_min": 0.05,
        "turnover_max": 0.30,
        "margin_min": 0.0005,
        "sc_threshold": 0.7,
        "pc_threshold": 0.7,
    }
    if thresholds:
        th.update(thresholds)

    # 提取 is 块
    is_block = is_result
    if isinstance(is_result, dict) and isinstance(is_result.get("is"), dict):
        is_block = is_result["is"]

    # 提取指标
    def _num(d, k):
        v = d.get(k) if isinstance(d, dict) else None
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    sharpe = _num(is_block, "sharpe")
    fitness = _num(is_block, "fitness")
    turnover = _num(is_block, "turnover")
    margin = _num(is_block, "margin")
    sc_value = _num(is_block, "selfCorrelation") if is_block.get("selfCorrelation") else None
    pc_value = _num(is_block, "prodCorrelation") if is_block.get("prodCorrelation") else None

    # Failed Gate 计数
    checks = is_block.get("checks") or []
    gate_result = count_failed_gates(checks)

    # 评级逻辑
    grade = "unknown"
    grade_reason = ""
    optimization_hints = []

    # 1. Failed RA 检查 (硬门槛)
    if gate_result.failed_ra > 0:
        grade = "failed"
        grade_reason = f"Failed RA = {gate_result.failed_ra} (需要 = 0)"
        for item in gate_result.failed_ra_items[:5]:  # 只取前5个
            optimization_hints.append(
                f"修复 {item['name']}: value={item.get('value'):.4f}, limit={item.get('limit')}"
            )
    # 2. 指标门槛
    elif sharpe < th["sharpe_min"]:
        grade = "needs_optimization"
        grade_reason = f"sharpe {sharpe:.2f} < {th['sharpe_min']}"
        optimization_hints.append("提高 sharpe: 尝试不同的中性化/窗口/decay")
    elif fitness < th["fitness_min"]:
        grade = "needs_optimization"
        grade_reason = f"fitness {fitness:.2f} < {th['fitness_min']}"
        optimization_hints.append("提高 fitness: 降低换手或增加 decay")
    elif turnover < th["turnover_min"] or turnover > th["turnover_max"]:
        grade = "needs_optimization"
        grade_reason = f"turnover {turnover:.2%} 不在 [{th['turnover_min']:.0%}, {th['turnover_max']:.0%}]"
        optimization_hints.append("调整 turnover: 改变 decay/窗口")
    elif margin < th["margin_min"]:
        grade = "needs_optimization"
        grade_reason = f"margin {margin*10000:.1f}bp < {th['margin_min']*10000:.0f}bp"
        optimization_hints.append("提高 margin: 选择更强信号字段")
    # 3. 相关性门槛
    elif sc_value is not None and sc_value >= th["sc_threshold"]:
        grade = "needs_optimization"
        grade_reason = f"SC {sc_value:.3f} >= {th['sc_threshold']}"
        optimization_hints.append("降低 SC: 修改表达式结构或换字段")
    elif pc_value is not None and pc_value >= th["pc_threshold"]:
        grade = "needs_optimization"
        grade_reason = f"PC {pc_value:.3f} >= {th['pc_threshold']}"
        optimization_hints.append("降低 PC: 使用 signed_power/换骨架/换数据集")
    # 4. 通过所有门槛
    else:
        grade = "submission_ready"
        grade_reason = "通过所有门槛"

    return AlphaEvaluation(
        alpha_id=alpha_id,
        expression=expression,
        sharpe=sharpe,
        fitness=fitness,
        turnover=turnover,
        margin=margin,
        failed_ra=gate_result.failed_ra,
        failed_ppa=gate_result.failed_ppa,
        qualifies_regular=gate_result.qualifies_regular,
        sc_value=sc_value,
        pc_value=pc_value,
        grade=grade,
        grade_reason=grade_reason,
        optimization_hints=list(optimization_hints),
    )


__all__ = [
    # 常量
    "RA_CHECK_NAMES",
    "PPA_CHECK_NAMES",
    "PASS_STATES",
    # Failed Gate 计数
    "FailedGateResult",
    "count_failed_gates",
    # 数据集质量
    "DatasetQuality",
    "evaluate_dataset_quality",
    # Alpha 评价
    "AlphaEvaluation",
    "evaluate_alpha",
    # 数据包解析
    "extract_datapack_stats",
    "filter_datasets_by_datapack",
    "filter_fields_by_datapack",
]