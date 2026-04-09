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
# 当前阶段这样写足够了
llm = LLMService()


def plan_node(state: ResearchState) -> Dict[str, Any]:
    """
    plan 节点：把用户原始问题拆成搜索子问题。

    输入：
    - state["question"]

    输出：
    - {"search_queries": [...]}

    这是 research workflow 的第一步，
    它的作用不是直接回答问题，而是先决定“应该搜什么”。
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

        # 如果 queries 不是列表，就做兜底
        if not isinstance(queries, list):
            queries = [question]

    except Exception:
        # 如果模型没有按要求输出合法 JSON，就退回到最保守策略：
        # 直接把原问题本身当作唯一搜索 query
        queries = [question]

    # 清理无效 query
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]

    # 限制 query 数量，避免过多搜索
    queries = queries[:MAX_SEARCH_QUERIES]

    # 如果最后一个都没留下来，就继续兜底
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

    这里的核心思想是：
    plan 节点负责“决定搜什么”，
    search 节点负责“真的去搜并收集结果”。
    """
    queries = state.get("search_queries", [])
    all_results: List[Dict[str, Any]] = []

    for idx, query in enumerate(queries, start=1):
        # 调用搜索工具
        results = search_web(query, max_results=MAX_RESULTS_PER_QUERY)
        log_step("Search", f"query_{idx} 返回 {len(results)} 条结果")

        # 给每条搜索结果补上来源 query，方便后面综合分析
        for item in results:
            result_item = {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "query": query,
            }
            all_results.append(result_item)

    return {"search_results": all_results}


def synthesize_node(state: ResearchState) -> Dict[str, Any]:
    """
    synthesize 节点：把搜索结果整理成研究笔记。

    输入：
    - state["question"]
    - state["search_results"]

    输出：
    - {"notes": [...]}

    这一步的作用是：
    不直接根据杂乱搜索结果生成最终报告，
    而是先提炼出中间层“笔记”，降低后续 report 节点的负担。
    """
    question = state["question"]
    results = state.get("search_results", [])

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
        cleaned = line.strip().lstrip("-•").strip()
        if cleaned:
            notes.append(cleaned)

    log_step("Synthesize", f"提炼出 {len(notes)} 条笔记")
    return {"notes": notes}


def report_node(state: ResearchState) -> Dict[str, Any]:
    """
    report 节点：根据问题、笔记和搜索结果生成最终报告。

    输入：
    - state["question"]
    - state["notes"]
    - state["search_results"]

    输出：
    - {"final_report": "..."}

    这是最后一个节点。
    到这里，前面的 plan / search / synthesize 都是在为它准备材料。
    """
    question = state["question"]
    notes = state.get("notes", [])
    results = state.get("search_results", [])

    # 把笔记整理成文本
    notes_text = "\n".join([f"- {note}" for note in notes])

    # 把搜索结果整理成文本
    results_text = "\n".join(
        [
            f"- {item['title']} | {item['url']} | {item['snippet']}"
            for item in results
        ]
    )

    user_prompt = f"""
用户问题：
{question}

研究笔记：
{notes_text}

搜索结果：
{results_text}

请生成最终研究报告。
""".strip()

    final_report = llm.chat(REPORT_SYSTEM_PROMPT, user_prompt)

    log_step("Report", "报告生成完成")
    return {"final_report": final_report}