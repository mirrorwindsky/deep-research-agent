"""
证据质量判断模块。

模块职责：
1. 基于 evidence_cards 判断当前证据是否足够进入综合阶段
2. 识别证据缺口 evidence_gaps，供 rewrite_query_node 生成补搜 query
3. 保持 judge_search_quality_node 的节点职责简洁

设计目标：
1. 将证据质量判断规则从 workflow 节点层拆出
2. 保持第一版规则轻量、可解释、易调试
3. 为后续扩展子问题覆盖判断、来源多样性评分、置信度聚合保留边界
"""

from typing import Any, Dict, List

from services.search_ranker import extract_domain


FALLBACK_EVIDENCE_RATIO_THRESHOLD = 0.5


def _collect_evidence_domains(evidence_cards: List[Dict[str, Any]]) -> List[str]:
    """
    从 evidence cards 中收集来源域名。

    设计原因：
    - judge 阶段需要判断证据是否过度集中在单一来源
    - evidence card 可能只包含 source_url，因此需要提供 URL 兜底解析
    """
    domains: List[str] = []

    for card in evidence_cards:
        domain = card.get("domain", "").strip()
        if not domain:
            domain = extract_domain(card.get("source_url", ""))

        if domain:
            domains.append(domain)

    return domains


def judge_evidence_quality(
    evidence_cards: List[Dict[str, Any]],
    retry_count: int,
) -> Dict[str, Any]:
    """
    判断当前 evidence cards 是否足够进入综合阶段。

    输入：
    - evidence_cards: build_evidence_cards_node 生成的结构化证据
    - retry_count: 当前补搜轮次

    输出：
    - needs_retry: 是否需要进入补搜分支
    - evidence_gaps: 当前识别出的证据缺口
    - metrics: 便于日志观察的统计指标

    当前规则：
    1. evidence_cards 数量过少时标记 insufficient_evidence
    2. 缺少官方来源时标记 official_source_missing
    3. 证据过度集中于单一 domain 时标记 source_diversity_low
    4. 缺少 example/readme/tutorial/API 这类实现证据时标记 example_source_missing
    5. 若已经补搜过一次，则不再触发补搜
    """
    official_source_types = {
        "official_docs",
        "official_repo",
        "official_blog",
    }
    implementation_page_kinds = {
        "example_page",
        "readme",
        "tutorial_page",
        "api_reference",
    }

    official_count = sum(
        1
        for card in evidence_cards
        if card.get("source_type", "") in official_source_types
    )
    implementation_count = sum(
        1
        for card in evidence_cards
        if card.get("page_kind", "") in implementation_page_kinds
    )
    fallback_count = sum(
        1
        for card in evidence_cards
        if card.get("evidence_source", "") == "snippet_fallback"
    )
    fallback_ratio = (
        fallback_count / len(evidence_cards)
        if evidence_cards
        else 0
    )
    domains = _collect_evidence_domains(evidence_cards)
    unique_domains = set(domains)

    evidence_gaps: List[str] = []

    if len(evidence_cards) < 3:
        evidence_gaps.append("insufficient_evidence")

    if official_count < 1:
        evidence_gaps.append("official_source_missing")

    if len(evidence_cards) >= 3 and len(unique_domains) <= 1:
        evidence_gaps.append("source_diversity_low")

    if implementation_count < 1:
        evidence_gaps.append("example_source_missing")

    if (
        len(evidence_cards) >= 3
        and fallback_ratio >= FALLBACK_EVIDENCE_RATIO_THRESHOLD
    ):
        evidence_gaps.append("fallback_evidence_too_many")

    needs_retry = bool(evidence_gaps) and retry_count < 1

    return {
        "needs_retry": needs_retry,
        "evidence_gaps": evidence_gaps,
        "metrics": {
            "evidence_count": len(evidence_cards),
            "official_count": official_count,
            "domain_count": len(unique_domains),
            "implementation_count": implementation_count,
            "fallback_count": fallback_count,
            "fallback_ratio": fallback_ratio,
            "retry_count": retry_count,
        },
    }
