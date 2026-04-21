"""
报告生成材料构建模块。

模块职责：
1. 将 notes、search_results、evidence_cards 组织为 report prompt
2. 优先从 evidence_cards 收集最终报告引用来源
3. 在缺少 evidence_cards 时回退使用搜索结果来源

设计目标：
1. 将报告材料组织逻辑从 report_node 中拆出
2. 保持 report_node 只负责读取 state、调用模型、回写结果
3. 为后续扩展引用格式、证据排序、报告结构模板保留独立边界
"""

from typing import Any, Dict, List

from services.search_ranker import collect_unique_sources


def _format_read_status(item: Dict[str, Any]) -> str:
    """
    将页面读取状态格式化为报告材料中的可靠性提示。

    设计原因：
    - read_success=True 表示证据来自真实页面正文
    - read_success=False 表示页面读取失败，证据通常来自搜索摘要或兜底文本
    - 在 report prompt 中显式标注该状态，便于模型表达来源局限
    """
    if item.get("read_success", False):
        status_code = item.get("status_code")
        return f"成功（HTTP {status_code}）" if status_code else "成功"

    read_error = item.get("read_error", "")
    if read_error:
        return f"失败（使用兜底内容；{read_error}）"

    return "失败（使用兜底内容）"


def _format_evidence_source(item: Dict[str, Any]) -> str:
    """
    格式化 evidence 来源层级，供报告材料显式区分正文证据与 fallback 证据。
    """
    evidence_source = item.get("evidence_source", "")
    if evidence_source:
        return evidence_source

    if item.get("read_success", False):
        return "page_content"

    return "snippet_fallback"


def collect_unique_evidence_sources(
    evidence_cards: List[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    从 evidence cards 中收集去重后的引用来源。

    设计原因：
    - v2 报告应优先引用已经进入证据卡的页面来源
    - 相比直接从 search_results 收口，evidence 来源更接近实际支撑结论的页面
    """
    sources: List[Dict[str, Any]] = []
    seen_urls = set()

    for card in evidence_cards:
        url = (card.get("source_url") or "").strip()
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        sources.append({
            "title": card.get("source_title", ""),
            "url": url,
            "domain": card.get("domain", ""),
            "source_type": card.get("source_type", ""),
            "page_kind": card.get("page_kind", ""),
            "read_success": card.get("read_success", False),
            "read_error": card.get("read_error", ""),
            "status_code": card.get("status_code"),
            "evidence_source": card.get("evidence_source", ""),
        })

        if len(sources) >= limit:
            break

    return sources


def format_evidence_cards_for_prompt(evidence_cards: List[Dict[str, Any]]) -> str:
    """
    将 evidence cards 格式化为 report prompt 中的结构化证据材料。
    """
    if not evidence_cards:
        return "（暂无结构化证据）"

    return "\n".join(
        [
            (
                f"- 子问题: {item.get('sub_question', '')}\n"
                f"  结论: {item.get('claim', '')}\n"
                f"  证据: {item.get('evidence', '')}\n"
                f"  来源标题: {item.get('source_title', '')}\n"
                f"  来源链接: {item.get('source_url', '')}\n"
                f"  来源类型: {item.get('source_type', '')}\n"
                f"  页面类型: {item.get('page_kind', '')}\n"
                f"  evidence_source: {_format_evidence_source(item)}\n"
                f"  页面读取: {_format_read_status(item)}"
            )
            for item in evidence_cards
        ]
    )


def build_report_prompt(
    question: str,
    notes: List[str],
    search_results: List[Dict[str, Any]],
    evidence_cards: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    构建 report_node 使用的用户 prompt 与候选引用来源。

    输入：
    - question: 原始研究问题
    - notes: 综合笔记
    - search_results: 排序后的搜索结果
    - evidence_cards: 结构化证据卡

    输出：
    - prompt: 可直接传入 LLM 的用户 prompt
    - unique_sources: 本次报告允许引用的候选来源

    当前策略：
    - 若存在 evidence_cards，则优先从 evidence_cards 收口引用来源
    - 若没有 evidence_cards，则回退到 search_results 的高质量来源收口
    """
    notes_text = "\n".join([f"- {note}" for note in notes]) if notes else "（暂无研究笔记）"
    evidence_text = format_evidence_cards_for_prompt(evidence_cards)

    evidence_sources = collect_unique_evidence_sources(evidence_cards, limit=5)

    if evidence_sources:
        unique_sources = evidence_sources
    else:
        unique_sources = collect_unique_sources(search_results, limit=4)

    selected_urls = {item["url"] for item in unique_sources}
    selected_results = [
        item
        for item in search_results
        if item.get("url", "") in selected_urls
    ]

    sources_text = "\n".join(
        [
            f"- {item.get('title', '')} | {item.get('url', '')} | "
            f"domain={item.get('domain', '')} | "
            f"source_type={item.get('source_type', '')} | "
            f"page_kind={item.get('page_kind', '')} | "
            f"evidence_source={_format_evidence_source(item)} | "
            f"read_status={_format_read_status(item)}"
            for item in unique_sources
        ]
    ) if unique_sources else "（暂无可用来源）"

    results_text = "\n".join(
        [
            f"- 标题: {item.get('title', '')}\n"
            f"  链接: {item.get('url', '')}\n"
            f"  摘要: {item.get('snippet', '')}\n"
            f"  域名: {item.get('domain', '')}\n"
            f"  分数: {item.get('source_score', 0)}"
            for item in selected_results
        ]
    ) if selected_results else "（暂无搜索结果）"

    prompt = f"""
用户问题：
{question}

研究笔记：
{notes_text}

结构化证据：
{evidence_text}

高质量搜索结果：
{results_text}

优先引用来源（已筛选）：
{sources_text}

请生成最终研究报告。

报告结构：
# 主题概述
用 2~4 句话说明问题背景和总体判断。

# 核心结论
列出 3~6 条核心结论。每条结论必须能从“结构化证据”或“研究笔记”中找到支撑。

# 分问题分析
按结构化证据中的子问题组织分析。每个分问题下说明：
- 结论
- 依据
- 来源

# 局限与不确定性
说明当前证据不足、来源覆盖不足、缺少实现案例或缺少对比材料的地方。

# 参考来源
只列“优先引用来源（已筛选）”中的来源标题和链接。

要求：
1. 参考来源只从“优先引用来源（已筛选）”中选择
2. 不要编造不存在的来源
3. 优先根据“结构化证据”中的结论和证据组织报告，不要只复述搜索摘要
4. 每个重要结论都应能对应至少一个来源
5. 优先引用官方文档、官方博客、官方参考资料
6. 参考来源数量控制在 3~5 条
7. 如果某些结论无法从结构化证据或当前来源中支撑，就不要强行下结论
8. 如果结构化证据为空，才允许主要依据“高质量搜索结果”生成保守报告
9. 若某个来源的“页面读取”为失败，应在“局限与不确定性”中说明该来源仅作为兜底参考
""".strip()

    return {
        "prompt": prompt,
        "unique_sources": unique_sources,
    }
