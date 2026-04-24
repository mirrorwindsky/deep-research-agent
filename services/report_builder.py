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

import re
from typing import Any, Dict, List, Optional

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


def _attach_source_ids(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    为候选来源分配稳定的引用编号。

    设计原因：
    - 编号只属于本次 report prompt 的候选来源集合
    - 不修改原始 evidence card，避免把报告格式细节写回证据层
    - 同一 URL 在来源列表和 evidence 材料中必须解析为同一个编号
    """
    indexed_sources: List[Dict[str, Any]] = []

    for idx, item in enumerate(sources, start=1):
        source = dict(item)
        source["source_id"] = idx
        indexed_sources.append(source)

    return indexed_sources


def _build_source_id_by_url(sources: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    根据已编号候选来源生成 URL 到 source_id 的映射。
    """
    source_id_by_url: Dict[str, int] = {}

    for item in sources:
        url = (item.get("url") or "").strip()
        source_id = item.get("source_id")
        if url and isinstance(source_id, int):
            source_id_by_url[url] = source_id

    return source_id_by_url


def _format_source_id(source_id: Any) -> str:
    """
    将来源编号格式化为报告引用标记。
    """
    if isinstance(source_id, int):
        return f"[{source_id}]"

    return "未列入候选来源"


def format_evidence_cards_for_prompt(
    evidence_cards: List[Dict[str, Any]],
    source_id_by_url: Optional[Dict[str, int]] = None,
) -> str:
    """
    将 evidence cards 格式化为 report prompt 中的结构化证据材料。
    """
    if not evidence_cards:
        return "（暂无结构化证据）"

    source_id_by_url = source_id_by_url or {}

    return "\n".join(
        [
            (
                f"- 子问题: {item.get('sub_question', '')}\n"
                f"  source_id: {_format_source_id(source_id_by_url.get((item.get('source_url') or '').strip()))}\n"
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

    evidence_sources = collect_unique_evidence_sources(evidence_cards, limit=5)

    if evidence_sources:
        unique_sources = _attach_source_ids(evidence_sources)
    else:
        unique_sources = _attach_source_ids(collect_unique_sources(search_results, limit=4))

    source_id_by_url = _build_source_id_by_url(unique_sources)
    evidence_text = format_evidence_cards_for_prompt(
        evidence_cards=evidence_cards,
        source_id_by_url=source_id_by_url,
    )

    selected_urls = {item["url"] for item in unique_sources}
    selected_results = [
        item
        for item in search_results
        if item.get("url", "") in selected_urls
    ]

    sources_text = "\n".join(
        [
            f"[{item.get('source_id')}] {item.get('title', '')}\n"
            f"URL: {item.get('url', '')}\n"
            f"domain: {item.get('domain', '')}\n"
            f"source_type: {item.get('source_type', '')}\n"
            f"page_kind: {item.get('page_kind', '')}\n"
            f"evidence_source: {_format_evidence_source(item)}\n"
            f"read_status: {_format_read_status(item)}"
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
列出 3~6 条核心结论。每条结论必须能从“结构化证据”或“研究笔记”中找到支撑，并使用 [1]、[2] 这类来源编号标注依据。

# 分问题分析
按结构化证据中的子问题组织分析。每个分问题下说明：
- 结论
- 依据
- 来源

# 局限与不确定性
说明当前证据不足、来源覆盖不足、缺少实现案例或缺少对比材料的地方。

# 参考来源
只列“优先引用来源（已筛选）”中的来源编号、标题和链接。

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
10. 关键结论、分问题分析和参考来源必须使用 [1]、[2] 这类来源编号
11. 只能引用“优先引用来源（已筛选）”中列出的编号，不得引用未列出的编号
12. 若某条结构化证据的 source_id 为“未列入候选来源”，不得将该证据对应来源写成引用编号
13. 正文、分问题分析或局限性中引用过的每一个编号，都必须在“参考来源”中列出对应来源
""".strip()

    return {
        "prompt": prompt,
        "unique_sources": unique_sources,
    }


def _format_reference_source(item: Dict[str, Any]) -> str:
    """
    将候选来源格式化为最终报告参考来源条目。
    """
    return (
        f"[{item.get('source_id')}] {item.get('title', '')}\n"
        f"链接: {item.get('url', '')}"
    )


def ensure_referenced_sources_are_listed(
    report: str,
    unique_sources: List[Dict[str, Any]],
) -> str:
    """
    确保最终报告中引用过的候选来源编号都出现在参考来源列表。

    设计原因：
    - LLM 可能在正文或局限性中引用了候选编号，但遗漏对应参考来源条目
    - 该函数只补充已存在于 unique_sources 的来源，不创建新来源
    - 该后处理为后续 report_validator 提供一个低风险的稳定兜底
    """
    report = report or ""
    if not report.strip() or not unique_sources:
        return report

    source_by_id = {
        item.get("source_id"): item
        for item in unique_sources
        if isinstance(item.get("source_id"), int)
    }
    if not source_by_id:
        return report

    cited_ids = {
        int(match)
        for match in re.findall(r"\[(\d+)\]", report)
        if int(match) in source_by_id
    }
    if not cited_ids:
        return report

    reference_heading = "# 参考来源"
    heading_index = report.find(reference_heading)

    if heading_index >= 0:
        body = report[:heading_index]
        references = report[heading_index:]
    else:
        body = report.rstrip()
        references = reference_heading

    listed_ids = {
        int(match)
        for match in re.findall(r"(?m)^\[(\d+)\]", references)
        if int(match) in source_by_id
    }

    missing_ids = sorted(cited_ids - listed_ids)
    if not missing_ids:
        return report

    missing_text = "\n\n".join(
        _format_reference_source(source_by_id[source_id])
        for source_id in missing_ids
    )

    references = references.rstrip()
    if references == reference_heading:
        references = f"{reference_heading}\n\n{missing_text}"
    else:
        references = f"{references}\n\n{missing_text}"

    return f"{body.rstrip()}\n\n{references}\n"
