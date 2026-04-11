import json
from typing import Dict, Any, List

from schemas.state import ResearchState
from services.llm import LLMService
from prompts.system_prompts import (
    PLANNER_SYSTEM_PROMPT,
    SYNTHESIZER_SYSTEM_PROMPT,
)
from prompts.output_prompts import REPORT_SYSTEM_PROMPT
from tools.search import search_web
from utils.logger import log_step
from config import MAX_SEARCH_QUERIES, MAX_RESULTS_PER_QUERY

# 创建一个全局 LLM 服务实例
# 当前阶段这样写足够了：整个程序启动后复用同一个模型客户端
llm = LLMService()


def _deduplicate_strings(items: List[str]) -> List[str]:
    """
    对字符串列表做去重，并保持原有顺序。

    例如：
    ["A", "B", "A", "C"] -> ["A", "B", "C"]

    这个工具函数主要给 plan_node 用，
    防止模型生成重复或高度相似的 query。
    """
    seen = set()
    result = []

    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def _fallback_notes_from_results(results: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    """
    当 synthesize_node 没有成功从模型那里得到有效 notes 时，
    使用搜索结果的 snippet 做一个最简单的兜底版本。

    这样做的目的是：
    即使模型在“提炼笔记”这一步失效，整个 workflow 也不会彻底断掉。
    """
    notes = []
    seen = set()

    for item in results:
        snippet = item.get("snippet", "").strip()
        if not snippet:
            continue
        if snippet in seen:
            continue

        seen.add(snippet)
        notes.append(snippet)

        if len(notes) >= limit:
            break

    return notes


def _collect_unique_sources(results: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, str]]:
    """
    从 search_results 中提取唯一来源，按 url 去重。

    返回格式例如：
    [
        {"title": "...", "url": "..."},
        {"title": "...", "url": "..."}
    ]

    report_node 会用它来减少重复来源。
    """
    unique_sources = []
    seen_urls = set()

    for item in results:
        url = item.get("url", "").strip()
        title = item.get("title", "").strip()

        if not url:
            continue
        if url in seen_urls:
            continue

        seen_urls.add(url)
        unique_sources.append({
            "title": title or "未命名来源",
            "url": url,
        })

        if len(unique_sources) >= limit:
            break

    return unique_sources


def plan_node(state: ResearchState) -> Dict[str, Any]:
    """
    plan 节点：把用户原始问题拆成搜索子问题。

    输入：
    - state["question"]

    输出：
    - {"search_queries": [...]}

    稳定性增强点：
    1. 解析 JSON 失败时兜底
    2. query 清洗
    3. query 去重
    4. 数量限制
    """
    question = state["question"]

    # 给模型的用户输入
    user_prompt = f"用户研究问题：{question}"

    # 调用模型，让它返回 JSON 格式的搜索子问题
    raw_output = llm.chat(PLANNER_SYSTEM_PROMPT, user_prompt)

    try:
        # 尝试把模型输出解析成 JSON
        data = json.loads(raw_output)
        queries = data.get("queries", [])

        # 如果 queries 不是列表，就回退
        if not isinstance(queries, list):
            log_step("Plan", "模型输出中 queries 不是列表，已回退为原问题。")
            queries = [question]

    except Exception:
        # 如果模型没有输出合法 JSON，就用原问题兜底
        log_step("Plan", "模型输出不是合法 JSON，已回退为原问题。")
        queries = [question]

    # 只保留非空字符串
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]

    # 去重，避免重复 query
    queries = _deduplicate_strings(queries)

    # 限制 query 数量，避免一次搜太多
    queries = queries[:MAX_SEARCH_QUERIES]

    # 如果一个都没有，继续兜底
    if not queries:
        queries = [question]

    log_step("Plan", f"生成了 {len(queries)} 个搜索子问题")
    for idx, query in enumerate(queries, start=1):
        log_step("Plan", f"query_{idx}: {query}")

    return {"search_queries": queries}


def search_node(state: ResearchState) -> Dict[str, Any]:
    """
    search 节点：逐个执行搜索子问题，并收集结果。

    输入：
    - state["search_queries"]

    输出：
    - {"search_results": [...]}

    稳定性增强点：
    1. 按 url 去重
    2. 跳过空 url
    3. 打印去重后结果数
    """
    queries = state.get("search_queries", [])
    all_results: List[Dict[str, Any]] = []
    seen_urls = set()

    for idx, query in enumerate(queries, start=1):
        # 调用搜索工具
        results = search_web(query, max_results=MAX_RESULTS_PER_QUERY)
        log_step("Search", f"query_{idx} 返回 {len(results)} 条结果")

        for item in results:
            url = item.get("url", "").strip()

            # url 为空就跳过，因为没有链接的结果基本不可用
            if not url:
                continue

            # 按 url 去重，避免多个 query 返回重复结果
            if url in seen_urls:
                continue

            seen_urls.add(url)

            result_item = {
                "title": item.get("title", "").strip(),
                "url": url,
                "snippet": item.get("snippet", "").strip(),
                "query": query,
            }
            all_results.append(result_item)

    if not all_results:
        log_step("Search", "警告：去重后没有保留任何搜索结果。")
    else:
        log_step("Search", f"去重后共保留 {len(all_results)} 条结果")

    return {"search_results": all_results}


def synthesize_node(state: ResearchState) -> Dict[str, Any]:
    """
    synthesize 节点：把搜索结果整理成研究笔记。

    输入：
    - state["question"]
    - state["search_results"]

    输出：
    - {"notes": [...]}

    稳定性增强点：
    1. 如果搜索结果为空，直接返回空 notes
    2. 如果模型输出为空，自动使用 snippet 兜底生成 notes
    3. 对 notes 做简单去重
    """
    question = state["question"]
    results = state.get("search_results", [])

    if not results:
        log_step("Synthesize", "没有搜索结果可供综合，返回空 notes。")
        return {"notes": []}

    # 把搜索结果拼成一段材料，交给模型阅读
    material = "\n".join(
        [
            (
                f"- 标题: {item['title']}\n"
                f"  链接: {item['url']}\n"
                f"  摘要: {item['snippet']}\n"
                f"  来源查询: {item['query']}"
            )
            for item in results
        ]
    )

    user_prompt = f"""
研究问题：
{question}

搜索结果：
{material}

请输出研究笔记。
""".strip()

    notes_text = llm.chat(SYNTHESIZER_SYSTEM_PROMPT, user_prompt)

    # 按行切分，清理可能的列表符号
    notes = []
    for line in notes_text.splitlines():
        cleaned = line.strip().lstrip("-•1234567890. ").strip()
        if cleaned:
            notes.append(cleaned)

    # 对 notes 做简单去重
    notes = _deduplicate_strings(notes)

    # 如果模型没有产出有效 notes，则使用搜索摘要兜底
    if not notes:
        log_step("Synthesize", "模型未生成有效 notes，使用 snippet 兜底。")
        notes = _fallback_notes_from_results(results, limit=5)

    log_step("Synthesize", f"提炼出 {len(notes)} 条笔记")
    return {"notes": notes}


def report_node(state: ResearchState) -> Dict[str, Any]:
    """
    report 节点：根据问题、笔记和搜索结果生成最终报告。
    """
    question = state["question"]
    notes = state.get("notes", [])
    results = state.get("search_results", [])

    # 如果没有任何搜索结果，直接返回一个保守版报告
    # 不再让模型在“无证据”情况下自由生成大段分析
    if not results:
        log_step("Report", "没有搜索结果，返回保守版报告。")

        fallback_report = f"""# 主题概述
当前未检索到与“{question}”相关的搜索结果，因此暂时无法基于外部资料生成可靠研究报告。

# 关键发现
1. 当前搜索结果为空，说明本轮检索未提供可用证据。
2. 现阶段不应输出基于外部来源的结论性分析。
3. 建议检查搜索工具、搜索 query 或 mock 模式设置。

# 参考来源
（暂无可用来源）
"""
        return {"final_report": fallback_report}

    # ===== 以下保留你原本的正常逻辑 =====
    notes_text = "\n".join([f"- {note}" for note in notes]) if notes else "（暂无研究笔记）"

    results_text = "\n".join(
        [
            f"- {item['title']} | {item['url']} | {item['snippet']}"
            for item in results
        ]
    )

    unique_sources = _collect_unique_sources(results, limit=6)
    sources_text = "\n".join(
        [f"- {item['title']} | {item['url']}" for item in unique_sources]
    ) if unique_sources else "（暂无可用来源）"

    user_prompt = f"""
用户问题：
{question}

研究笔记：
{notes_text}

搜索结果：
{results_text}

可引用来源（已去重）：
{sources_text}

请生成最终研究报告。
""".strip()

    final_report = llm.chat(REPORT_SYSTEM_PROMPT, user_prompt)

    log_step("Report", "报告生成完成")
    return {"final_report": final_report}