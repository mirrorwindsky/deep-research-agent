"""
补搜 query 生成服务。

模块职责：
1. 根据 judge 阶段识别出的 evidence_gaps 生成一轮补搜 query。
2. 将不同证据缺口映射到更有针对性的检索意图。
3. 让 rewrite_query_node 保持薄编排职责。

设计目标：
1. 避免在节点层继续累积补搜模板策略。
2. 保持规则简单、可解释、可单元测试。
3. 为后续引入更智能的 query rewrite 或 gap-specific planner 保留边界。
"""

from typing import List


def _deduplicate_strings(items: List[str]) -> List[str]:
    """
    对字符串列表做保序去重。
    """
    seen = set()
    result: List[str] = []

    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def build_rewritten_queries(
    *,
    question: str,
    original_queries: List[str],
    evidence_gaps: List[str],
    max_queries: int,
) -> List[str]:
    """
    根据 evidence gaps 生成补搜 query。

    输入：
    - question: 原始研究问题。
    - original_queries: planner 生成的原始 query 列表。
    - evidence_gaps: judge 阶段识别出的证据缺口。
    - max_queries: 最多返回的补搜 query 数量。

    输出：
    - 去重、截断后的补搜 query 列表。
    """
    base_queries = original_queries or [question]
    primary_query = base_queries[0] if base_queries else question

    rewritten_queries: List[str] = []

    if "implementation_detail_missing" in evidence_gaps:
        rewritten_queries.append(
            f"{primary_query} implementation guide tutorial example code official docs"
        )
        rewritten_queries.append(
            f"{primary_query} controller CRD configuration example"
        )

    if "comparison_missing" in evidence_gaps:
        rewritten_queries.append(
            f"{primary_query} comparison vs difference tradeoff"
        )
        rewritten_queries.append(
            f"{primary_query} alternatives comparison official docs"
        )

    if "official_source_missing" in evidence_gaps:
        rewritten_queries.append(f"{primary_query} official documentation reference")

    if "example_source_missing" in evidence_gaps:
        rewritten_queries.append(f"{primary_query} GitHub example tutorial")

    if "insufficient_evidence" in evidence_gaps:
        rewritten_queries.append(f"{primary_query} docs guide implementation")

    if "source_diversity_low" in evidence_gaps:
        rewritten_queries.append(f"{primary_query} comparison examples best practices")

    if "fallback_evidence_too_many" in evidence_gaps:
        rewritten_queries.append(f"{primary_query} official docs guide reference")

    if not rewritten_queries:
        rewritten_queries = [
            f"{query} official documentation"
            for query in base_queries[:2]
        ]

    return _deduplicate_strings(rewritten_queries)[:max_queries]
