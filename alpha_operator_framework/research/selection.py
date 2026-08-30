"""Pure first-round selection policies."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Sequence

from .round import Candidate, KnowledgeSnapshot, ResearchPolicy, SelectionDecision

logger = logging.getLogger(__name__)


class WeightedStratifiedSelector:
    """基于加权证据评分、在结构配额约束下选出最优候选因子的选择器。

    算法分三阶段执行：
    1. **过滤**：利用 KnowledgeSnapshot 剔除已被历史知识否决的候选。
    2. **族内排名**：按加权综合评分（field / operator / template / novelty / uncertainty
       五个维度）降序排列各族成员，取前 ``quota`` 个进入初选池。
    3. **全局裁剪**：仅未设置分族配额时，按 ``policy.max_backtests`` 截断初选池。

    Attributes:
        name: 策略标识符，用于在工厂函数中按名称查找该选择器。
    """

    name = "weighted_stratified"

    def select(
        self,
        candidates: Sequence[Candidate],
        policy: ResearchPolicy,
        knowledge: KnowledgeSnapshot,
        random_source: Any,
    ) -> list[SelectionDecision]:
        """对候选因子执行加权分层选择，返回每个候选的决策结果。

        Args:
            candidates: 本轮待评估的全部候选因子序列。
            policy: 当前研究策略配置，包含权重、配额、预算等参数。
            knowledge: 当前知识快照，用于计算各维度评分及判断是否应拒绝候选。
            random_source: 随机源（接口预留，本实现为确定性算法，不实际使用）。

        Returns:
            与 ``candidates`` 等长的 :class:`SelectionDecision` 列表，每条记录包含
            是否被选中、评分分量、拒绝/选中原因，以及所用策略名称。
        """
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        rejected_ids: set[str] = set()
        # 第一阶段：按知识剪枝规则过滤，并将通过的候选按族分组
        for candidate in candidates:
            if knowledge.rejects(candidate):
                rejected_ids.add(candidate.candidate_id)
            else:
                grouped[candidate.family].append(candidate)

        logger.info(
            "候选过滤完成：总候选=%d，被知识规则拒绝=%d，有效族数=%d",
            len(candidates), len(rejected_ids), len(grouped),
        )

        selected_ids: set[str] = set()
        # 均分回测预算到各族；至少保证每族 1 个配额，避免小族全部丢失
        per_family = max(1, policy.max_backtests // max(1, len(grouped)))
        for family, members in grouped.items():
            # 优先使用策略中显式配置的族配额，否则退回到均分值
            quota = policy.family_quotas.get(family, per_family)
            # 按综合评分降序排列族内成员，候选 ID 作为同分时的稳定决胜字段
            ranked = sorted(members, key=lambda candidate: (-self.score(candidate, policy, knowledge), candidate.candidate_id))
            selected_ids.update(candidate.candidate_id for candidate in ranked[:quota])
            logger.info(
                "族 '%s'：成员=%d，配额=%d，进入初选池=%d",
                family, len(members), quota, min(quota, len(members)),
            )

        # 显式分族配额是最终预算；仅旧式全局预算才进行二次裁剪。
        if not policy.family_quotas and len(selected_ids) > policy.max_backtests:
            logger.info(
                "初选池 %d 超过 max_backtests=%d，执行全局裁剪",
                len(selected_ids), policy.max_backtests,
            )
            ranked_all = sorted(
                (candidate for candidate in candidates if candidate.candidate_id in selected_ids),
                key=lambda candidate: (-self.score(candidate, policy, knowledge), candidate.candidate_id),
            )
            selected_ids = {candidate.candidate_id for candidate in ranked_all[:policy.max_backtests]}

        logger.info(
            "选择完成：最终入选=%d，被拒绝=%d，未入选=%d（策略=%s，预算=%d）",
            len(selected_ids),
            len(rejected_ids),
            len(candidates) - len(selected_ids) - len(rejected_ids),
            self.name,
            policy.max_backtests,
        )

        return [
            SelectionDecision(
                candidate_id=candidate.candidate_id,
                selected=candidate.candidate_id in selected_ids,
                score_components=self.components(candidate, policy, knowledge),
                reason=(
                    "Rejected by knowledge pruning rule" if candidate.candidate_id in rejected_ids
                    else "Highest weighted score within family quota" if candidate.candidate_id in selected_ids
                    else "Below weighted family quota"
                ),
                policy_name=self.name,
            )
            for candidate in candidates
        ]

    @staticmethod
    def components(candidate: Candidate, policy: ResearchPolicy, knowledge: KnowledgeSnapshot) -> dict[str, float]:
        """计算候选因子得分的各分量值。"""
        return {
            "field": policy.field_weight * knowledge.field_score(candidate),
            "operator": policy.operator_weight * knowledge.operator_score(candidate),
            "template": policy.template_weight * knowledge.template_score(candidate),
            "novelty": policy.novelty_weight * candidate.novelty_score,
            "uncertainty": policy.uncertainty_weight * knowledge.uncertainty(candidate),
        }

    @classmethod
    def score(cls, candidate: Candidate, policy: ResearchPolicy, knowledge: KnowledgeSnapshot) -> float:
        """根据加权分量计算候选因子的综合评分。"""
        return sum(cls.components(candidate, policy, knowledge).values())


class UcbSelector(WeightedStratifiedSelector):
    """基于置信区间上界 (UCB) 的选择器。

    在加权分量评分基础上，通过增大不确定性部分的权重，鼓励对低回测频率因子的探索。
    """

    name = "ucb"

    @classmethod
    def score(cls, candidate: Candidate, policy: ResearchPolicy, knowledge: KnowledgeSnapshot) -> float:
        """在原有分数上增加 2.0 倍的不确定性溢价以实施探索性打分。"""
        components = cls.components(candidate, policy, knowledge)
        return sum(components.values()) + 2.0 * knowledge.uncertainty(candidate)


class ThompsonSelector(UcbSelector):
    """基于 Thompson 抽样的选择器变体。

    目前作为 UCB 选择器的确定性后验均值近似，边界处保留随机性注入逻辑。
    """

    name = "thompson"


class DiversitySelector(UcbSelector):
    """Greedy structural-diversity selector for candidates not yet backtested.

    PnL correlation is unavailable at this point, so this selector diversifies
    fields, operators and template identities. Result-level PnL diversity is a
    separate promotion gate in the research loop.
    """

    name = "diversity"

    def select(
        self,
        candidates: Sequence[Candidate],
        policy: ResearchPolicy,
        knowledge: KnowledgeSnapshot,
        random_source: Any,
    ) -> list[SelectionDecision]:
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        rejected_ids: set[str] = set()
        for candidate in candidates:
            if knowledge.rejects(candidate):
                rejected_ids.add(candidate.candidate_id)
            else:
                grouped[candidate.family].append(candidate)

        selected: list[Candidate] = []
        per_family = max(1, policy.max_backtests // max(1, len(grouped)))
        for family, members in sorted(grouped.items()):
            quota = policy.family_quotas.get(family, per_family)
            pool = list(members)
            family_selected: list[Candidate] = []
            while pool and len(family_selected) < quota:
                if not family_selected:
                    pick = max(pool, key=lambda item: (self.score(item, policy, knowledge), item.candidate_id))
                else:
                    pick = max(
                        pool,
                        key=lambda item: (
                            min(self._structural_distance(item, prior) for prior in family_selected),
                            self.score(item, policy, knowledge),
                            item.candidate_id,
                        ),
                    )
                family_selected.append(pick)
                pool.remove(pick)
            selected.extend(family_selected)

        if not policy.family_quotas and len(selected) > policy.max_backtests:
            chosen: list[Candidate] = []
            pool = list(selected)
            while pool and len(chosen) < policy.max_backtests:
                pick = max(
                    pool,
                    key=lambda item: (
                        min((self._structural_distance(item, prior) for prior in chosen), default=1.0),
                        self.score(item, policy, knowledge),
                        item.candidate_id,
                    ),
                )
                chosen.append(pick)
                pool.remove(pick)
            selected = chosen

        selected_ids = {candidate.candidate_id for candidate in selected}
        return [
            SelectionDecision(
                candidate_id=candidate.candidate_id,
                selected=candidate.candidate_id in selected_ids,
                score_components=self.components(candidate, policy, knowledge),
                reason=(
                    "Rejected by knowledge pruning rule" if candidate.candidate_id in rejected_ids
                    else "Selected by structural diversity within family quota"
                    if candidate.candidate_id in selected_ids
                    else "Below structural-diversity family quota"
                ),
                policy_name=self.name,
            )
            for candidate in candidates
        ]

    @staticmethod
    def _structural_distance(left: Candidate, right: Candidate) -> float:
        left_tokens = (
            {f"field:{value}" for value in left.fields}
            | {f"operator:{value}" for value in left.operators}
            | {f"template:{left.template_id}"}
        )
        right_tokens = (
            {f"field:{value}" for value in right.fields}
            | {f"operator:{value}" for value in right.operators}
            | {f"template:{right.template_id}"}
        )
        union = left_tokens | right_tokens
        return 1.0 if not union else 1.0 - len(left_tokens & right_tokens) / len(union)
