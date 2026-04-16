# agents/researcher.py

"""
Research workflow 节点模块。

模块职责：
1. 定义 research graph 中的核心节点函数
2. 负责在节点级别完成状态读取、调用外部能力、回写状态
3. 保持 workflow 主链清晰：
   plan -> search -> synthesize -> report

设计原则：
1. 节点层负责流程编排，不承担过多底层策略细节
2. 搜索结果质量控制逻辑下沉到 services/search_ranker.py
3. 节点函数尽量保持“读 state -> 做一件事 -> 返回局部更新”的结构
4. 在当前阶段优先保证主链稳定、易调试、易扩展

说明：
- 当前文件保留少量通用辅助函数，例如字符串去重、兜底 notes 提取、语言特征判断
- 搜索结果排序、来源识别、候选引用来源收口等逻辑已抽离到独立服务模块
"""

import json
from typing import Any, Dict, List

from config import MAX_RESULTS_PER_QUERY, MAX_SEARCH_QUERIES
from prompts.output_prompts import REPORT_SYSTEM_PROMPT
from prompts.system_prompts import (
    PLANNER_SYSTEM_PROMPT,
    SYNTHESIZER_SYSTEM_PROMPT,
)
from schemas.state import ResearchState
from services.llm import LLMService
from services.search_ranker import (
    collect_unique_sources,
    rank_search_results,
)
from tools.search import search_web
from utils.logger import log_step

# 创建全局 LLM 服务实例。
#
# 设计原因：
# 1. 避免每次进入节点函数时重复初始化模型客户端
# 2. 当前项目规模较小，此写法已经足够稳定且直接
# 3. 若后续需要支持多模型切换、依赖注入或测试替身，再进一步抽象
llm = LLMService()


def _deduplicate_strings(items: List[str]) -> List[str]:
    """
    对字符串列表做保序去重。

    输入：
    - items: 原始字符串列表

    输出：
    - 去重后的字符串列表，保持首次出现顺序不变

    典型用途：
    - 对 planner 输出的 query 做去重
    - 对 synthesize 阶段的 notes 做去重

    说明：
    - 当前去重基于字符串标准化后的完全匹配
    - 暂不处理“语义相近但文本不同”的重复情况
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


def _fallback_notes_from_results(results: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    """
    从搜索结果中提取兜底研究笔记。

    设计原因：
    - synthesize_node 主要依赖模型将搜索结果压缩为研究笔记
    - 若模型未返回有效内容，整条 workflow 不应直接失效
    - 因此在模型提炼失败时，使用 snippet 生成最简兜底 notes

    参数：
    - results: 搜索结果列表
    - limit: 最多提取多少条兜底笔记

    返回：
    - 基于 snippet 提取的笔记列表

    说明：
    - 当前实现只做最基础的 snippet 去重与截断
    - 后续可扩展为“优先高分来源摘要”或“按来源类型选择摘要”
    """
    notes: List[str] = []
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


def _contains_chinese(text: str) -> bool:
    """
    判断字符串中是否包含中文字符。

    用途：
    - 辅助观察 planner 输出的 query 语言分布
    - 作为当前阶段的简单语言特征统计工具

    说明：
    - 该函数仅判断是否包含中文字符
    - 不负责识别文本主语言，也不做复杂语言分类
    """
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _contains_english_letters(text: str) -> bool:
    """
    判断字符串中是否包含英文字母。

    用途：
    - 辅助观察 planner 输出的 query 语言分布
    - 检查 query 是否包含英文技术术语或英文检索意图

    说明：
    - 该函数仅判断是否存在英文字母
    - 中英混合 query 可能会同时被中文统计与英文统计命中
    """
    return any(("a" <= ch.lower() <= "z") for ch in text)


def plan_node(state: ResearchState) -> Dict[str, Any]:
    """
    plan 节点：将用户原始研究问题拆解为搜索子问题。

    输入：
    - state["question"]

    输出：
    - {"search_queries": [...]}

    当前职责：
    1. 调用 planner prompt 生成结构化 query 列表
    2. 对模型输出做 JSON 解析
    3. 清洗、去重并限制 query 数量
    4. 输出语言分布日志，辅助观察 planner 行为

    稳定性保护：
    - 模型输出不是合法 JSON 时，回退为原问题
    - queries 字段不是列表时，回退为原问题
    - 清洗后无有效 query 时，回退为原问题
    """
    question = state["question"]

    # planner 的用户输入保持简单明确，避免在节点层叠加额外提示噪音
    user_prompt = f"用户研究问题：{question}"

    # 调用模型，期望返回 JSON 格式的搜索子问题列表
    raw_output = llm.chat(PLANNER_SYSTEM_PROMPT, user_prompt)

    try:
        data = json.loads(raw_output)
        queries = data.get("queries", [])

        if not isinstance(queries, list):
            log_step("Plan", "模型输出中的 queries 字段不是列表，已回退为原问题。")
            queries = [question]

    except Exception:
        log_step("Plan", "模型输出不是合法 JSON，已回退为原问题。")
        queries = [question]

    # 仅保留非空字符串，去除多余空白
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]

    # 保序去重，避免出现完全重复的检索子问题
    queries = _deduplicate_strings(queries)

    # 限制 query 数量，避免单轮搜索过于发散
    queries = queries[:MAX_SEARCH_QUERIES]

    # 统计语言特征，便于观察 planner 是否按预期生成中英混合 query
    chinese_count = sum(1 for q in queries if _contains_chinese(q))
    english_count = sum(1 for q in queries if _contains_english_letters(q))

    log_step("Plan", f"query language stats: chinese={chinese_count}, english={english_count}")

    if english_count == 0:
        log_step("Plan", "警告：当前 query 全部偏中文，可能不利于检索官方技术资料。")

    if chinese_count == 0:
        log_step("Plan", "提示：当前 query 全部偏英文，可能会减少中文补充资料。")

    # 清洗后若无有效 query，则继续以原问题兜底
    if not queries:
        queries = [question]

    log_step("Plan", f"生成了 {len(queries)} 个搜索子问题")
    for idx, query in enumerate(queries, start=1):
        log_step("Plan", f"query_{idx}: {query}")

    return {"search_queries": queries}


def search_node(state: ResearchState) -> Dict[str, Any]:
    """
    search 节点：根据搜索子问题执行检索，并对结果进行去重、排序和截断。

    输入：
    - state["search_queries"]

    输出：
    - {"search_results": [...]}

    当前职责：
    1. 逐个 query 调用统一搜索工具接口
    2. 按 URL 去重，避免重复结果污染后续阶段
    3. 调用 search_ranker 对结果做来源质量增强与排序
    4. 截断低优先级结果，减少后续节点处理噪音

    设计说明：
    - 节点层不再直接承担来源打分细节
    - 来源识别、页面识别、query_fit 打分、信息密度打分已下沉到 services/search_ranker.py
    """
    from config import MAX_FILTERED_RESULTS

    queries = state.get("search_queries", [])
    all_results: List[Dict[str, Any]] = []
    seen_urls = set()

    for idx, query in enumerate(queries, start=1):
        results = search_web(query, max_results=MAX_RESULTS_PER_QUERY)
        log_step("Search", f"query_{idx} 返回 {len(results)} 条结果")

        for item in results:
            url = item.get("url", "").strip()

            # 没有 URL 的结果无法作为可靠来源，直接跳过
            if not url:
                continue

            # URL 去重，避免多个 query 返回完全相同的结果
            if url in seen_urls:
                continue

            seen_urls.add(url)

            # 当前阶段统一保留基础字段。
            # 评分增强信息在 rank_search_results() 中统一补充。
            result_item = {
                "title": item.get("title", "").strip(),
                "url": url,
                "snippet": item.get("snippet", "").strip(),
                "query": query,
            }
            all_results.append(result_item)

    if not all_results:
        log_step("Search", "警告：去重后没有保留任何搜索结果。")
        return {"search_results": []}

    # 对搜索结果做来源质量增强与排序
    ranked_results = rank_search_results(all_results)

    # 控制最终结果数量，避免低质量或边缘结果进入后续上下文
    filtered_results = ranked_results[:MAX_FILTERED_RESULTS]

    log_step("Search", f"去重后共保留 {len(all_results)} 条结果")
    log_step("Search", f"排序后最终保留 {len(filtered_results)} 条结果")

    # 输出前几条排序结果，便于在 search only 模式下观察策略行为
    for idx, item in enumerate(filtered_results[:5], start=1):
        log_step(
            "Search",
            f"top_{idx}: score={item.get('source_score', 0)} | "
            f"source_type={item.get('source_type', '')} | "
            f"page_kind={item.get('page_kind', '')} | "
            f"domain={item.get('domain', '')} | "
            f"title={item.get('title', '')}"
        )

    return {"search_results": filtered_results}


def synthesize_node(state: ResearchState) -> Dict[str, Any]:
    """
    synthesize 节点：将搜索结果整理为研究笔记。

    输入：
    - state["question"]
    - state["search_results"]

    输出：
    - {"notes": [...]}

    当前职责：
    1. 将搜索结果组织为供模型阅读的材料
    2. 调用 synthesize prompt 提炼研究笔记
    3. 对输出笔记做简单清洗与去重
    4. 在模型输出失效时，使用搜索摘要做兜底

    设计说明：
    - synthesize 阶段的目标不是直接产出最终报告
    - 该阶段承担“中间压缩层”角色，为 report 阶段提供更稳定的结构化输入
    """
    question = state["question"]
    results = state.get("search_results", [])

    if not results:
        log_step("Synthesize", "没有搜索结果可供综合，返回空 notes。")
        return {"notes": []}

    # 将搜索结果组织成统一材料块，供模型做摘要与提炼
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

    # 逐行提取笔记，并清理常见列表符号
    notes: List[str] = []
    for line in notes_text.splitlines():
        cleaned = line.strip().lstrip("-•1234567890. ").strip()
        if cleaned:
            notes.append(cleaned)

    # 保序去重，避免模型输出重复笔记
    notes = _deduplicate_strings(notes)

    # 若模型未生成有效 notes，则使用 snippet 做兜底
    if not notes:
        log_step("Synthesize", "模型未生成有效 notes，使用 snippet 兜底。")
        notes = _fallback_notes_from_results(results, limit=5)

    log_step("Synthesize", f"提炼出 {len(notes)} 条笔记")
    return {"notes": notes}


def report_node(state: ResearchState) -> Dict[str, Any]:
    """
    report 节点：根据问题、研究笔记和搜索结果生成最终研究报告。

    输入：
    - state["question"]
    - state["notes"]
    - state["search_results"]

    输出：
    - {"final_report": "..."}

    当前职责：
    1. 在有搜索结果时，组织高质量结果与候选引用来源
    2. 在无搜索结果时，返回保守版报告
    3. 控制最终 prompt 中的来源范围，避免模型乱引用或过度发散

    设计说明：
    - report 阶段不直接消费全部搜索结果
    - 更合理的做法是先通过 collect_unique_sources() 收口为少量高质量候选来源
    - 该设计有利于控制引用质量，并减少重复来源占用上下文
    """
    question = state["question"]
    notes = state.get("notes", [])
    results = state.get("search_results", [])

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

    notes_text = "\n".join([f"- {note}" for note in notes]) if notes else "（暂无研究笔记）"

    # 从搜索结果中收集去重后的候选引用来源
    unique_sources = collect_unique_sources(results, limit=4)

    # 仅保留候选引用来源对应的详细搜索结果，减少 prompt 噪音
    selected_urls = {item["url"] for item in unique_sources}
    selected_results = [item for item in results if item.get("url", "") in selected_urls]

    sources_text = "\n".join(
        [
            f"- {item['title']} | {item['url']} | "
            f"domain={item.get('domain', '')} | score={item.get('source_score', 0)}"
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

    user_prompt = f"""
用户问题：
{question}

研究笔记：
{notes_text}

高质量搜索结果：
{results_text}

优先引用来源（已筛选）：
{sources_text}

请生成最终研究报告。

要求：
1. 参考来源只从“优先引用来源（已筛选）”中选择
2. 不要编造不存在的来源
3. 如果某些结论无法从当前来源中支撑，就不要强行下结论
4. 优先引用官方文档、官方博客、官方参考资料
5. 参考来源数量控制在 3~5 条
""".strip()

    final_report = llm.chat(REPORT_SYSTEM_PROMPT, user_prompt)

    log_step("Report", f"报告生成完成，候选引用来源数={len(unique_sources)}")
    for idx, item in enumerate(unique_sources[:5], start=1):
        log_step(
            "Report",
            f"source_{idx}: score={item.get('source_score', 0)} | "
            f"domain={item.get('domain', '')} | title={item.get('title', '')}"
        )

    return {"final_report": final_report}