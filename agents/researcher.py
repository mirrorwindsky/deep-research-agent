# agents/researcher.py

"""
Research workflow 节点模块。

模块职责：
1. 定义 research graph 中的核心节点函数
2. 负责在节点级别完成状态读取、调用外部能力、回写状态
3. 保持 workflow 主链清晰，并逐步向 deep research v2 升级：
   plan -> search -> read_pages -> build_evidence_cards -> judge_search_quality -> rewrite_query / synthesize_evidence -> report

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

from config import MAX_PAGE_READS, MAX_RESULTS_PER_QUERY, MAX_SEARCH_QUERIES
from prompts.output_prompts import REPORT_SYSTEM_PROMPT
from prompts.system_prompts import (
    PLANNER_SYSTEM_PROMPT,
    SYNTHESIZER_SYSTEM_PROMPT,
)
from schemas.state import ResearchState
from services.evidence_builder import build_evidence_cards_from_pages
from services.evidence_judge import judge_evidence_quality
from services.evidence_synthesizer import (
    build_evidence_synthesis_prompt,
    fallback_notes_from_evidence,
)
from services.llm import LLMService
from services.report_builder import build_report_prompt
from services.search_ranker import (
    rank_search_results,
)
from services.page_reader import fetch_page_content
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


def _summarize_page_content(
    question: str,
    query: str,
    title: str,
    url: str,
    page_content: str,
) -> str:
    """
    对页面正文生成简要研究摘要。

    设计目标：
    1. 将页面正文压缩为更适合 evidence card 构建的摘要
    2. 保持摘要与当前研究问题和子 query 相关
    3. 控制摘要长度，避免后续节点处理过于发散

    回退策略：
    - 若 page_content 为空，则返回空字符串
    - 若模型调用异常或返回空值，则回退到正文前若干字符
    """
    page_content = (page_content or "").strip()
    if not page_content:
        return ""

    prompt = f"""
研究主问题：
{question}

当前子问题：
{query}

页面标题：
{title}

页面链接：
{url}

页面正文：
{page_content}

请基于页面正文，生成 3~5 句简明研究摘要。
要求：
1. 只保留与研究问题相关的信息
2. 尽量提取定义、关键机制、区别、实现要点、限制条件等内容
3. 不要输出项目符号
4. 不要编造页面中不存在的信息
""".strip()

    try:
        summary = llm.chat(SYNTHESIZER_SYSTEM_PROMPT, prompt).strip()
        if summary:
            return summary
    except Exception:
        pass

    # 模型摘要失败时，回退到正文前若干字符
    return page_content[:500].strip()


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

    return {
        "search_queries": queries,
        "retry_count": 0,
        "needs_retry": False,
        "rewritten_queries": [],
    }


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

    # 若存在补搜后的 rewritten_queries，则优先使用；
    # 否则使用 planner 生成的 search_queries。
    queries = state.get("rewritten_queries") or state.get("search_queries", [])
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


def read_pages_node(state: ResearchState) -> Dict[str, Any]:
    """
    read_pages 节点：读取高优先级搜索结果对应的页面内容。

    当前职责：
    1. 读取前若干条高分搜索结果对应的页面正文
    2. 对正文做页面级摘要
    3. 为 evidence card 构建提供页面级输入

    当前实现策略：
    - 仅处理前 MAX_PAGE_READS 条高分结果
    - 页面请求失败时，回退使用原始 snippet
    - 页面摘要失败时，回退使用正文片段
    """
    question = state.get("question", "")
    search_results = state.get("search_results", [])

    if not search_results:
        log_step("ReadPages", "没有 search_results，返回空 page_results。")
        return {"page_results": []}

    selected_results = search_results[:MAX_PAGE_READS]
    page_results: List[Dict[str, Any]] = []

    for idx, item in enumerate(selected_results, start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        query = item.get("query", "")
        snippet = item.get("snippet", "")

        read_result = fetch_page_content(url)

        read_success = read_result.get("read_success", False)
        page_content = read_result.get("page_content", "").strip()

        # 若页面正文抓取失败，则回退使用 snippet 作为最小可用内容
        if not page_content:
            page_content = snippet.strip()

        page_summary = _summarize_page_content(
            question=question,
            query=query,
            title=title,
            url=url,
            page_content=page_content,
        )

        page_item = {
            "title": title,
            "url": url,
            "query": query,
            "snippet": snippet,
            "domain": item.get("domain", ""),
            "source_type": item.get("source_type", ""),
            "page_kind": item.get("page_kind", ""),
            "source_score": item.get("source_score", 0),
            "source_type_score": item.get("source_type_score", 0),
            "page_kind_score": item.get("page_kind_score", 0),
            "query_fit_score": item.get("query_fit_score", 0),
            "evidence_score": item.get("evidence_score", 0),
            "reasons": item.get("reasons", []),
            "read_success": read_success,
            "read_error": read_result.get("read_error", ""),
            "final_url": read_result.get("final_url", url),
            "status_code": read_result.get("status_code"),
            "content_type": read_result.get("content_type", ""),
            "page_content": page_content,
            "page_summary": page_summary,
        }
        page_results.append(page_item)

        log_step(
            "ReadPages",
            f"page_{idx}: read_success={read_success} | "
            f"domain={page_item.get('domain', '')} | "
            f"title={title}"
        )

        if not read_success and read_result.get("read_error"):
            log_step("ReadPages", f"page_{idx} fallback: {read_result['read_error']}")

    log_step("ReadPages", f"完成页面读取，共生成 {len(page_results)} 条 page_results")
    return {"page_results": page_results}


def build_evidence_cards_node(state: ResearchState) -> Dict[str, Any]:
    """
    build_evidence_cards 节点：将页面结果转换为结构化证据卡。

    当前阶段目标：
    - 从 page_summary/page_content 中提炼句子级 claim
    - 将 claim 绑定到同页 page_content 中更接近原文的 evidence
    - 为后续 evidence-based synthesize / report 提供结构化输入

    当前实现策略：
    1. 每个页面最多生成 2 条 evidence card
    2. 优先从 page_summary 生成 claim，必要时回退到 snippet/page_content
    3. evidence 优先来自 page_content 中与 claim 关键词重合度最高的句子
    4. 暂不引入复杂置信度建模或额外模型调用
    """
    question = state.get("question", "")
    page_results = state.get("page_results", [])

    evidence_cards = build_evidence_cards_from_pages(
        question=question,
        page_results=page_results,
    )

    log_step("Evidence", f"构建 {len(evidence_cards)} 条 evidence_cards")
    return {"evidence_cards": evidence_cards}


def judge_search_quality_node(state: ResearchState) -> Dict[str, Any]:
    """
    judge_search_quality 节点：判断当前搜索与证据质量是否足够进入综合阶段。

    当前规则：
    1. evidence_cards 数量过少时标记 insufficient_evidence
    2. 缺少官方来源时标记 official_source_missing
    3. 证据过度集中于单一 domain 时标记 source_diversity_low
    4. 缺少 example/readme 类实现证据时标记 example_source_missing
    5. 若已经补搜过一次，则不再触发补搜

    输出：
    - needs_retry: 是否进入 rewrite_query 分支
    - evidence_gaps: 当前识别出的证据缺口，供 rewrite_query_node 使用
    """
    evidence_cards = state.get("evidence_cards", [])
    retry_count = state.get("retry_count", 0)

    quality_result = judge_evidence_quality(
        evidence_cards=evidence_cards,
        retry_count=retry_count,
    )
    needs_retry = quality_result["needs_retry"]
    evidence_gaps = quality_result["evidence_gaps"]
    metrics = quality_result["metrics"]

    log_step(
        "Judge",
        f"evidence_cards={metrics['evidence_count']} | "
        f"official_count={metrics['official_count']} | "
        f"domains={metrics['domain_count']} | "
        f"implementation_count={metrics['implementation_count']} | "
        f"retry_count={metrics['retry_count']} | "
        f"needs_retry={needs_retry}"
    )

    if evidence_gaps:
        log_step("Judge", f"evidence_gaps={', '.join(evidence_gaps)}")

    return {
        "needs_retry": needs_retry,
        "evidence_gaps": evidence_gaps,
    }


def rewrite_query_node(state: ResearchState) -> Dict[str, Any]:
    """
    rewrite_query 节点：在当前证据不足时生成一轮补搜 query。

    当前阶段采用基于 evidence_gaps 的规则改写：
    - official_source_missing: 补官方文档 / 官方参考资料 query
    - example_source_missing: 补 GitHub example / tutorial query
    - insufficient_evidence: 补更宽的 docs / guide / reference query
    - source_diversity_low: 补不同来源形态的 docs / examples query

    后续将逐步扩展为：
    1. 将 evidence_gaps 与子问题覆盖情况结合
    2. 根据具体 topic 类型定制补搜模板
    3. 使用模型进行更智能的 query rewrite
    """
    question = state.get("question", "")
    original_queries = state.get("search_queries", [])
    retry_count = state.get("retry_count", 0)
    evidence_gaps = state.get("evidence_gaps", [])

    base_queries = original_queries or [question]
    primary_query = base_queries[0] if base_queries else question

    rewritten_queries: List[str] = []

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

    # 若 judge 未给出明确缺口，保留一个稳定兜底策略。
    if not rewritten_queries:
        rewritten_queries = [
            f"{query} official documentation"
            for query in base_queries[:2]
        ]

    # 保序去重，避免生成重复补搜 query
    rewritten_queries = _deduplicate_strings(rewritten_queries)
    rewritten_queries = rewritten_queries[:MAX_SEARCH_QUERIES]

    new_retry_count = retry_count + 1

    log_step(
        "RewriteQuery",
        f"基于 evidence_gaps={evidence_gaps or ['fallback']} 生成 {len(rewritten_queries)} 条补搜 query"
    )
    for idx, query in enumerate(rewritten_queries, start=1):
        log_step("RewriteQuery", f"rewrite_query_{idx}: {query}")

    return {
        "rewritten_queries": rewritten_queries,
        "retry_count": new_retry_count,
    }


def synthesize_evidence_node(state: ResearchState) -> Dict[str, Any]:
    """
    synthesize_evidence 节点：基于 evidence_cards 生成综合笔记。

    当前阶段采用 evidence-first 策略：
    - 若 evidence_cards 存在，则优先基于 evidence_cards 生成 notes
    - 若 evidence_cards 为空，则回退复用原有 synthesize_node 逻辑
    - 若模型未生成有效 notes，则从 evidence claims 生成兜底 notes

    设计原因：
    - v2 graph 的综合层应消费结构化证据，而不是直接消费搜索结果
    - 节点层只负责流程编排，证据材料组织下沉到 services/evidence_synthesizer.py
    """
    question = state["question"]
    evidence_cards = state.get("evidence_cards", [])
    evidence_gaps = state.get("evidence_gaps", [])

    if not evidence_cards:
        log_step("SynthesizeEvidence", "没有 evidence_cards，回退使用原 synthesize_node 逻辑。")
        return synthesize_node(state)

    user_prompt = build_evidence_synthesis_prompt(
        question=question,
        evidence_cards=evidence_cards,
        evidence_gaps=evidence_gaps,
    )

    notes_text = llm.chat(SYNTHESIZER_SYSTEM_PROMPT, user_prompt)

    notes: List[str] = []
    for line in notes_text.splitlines():
        cleaned = line.strip().lstrip("-•1234567890. ").strip()
        if cleaned:
            notes.append(cleaned)

    notes = _deduplicate_strings(notes)

    if not notes:
        log_step("SynthesizeEvidence", "模型未生成有效 notes，回退使用证据 claim。")
        notes = fallback_notes_from_evidence(evidence_cards, limit=8)

    log_step(
        "SynthesizeEvidence",
        f"基于 {len(evidence_cards)} 条 evidence_cards 提炼出 {len(notes)} 条笔记"
    )
    return {"notes": notes}


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
    report 节点：根据问题、研究笔记、结构化证据和来源生成最终研究报告。

    输入：
    - state["question"]
    - state["notes"]
    - state["search_results"]
    - state["evidence_cards"]

    输出：
    - {"final_report": "..."}

    当前职责：
    1. 优先使用 evidence_cards 组织结构化证据与引用来源
    2. 当 evidence_cards 不存在时，回退使用高质量搜索结果与候选引用来源
    3. 在无证据、无搜索结果时，返回保守版报告
    3. 控制最终 prompt 中的来源范围，避免模型乱引用或过度发散

    设计说明：
    - v2 主链应优先基于 evidence_cards 生成报告
    - 搜索结果仍作为兼容回退，用于 evidence 不可用的场景
    - 引用来源优先来自实际支撑 claim 的 evidence cards
    """
    question = state["question"]
    notes = state.get("notes", [])
    results = state.get("search_results", [])
    evidence_cards = state.get("evidence_cards", [])

    if not results and not evidence_cards:
        log_step("Report", "没有搜索结果或结构化证据，返回保守版报告。")

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

    report_material = build_report_prompt(
        question=question,
        notes=notes,
        search_results=results,
        evidence_cards=evidence_cards,
    )
    user_prompt = report_material["prompt"]
    unique_sources = report_material["unique_sources"]

    final_report = llm.chat(REPORT_SYSTEM_PROMPT, user_prompt)

    log_step(
        "Report",
        f"报告生成完成，evidence_cards={len(evidence_cards)} | 候选引用来源数={len(unique_sources)}"
    )
    for idx, item in enumerate(unique_sources[:5], start=1):
        score_text = (
            f"score={item['source_score']} | "
            if "source_score" in item
            else ""
        )
        log_step(
            "Report",
            f"source_{idx}: {score_text}"
            f"source_type={item.get('source_type', '')} | "
            f"page_kind={item.get('page_kind', '')} | "
            f"domain={item.get('domain', '')} | "
            f"title={item.get('title', '')}"
        )

    return {"final_report": final_report}
