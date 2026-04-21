"""
结构化证据综合模块。

模块职责：
1. 将 evidence_cards 聚合为适合 LLM 综合的材料
2. 构建 synthesize_evidence_node 使用的 prompt
3. 在模型输出不可用时，从 evidence claims 生成兜底 notes

设计目标：
1. 将 evidence 综合策略从 workflow 节点层拆出
2. 使 synthesize_evidence_node 保持“读 state -> 调 service/LLM -> 写 state”的结构
3. 为后续扩展按子问题聚合、来源权重、证据缺口提示保留独立边界
"""

from collections import OrderedDict
from typing import Any, Dict, List


def group_evidence_by_sub_question(
    evidence_cards: List[Dict[str, Any]],
) -> "OrderedDict[str, List[Dict[str, Any]]]":
    """
    按 sub_question 对 evidence cards 做保序分组。

    设计原因：
    - research workflow 的 evidence 通常来自多个 query / 子问题
    - 按子问题组织材料，可以让综合阶段更容易保留问题结构
    """
    grouped: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()

    for card in evidence_cards:
        sub_question = card.get("sub_question", "").strip() or "未标注子问题"
        grouped.setdefault(sub_question, []).append(card)

    return grouped


def format_grouped_evidence_for_prompt(
    evidence_cards: List[Dict[str, Any]],
) -> str:
    """
    将 evidence cards 按子问题格式化为综合阶段材料。
    """
    if not evidence_cards:
        return "（暂无结构化证据）"

    grouped = group_evidence_by_sub_question(evidence_cards)
    sections: List[str] = []

    for sub_question, cards in grouped.items():
        lines = [f"子问题：{sub_question}"]

        for idx, card in enumerate(cards, start=1):
            lines.append(
                "\n".join([
                    f"{idx}. 结论：{card.get('claim', '')}",
                    f"   证据：{card.get('evidence', '')}",
                    f"   来源：{card.get('source_title', '')}",
                    f"   链接：{card.get('source_url', '')}",
                    (
                        f"   来源类型：{card.get('source_type', '')} | "
                        f"页面类型：{card.get('page_kind', '')} | "
                        f"evidence_source：{card.get('evidence_source', '')} | "
                        f"域名：{card.get('domain', '')}"
                    ),
                ])
            )

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def build_evidence_synthesis_prompt(
    question: str,
    evidence_cards: List[Dict[str, Any]],
    evidence_gaps: List[str] | None = None,
) -> str:
    """
    构建 synthesize_evidence_node 使用的用户 prompt。

    输入：
    - question: 原始研究问题
    - evidence_cards: 结构化证据卡
    - evidence_gaps: judge 阶段识别出的证据缺口

    输出：
    - 可直接传入 LLM 的用户 prompt

    输出要求设计：
    - 生成 4~8 条研究笔记
    - 每条笔记必须有明确证据支撑
    - 证据不足时写成限制或不确定性，而不是补全不存在的信息
    """
    evidence_text = format_grouped_evidence_for_prompt(evidence_cards)
    gaps_text = "、".join(evidence_gaps or []) if evidence_gaps else "（未识别到明确证据缺口）"

    return f"""
研究问题：
{question}

结构化证据：
{evidence_text}

已识别的证据缺口：
{gaps_text}

请基于以上结构化证据生成 4~8 条研究笔记。

要求：
1. 每条笔记一行
2. 只输出有证据支撑的结论
3. 优先保留定义、机制、实现方式、适用场景、限制条件
4. 如果证据存在明显缺口，将缺口写成“不确定性/限制”，不要编造补充事实
5. 不要输出项目符号以外的解释性文字
""".strip()


def fallback_notes_from_evidence(
    evidence_cards: List[Dict[str, Any]],
    limit: int = 8,
) -> List[str]:
    """
    在模型未生成有效 notes 时，从 evidence claims 中生成兜底研究笔记。

    当前策略：
    - 优先保留 claim
    - 同一文本完全重复时只保留一次
    - 最多返回 limit 条，避免后续 report prompt 过长
    """
    notes: List[str] = []
    seen = set()

    for card in evidence_cards:
        claim = (card.get("claim") or "").strip()
        if not claim:
            continue

        normalized = claim.lower()
        if normalized in seen:
            continue

        seen.add(normalized)
        notes.append(claim)

        if len(notes) >= limit:
            break

    return notes
