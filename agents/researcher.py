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

from urllib.parse import urlparse

# 创建一个全局 LLM 服务实例
# 当前阶段这样写足够：整个程序启动后复用同一个模型客户端
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


def _collect_unique_sources(results: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    """
    从 search_results 中提取最终报告引用来源。

    规则：
    1. 先按 url 去重
    2. 优先保留官方/优先域名来源
    3. 只有优先来源不足时，才用其他来源补足
    """
    from config import PREFERRED_DOMAINS, LOW_PRIORITY_DOMAINS

    deduped_sources = []
    seen_urls = set()

    for item in results:
        url = item.get("url", "").strip()
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)

        deduped_sources.append({
            "title": item.get("title", "").strip() or "未命名来源",
            "url": url,
            "domain": item.get("domain", "").strip(),
            "source_score": item.get("source_score", 0),
        })

    # 先按总体质量排序
    deduped_sources.sort(
        key=lambda item: (
            1 if _domain_matches(item.get("domain", ""), PREFERRED_DOMAINS) else 0,
            0 if _domain_matches(item.get("domain", ""), LOW_PRIORITY_DOMAINS) else 1,
            item.get("source_score", 0),
            len(item.get("title", "")),
        ),
        reverse=True,
    )

    preferred_sources = []
    other_sources = []

    for item in deduped_sources:
        domain = item.get("domain", "").strip().lower()

        if _domain_matches(domain, PREFERRED_DOMAINS):
            preferred_sources.append(item)
        else:
            other_sources.append(item)

    # 优先来源先占位
    selected_sources = preferred_sources[:limit]

    # 不够再补其他来源
    if len(selected_sources) < limit:
        remain = limit - len(selected_sources)
        selected_sources.extend(other_sources[:remain])

    return selected_sources


def _extract_domain(url: str) -> str:
    """
    从 URL 中提取域名，便于后续做来源质量判断。
    例如：
    https://docs.langchain.com/oss/python/langgraph/overview
    -> docs.langchain.com
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower().strip()
    except Exception:
        return ""


def _domain_matches(domain: str, candidates: List[str]) -> bool:
    """
    判断某个 domain 是否命中候选列表。

    例如：
    domain = "docs.langchain.com"
    candidates = ["langchain.com"]
    也应该视为命中，因为它是子域名。
    """
    for candidate in candidates:
        candidate = candidate.lower().strip()
        if not candidate:
            continue
        if domain == candidate or domain.endswith("." + candidate):
            return True
    return False


def _score_search_result(item: Dict[str, Any]) -> int:
    """
    给单条搜索结果打一个简单分数。
    分数越高，说明越优先保留。

    当前策略比较保守：
    - 官方文档 / GitHub 优先
    - 常见社区博客保留，但降权
    - 有标题、有摘要的结果更优先
    """
    from config import PREFERRED_DOMAINS, LOW_PRIORITY_DOMAINS

    score = 0

    url = item.get("url", "").strip()
    title = item.get("title", "").strip()
    snippet = item.get("snippet", "").strip()
    domain = _extract_domain(url)

    # 基础质量分
    if title:
        score += 10
    if snippet:
        score += 10
    if url:
        score += 10

    # 官方/优先来源加分
    if _domain_matches(domain, PREFERRED_DOMAINS):
        score += 50

    # 低优先级来源降分，但不直接删除
    if _domain_matches(domain, LOW_PRIORITY_DOMAINS):
        score -= 15

    return score


def _rank_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对搜索结果按来源质量做排序。
    不做强过滤，只做“优先级排序”。
    """
    enriched_results = []

    for item in results:
        copied = dict(item)
        copied["domain"] = _extract_domain(copied.get("url", ""))
        copied["source_score"] = _score_search_result(copied)
        enriched_results.append(copied)

    enriched_results.sort(
        key=lambda x: (
            x.get("source_score", 0),
            len(x.get("snippet", "")),
            len(x.get("title", "")),
        ),
        reverse=True,
    )

    return enriched_results


def _contains_chinese(text: str) -> bool:
    """
    判断字符串中是否包含中文字符。
    """
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _contains_english_letters(text: str) -> bool:
    """
    判断字符串中是否包含英文字母。
    """
    return any(("a" <= ch.lower() <= "z") for ch in text)


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

    # 统计语言分布，给出提示
    chinese_count = sum(1 for q in queries if _contains_chinese(q))
    english_count = sum(1 for q in queries if _contains_english_letters(q))

    log_step("Plan", f"query language stats: chinese={chinese_count}, english={english_count}")

    if english_count == 0:
        log_step("Plan", "警告：当前 query 全部偏中文，可能不利于检索官方技术资料。")

    if chinese_count == 0:
        log_step("Plan", "提示：当前 query 全部偏英文，可能会减少中文补充资料。")

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
    3. 对来源质量做排序
    4. 控制最终保留结果数
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

            # 没有 url 的结果直接跳过
            if not url:
                continue

            # 去重：如果 url 已经存在，就不重复加入
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
        return {"search_results": []}

    # 对搜索结果做来源质量排序
    ranked_results = _rank_search_results(all_results)

    # 截断：避免把太多低质量结果交给后续节点
    filtered_results = ranked_results[:MAX_FILTERED_RESULTS]

    log_step("Search", f"去重后共保留 {len(all_results)} 条结果")
    log_step("Search", f"排序后最终保留 {len(filtered_results)} 条结果")

    # 打印前几条来源，便于调试观察
    for idx, item in enumerate(filtered_results[:5], start=1):
        log_step(
            "Search",
            f"top_{idx}: score={item.get('source_score', 0)} | domain={item.get('domain', '')} | title={item.get('title', '')}"
        )

    return {"search_results": filtered_results}


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

    # 候选引用来源
    unique_sources = _collect_unique_sources(results, limit=4)

    # 只保留和候选引用来源对应的搜索结果
    selected_urls = {item["url"] for item in unique_sources}
    selected_results = [item for item in results if item.get("url", "") in selected_urls]

    sources_text = "\n".join(
        [
            f"- {item['title']} | {item['url']} | domain={item.get('domain', '')} | score={item.get('source_score', 0)}"
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
            f"source_{idx}: score={item.get('source_score', 0)} | domain={item.get('domain', '')} | title={item.get('title', '')}"
        )

    return {"final_report": final_report}