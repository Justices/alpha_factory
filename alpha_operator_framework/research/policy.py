"""Versioned, serializable research-policy configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .round import ResearchPolicy
from .selection import DiversitySelector, ThompsonSelector, UcbSelector, WeightedStratifiedSelector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicySnapshot:
    """策略快照配置 (PolicySnapshot).

    负责定义完整的研究回测与审查策略。该类实例通常从 JSON 或 YAML 文件反序列化而来。
    """
    version: str
    region: str
    universe: str
    max_backtests: int
    selection_strategy: str = "weighted_stratified"
    weights: Mapping[str, float] = None  # type: ignore[assignment]
    templates: tuple[Any, ...] = ()
    prohibited_patterns: tuple[str, ...] = ()
    evaluation: Mapping[str, float] = None  # type: ignore[assignment]
    settings: Mapping[str, Any] = None  # type: ignore[assignment]
    template_promotion: Mapping[str, Any] = None  # type: ignore[assignment]
    retry: Mapping[str, Any] = None  # type: ignore[assignment]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PolicySnapshot":
        """从字典映射中构造并校验 PolicySnapshot。

        Args:
            data: 包含策略属性的配置字典。

        Returns:
            PolicySnapshot: 校验通过的策略快照实例。
        """
        logger.info("正在从数据字典中解析 PolicySnapshot 策略快照...")
        region, universe = str(data.get("region", "")), str(data.get("universe", ""))
        budget = int(data.get("max_backtests", 0))
        strategy = str(data.get("selection_strategy", "weighted_stratified"))
        if not region or not universe:
            logger.error("解析策略失败：缺少 region 或 universe 字段")
            raise ValueError("region and universe are required")
        if budget <= 0:
            logger.error("解析策略失败：max_backtests 必须为正整数 (当前为: %d)", budget)
            raise ValueError("max_backtests must be positive")
        if strategy not in {"weighted_stratified", "thompson", "ucb", "diversity"}:
            logger.error("解析策略失败：不支持的选择策略 selection_strategy=%s", strategy)
            raise ValueError("selection_strategy is invalid")
        weights = dict(data.get("weights", {}))
        evaluation = dict(data.get("evaluation", {}))
        pruning = dict(data.get("pruning", {}))
        settings = dict(data.get("settings", {}))
        promotion = dict(data.get("template_promotion", {}))
        retry_value = data.get("retry", {})
        if not isinstance(retry_value, Mapping):
            logger.error("解析策略失败：retry 参数结构错误")
            raise ValueError("retry is invalid")
        retry = dict(retry_value)
        if any(key not in {"field", "operator", "template", "novelty", "uncertainty"} or float(value) < 0 for key, value in weights.items()):
            logger.error("解析策略失败：weights 包含非法字段或负值权重: %s", weights)
            raise ValueError("weights are invalid")
        if any(key not in {"min_sharpe", "min_fitness", "min_margin", "max_turnover"} for key in evaluation):
            logger.error("解析策略失败：evaluation 包含非法字段")
            raise ValueError("evaluation is invalid")
        if float(evaluation.get("max_turnover", 0.70)) <= 0 or float(evaluation.get("max_turnover", 0.70)) > 1:
            logger.error("解析策略失败：max_turnover 范围溢出，应当在 (0, 1] 之间")
            raise ValueError("evaluation.max_turnover is invalid")
        if set(settings) - {"delay", "decay", "neutralization", "truncation"}:
            logger.error("解析策略失败：settings 包含未知参数")
            raise ValueError("settings are invalid")
        if int(settings.get("delay", 1)) < 0 or int(settings.get("decay", 8)) < 0:
            logger.error("解析策略失败：delay 或 decay 参数包含负值")
            raise ValueError("settings are invalid")
        if not 0 < float(settings.get("truncation", 0.08)) <= 1:
            logger.error("解析策略失败：truncation 范围溢出，应当在 (0, 1] 之间")
            raise ValueError("settings are invalid")
        if set(promotion) - {"min_support", "min_sharpe", "min_fitness", "max_correlation", "structural_max_correlation", "platform_max_correlation", "observation_window"}:
            logger.error("解析策略失败：template_promotion 包含未知参数")
            raise ValueError("template_promotion is invalid")
        if int(promotion.get("min_support", 1)) < 1 or int(promotion.get("observation_window", 1)) < 1:
            logger.error("解析策略失败：min_support 或 observation_window 参数小于 1")
            raise ValueError("template_promotion is invalid")
        if set(retry) - {"max_attempts", "backoff_seconds"}:
            logger.error("解析策略失败：retry 包含未知参数")
            raise ValueError("retry is invalid")
        max_attempts = retry.get("max_attempts", 3)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            logger.error("解析策略失败：max_attempts 必须为正整数")
            raise ValueError("retry.max_attempts is invalid")
        backoff = retry.get("backoff_seconds", (30.0, 60.0, 120.0))
        if (
            not isinstance(backoff, (list, tuple))
            or not backoff
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or float(value) <= 0
                for value in backoff
            )
        ):
            logger.error("解析策略失败：retry.backoff_seconds 配置不合法: %s", backoff)
            raise ValueError("retry.backoff_seconds is invalid")
        retry = {"max_attempts": max_attempts, "backoff_seconds": tuple(float(value) for value in backoff)}
        templates = tuple(data.get("templates", ()))
        if any(not item for item in templates):
            logger.error("解析策略失败：templates 配置错误")
            raise ValueError("templates are invalid")
        patterns = tuple(str(item) for item in pruning.get("prohibited_patterns", ()))
        
        version = str(data.get("version", "default"))
        logger.info("策略配置校验通过。版本: %s, 区域: %s, 股票池: %s, 预算上限: %d", version, region, universe, budget)
        return cls(version, region, universe, budget, strategy, weights, templates, patterns, evaluation, settings, promotion, retry)

    def construction_templates(self):
        """生成并返回经过包装的 ConstructionTemplate 实例列表。"""
        from .construction import ConstructionTemplate

        templates = []
        for item in self.templates:
            if not isinstance(item, Mapping):
                logger.error("模块模板不是合法的 Mapping: %s", item)
                raise ValueError("policy templates must be mappings with id, expression, family, and operators")
            required = {"id", "expression", "family", "operators"}
            if not required <= item.keys() or "{field}" not in str(item["expression"]):
                logger.error("模板内容缺少必填字段或包含错误表达式: %s", item)
                raise ValueError("policy template is invalid")
            templates.append(ConstructionTemplate(
                str(item["id"]), str(item["expression"]), str(item["family"]), tuple(str(value) for value in item["operators"]),
            ))
        return tuple(templates)

    def to_research_policy(self) -> ResearchPolicy:
        """将 PolicySnapshot 转换为底层的具体 ResearchPolicy 策略配置。"""
        weights = self.weights or {}
        evaluation = self.evaluation or {}
        settings = self.settings or {}
        promotion = self.template_promotion or {}
        retry = self.retry or {}
        return ResearchPolicy(self.region, self.universe, self.max_backtests,
            field_weight=float(weights.get("field", 1.0)), operator_weight=float(weights.get("operator", 1.0)),
            template_weight=float(weights.get("template", 1.0)), novelty_weight=float(weights.get("novelty", 1.0)),
            uncertainty_weight=float(weights.get("uncertainty", 1.0)), prohibited_patterns=self.prohibited_patterns,
            policy_version=self.version, selection_strategy=self.selection_strategy,
            min_sharpe=float(evaluation.get("min_sharpe", 1.0)), min_fitness=float(evaluation.get("min_fitness", 0.8)),
            min_margin=float(evaluation.get("min_margin", 4.0)), max_turnover=float(evaluation.get("max_turnover", 0.70)),
            delay=int(settings.get("delay", 1)), decay=int(settings.get("decay", 8)),
            neutralization=str(settings.get("neutralization", "SUBINDUSTRY")), truncation=float(settings.get("truncation", 0.08)),
            template_min_support=int(promotion.get("min_support", 1)), template_min_sharpe=float(promotion.get("min_sharpe", 1.0)),
            template_min_fitness=float(promotion.get("min_fitness", 0.8)), template_max_correlation=float(promotion.get("max_correlation", 0.70)),
            template_structural_max_correlation=float(promotion.get("structural_max_correlation", promotion.get("max_correlation", 0.70))),
            template_platform_max_correlation=float(promotion.get("platform_max_correlation", promotion.get("max_correlation", 0.70))),
            template_observation_window=int(promotion.get("observation_window", 1)),
            max_retry_attempts=int(retry.get("max_attempts", 3)),
            retry_backoff_seconds=tuple(float(value) for value in retry.get("backoff_seconds", (30.0, 60.0, 120.0))))


def build_selector(policy: ResearchPolicy):
    """根据 ResearchPolicy 中配置的选择算法名称，反射构建对应的选择器实例。"""
    selectors = {
        "weighted_stratified": WeightedStratifiedSelector,
        "stratified": WeightedStratifiedSelector,
        "thompson": ThompsonSelector,
        "ucb": UcbSelector,
        "diversity": DiversitySelector,
        "d_optimal": DiversitySelector,
    }
    logger.info("正在构建因子筛选选择器... 策略算法: %s", policy.selection_strategy)
    try:
        return selectors[policy.selection_strategy]()
    except KeyError as error:
        logger.error("构建选择器失败：未知选择算法 %s", policy.selection_strategy)
        raise ValueError(f"Unknown selection strategy: {policy.selection_strategy}") from error


def validate_cli_policy_overrides(policy: ResearchPolicy, overrides: Mapping[str, Any]) -> None:
    """校验命令行参数覆盖配置，若发现不一致则拒绝并抛出异常，防止无声静默忽略。"""
    logger.info("校验 CLI 覆盖参数，确保与已载入的策略配置不存在冲突...")
    aliases = {"algorithm": "selection_strategy"}
    for name, value in overrides.items():
        if value is None:
            continue
        attribute = aliases.get(name, name)
        if getattr(policy, attribute) != value:
            logger.error("覆盖冲突：CLI 提供的参数 %s=%s 与策略配置中的属性 %s=%s 不一致", name, value, attribute, getattr(policy, attribute))
            raise ValueError(f"CLI override conflicts with policy file: {name}")


def load_policy(path: Path) -> PolicySnapshot:
    """从指定的文件路径加载 JSON 或 YAML 格式的策略配置文件。"""
    logger.info("开始加载策略配置文件。路径: %s", path)
    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
                loader = getattr(yaml, "safe_load", None)
            except ImportError:
                loader = None
            if loader is not None:
                data = loader(content)
            else:
                logger.info("检测到 YAML 格式但未导入 PyYAML，自动回退到极简冒号解析行读取...")
                data = {
                    key.strip(): int(value.strip()) if value.strip().isdigit() else value.strip()
                    for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")
                    for key, value in [line.split(":", 1)]
                }
        else:
            data = json.loads(content)
        if not isinstance(data, Mapping):
            raise ValueError("Policy file must contain a mapping")
        snapshot = PolicySnapshot.from_mapping(data)
        logger.info("成功从路径 %s 加载并实例化策略快照", path)
        return snapshot
    except Exception as e:
        logger.exception("加载策略文件时抛出异常: %s", e)
        raise
