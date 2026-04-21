# services/search_ranker.py

"""
搜索结果排序与来源质量判断模块。

模块职责：
1. 提供搜索结果的基础清洗与标准化能力
2. 提供来源类型识别与页面形态识别能力
3. 提供基于规则的搜索结果评分与排序能力
4. 为 report 阶段提供去重后的高质量候选来源集合

设计目标：
1. 将搜索结果质量控制逻辑从 researcher.py 中抽离
2. 保持节点层（workflow nodes）与策略层（ranking policy）的职责分离
3. 使搜索排序过程具备可解释性，便于 search only 模式下独立调试
4. 为后续来源规则扩展、评分微调和独立测试保留清晰边界

实现特点：
- 当前版本采用启发式规则，而非学习式排序模型
- 评分逻辑强调“可解释、可维护、可渐进增强”
- 适合作为第一阶段 technical research agent 的来源质量控制基线

适用场景：
- 技术概念调研
- 官方资料优先检索
- 技术实现 / 教程类问题检索
- 初步来源筛选与报告引用来源收口

限制说明：
- 当前分类与评分规则仍为第一版实现，不追求绝对精确
- 中文 query 的关键词提取采用简化策略，尚未引入真正中文分词
- GitHub 来源当前统一视为 repo 类来源，尚未进一步细分官方仓库 / issue / discussion
"""

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from config import (
    AUTHORITATIVE_DOMAINS,
    COMMUNITY_DOMAINS,
    COMPARISON_HINTS,
    EVIDENCE_SNIPPET_GOOD_LEN,
    EVIDENCE_SNIPPET_MIN_LEN,
    EXAMPLE_HINTS,
    FORUM_DOMAINS,
    IMPLEMENTATION_HINTS,
    ISSUE_HINTS,
    LOW_PRIORITY_DOMAINS,
    MARKETING_HINTS,
    OFFICIAL_BLOG_HINTS,
    OFFICIAL_DOC_HINTS,
    OFFICIAL_INTENT_HINTS,
    PAGE_KIND_SCORES,
    QUERY_FIT_COMPARISON_BONUS,
    QUERY_FIT_EXACT_PHRASE_BONUS,
    QUERY_FIT_HOME_PAGE_PENALTY,
    QUERY_FIT_IMPLEMENTATION_BONUS,
    QUERY_FIT_OFFICIAL_INTENT_BONUS,
    QUERY_FIT_SNIPPET_HIT,
    QUERY_FIT_SPECIFIC_PAGE_BONUS,
    QUERY_FIT_TITLE_HIT,
    README_HINTS,
    SOURCE_TYPE_SCORES,
)


def extract_domain(url: str) -> str:
    """
    从 URL 中提取规范化域名。

    用途：
    - 为来源类型识别提供基础字段
    - 为后续来源匹配与排序提供统一输入

    参数：
    - url: 搜索结果中的链接字符串

    返回：
    - 规范化后的域名
    - 若解析失败，则返回空字符串

    实现说明：
    - 当前实现会去除常见的 `www.` 前缀，以减少匹配歧义
    - 异常场景下统一返回空字符串，避免脏数据中断排序流程
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().strip()

        # 去除常见的 www. 前缀，降低域名匹配复杂度
        if domain.startswith("www."):
            domain = domain[4:]

        return domain
    except Exception:
        # 搜索结果可能包含脏链接或缺失字段，异常场景统一兜底为空字符串
        return ""


def normalize_text(text: str) -> str:
    """
    对输入文本进行最基础的规范化处理。

    处理内容：
    1. None / 空值保护
    2. 去首尾空格
    3. 转为小写

    设计原因：
    - 启发式规则匹配通常不希望受到大小写与首尾空格影响
    - 统一预处理可以减少后续函数中的重复清洗逻辑
    """
    return (text or "").strip().lower()


def contains_any(text: str, hints: List[str]) -> bool:
    """
    判断文本中是否包含任意一个提示词。

    典型用途：
    - 判断页面是否像文档页
    - 判断页面是否像博客页
    - 判断页面是否像 example / issue / marketing 页面

    参数：
    - text: 待匹配文本
    - hints: 提示词列表

    返回：
    - True  表示命中至少一个提示词
    - False 表示未命中

    实现说明：
    - 当前采用简单子串匹配，规则易读、易调试
    - 第一版实现优先选择简单策略，而非复杂模式匹配
    """
    text = normalize_text(text)
    return any(h.lower() in text for h in hints)


def domain_matches(domain: str, candidates: List[str]) -> bool:
    """
    判断域名是否命中候选域名列表。

    匹配规则：
    - 完全相等视为命中
    - 子域名后缀匹配也视为命中

    示例：
    - domain = "docs.langchain.com"
    - candidate = "langchain.com"
    - 上述情况视为命中

    设计原因：
    - 技术站点常使用子域名承载文档、博客、产品页
    - 若只做完全匹配，会遗漏大量有效来源
    """
    domain = normalize_text(domain)

    for candidate in candidates:
        candidate = normalize_text(candidate)
        if not candidate:
            continue

        if domain == candidate or domain.endswith("." + candidate):
            return True

    return False


def tokenize_query(query: str) -> List[str]:
    """
    对 query 做轻量级关键词提取。

    当前策略：
    - 英文部分：提取类似单词、标识符、技术术语的 token
    - 中文部分：暂不做复杂分词，先保留完整 query 作为整体 token

    设计原因：
    - 第一阶段不引入中文分词依赖，避免增加额外复杂度
    - 当前目标是为 query_fit 提供一个“足够可用”的基础关键词集合
    - 该策略虽较粗糙，但便于理解与调试

    限制说明：
    - 该函数不是严格意义上的分词器
    - 中文 query 的匹配能力仍然有限，后续可根据需要替换为更强实现
    """
    query = normalize_text(query)
    if not query:
        return []

    # 提取英文风格 token，例如：
    # langgraph / function-calling / pytorch / operator / api
    english_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-\.]+", query)

    # 使用 dict.fromkeys 实现保序去重
    tokens = list(dict.fromkeys(english_tokens))

    # 若 query 中存在中文字符，则保留整句作为一个整体 token
    # 当前版本采用该简化策略，以维持实现轻量且可解释
    if re.search(r"[\u4e00-\u9fff]", query):
        tokens.append(query)

    return tokens


def _extract_meaningful_query_phrases(query: str) -> List[str]:
    """
    提取较有意义的 query 短语，用于完整短语命中加分。

    当前策略：
    - 保留原始 query 全句
    - 若 query 中含多个英文 token，则额外拼接较长英文短语

    设计原因：
    - 用于区分“完整问题命中”与“零散关键词命中”
    - 帮助具体落点页压过泛相关首页
    """
    query_l = normalize_text(query)
    if not query_l:
        return []

    phrases = [query_l]

    english_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-\.]+", query_l)
    if len(english_tokens) >= 2:
        phrases.append(" ".join(english_tokens))

    return list(dict.fromkeys([p for p in phrases if p]))


def _is_home_like_page(url: str) -> bool:
    """
    判断页面是否更像首页或泛入口页。

    典型示例：
    - /
    - /home/
    - /docs/home/
    - /docs/
    """
    url_l = normalize_text(url)
    parsed = urlparse(url_l)
    path = (parsed.path or "").strip("/")

    if path == "":
        return True

    home_like_paths = {
        "home",
        "docs",
        "docs/home",
        "index",
    }

    return path in home_like_paths


def _is_specific_content_page(url: str) -> bool:
    """
    判断页面是否更像具体内容页，而不是站点首页。

    判定思路：
    - 路径层级较深
    - 或包含 concepts / tutorial / guide / operator 等更具体的内容段
    """
    url_l = normalize_text(url)
    parsed = urlparse(url_l)
    path = (parsed.path or "").strip("/")

    if not path:
        return False

    if path.count("/") >= 2:
        return True

    specific_hints = [
        "concept",
        "concepts",
        "tutorial",
        "guide",
        "operator",
        "sdk",
        "reference",
        "api",
        "example",
        "examples",
        "quickstart",
    ]

    return any(hint in path for hint in specific_hints)


def classify_source_type(url: str, title: str, snippet: str) -> str:
    """
    判断搜索结果所属的来源类型。

    来源类型示例：
    - official_docs
    - official_repo
    - official_blog
    - community_article
    - forum_discussion
    - low_priority
    - unknown

    设计思路：
    - 来源质量控制不再直接依赖少量具体站点名
    - 优先将来源抽象为“类型”，再进行统一评分
    - 该方式更适合通用 technical research 场景

    说明：
    - 当前版本采用启发式分类规则
    - 分类结果不追求绝对精确，优先保证规则简单且可解释
    """
    domain = extract_domain(url)
    full_text = f"{normalize_text(url)} {normalize_text(title)} {normalize_text(snippet)}"

    # 低优先级来源优先识别，避免噪音结果获得较高排序位置
    if domain_matches(domain, LOW_PRIORITY_DOMAINS):
        return "low_priority"

    # 问答站、论坛、讨论社区通常适合作为补充证据，而非主证据来源
    if domain_matches(domain, FORUM_DOMAINS):
        return "forum_discussion"

    # 当前版本将 GitHub 统一归为 repo 类来源
    # 后续可进一步细分为 README、examples、issues、discussions 等子类型
    if "github.com" in domain:
        return "official_repo"

    # 只有命中“主题权威域名”时，文档/博客特征才可以升级为 official_*
    # 这样可以避免把普通第三方博客误判为 official_blog。
    if domain_matches(domain, AUTHORITATIVE_DOMAINS):
        if contains_any(full_text, OFFICIAL_DOC_HINTS):
            return "official_docs"

        if contains_any(full_text, OFFICIAL_BLOG_HINTS):
            return "official_blog"

    # 常见技术社区平台统一归为 community_article
    if domain_matches(domain, COMMUNITY_DOMAINS):
        return "community_article"

    # 对普通博客页、教程页、第三方厂商文章做保守归类。
    # 即便 URL 命中 blog 特征，也不直接升级为 official_blog。
    if any(word in full_text for word in ["tutorial", "guide", "how to", "example", "博客", "教程"]):
        return "community_article"

    if contains_any(full_text, OFFICIAL_BLOG_HINTS):
        return "community_article"

    return "unknown"


def classify_page_kind(url: str, title: str, snippet: str) -> str:
    """
    判断页面形态（page kind）。

    设计原因：
    - 仅使用来源类型仍不足以表达页面质量差异
    - 同一来源站点中的不同页面，其技术价值可能差异明显
      例如：
      - GitHub README 与 GitHub issue
      - 官网文档页与官网营销页
      - 博客发布说明与普通宣传文章

    返回值示例：
    - api_reference
    - docs_page
    - example_page
    - readme
    - comparison_page
    - tutorial_page
    - issue_or_discussion
    - release_note
    - marketing_page
    - content_farm_page
    - unknown
    """
    full_text = f"{normalize_text(url)} {normalize_text(title)} {normalize_text(snippet)}"
    url_l = normalize_text(url)
    title_l = normalize_text(title)

    # issue / discussion 更适合作为补充证据，而不是主证据
    if contains_any(full_text, ISSUE_HINTS):
        return "issue_or_discussion"

    # GitHub 仓库根页经常不会显式带 /readme，
    # 但 title、snippet、repo 名里会出现 sample / example / quickstart 等信号。
    # 对这类页面做提前识别，避免落到 unknown。
    if "github.com" in url_l:
        if any(word in full_text for word in ["sample", "samples", "example", "examples", "quickstart"]):
            return "example_page"

        # GitHub 仓库根页通常默认展示 README，
        # 若路径形态像 owner/repo，则可保守视为 readme。
        parsed = urlparse(url_l)
        path = (parsed.path or "").strip("/")
        if path and path.count("/") == 1:
            return "readme"

    # README 对项目介绍、安装、快速上手通常具有较高价值
    if contains_any(full_text, README_HINTS):
        return "readme"

    # example / quickstart / getting-started 页面通常对实现问题很有帮助
    if contains_any(full_text, EXAMPLE_HINTS):
        return "example_page"

    # 官方文档与 API reference 页面通常是技术 research 的高价值来源
    if contains_any(full_text, OFFICIAL_DOC_HINTS):
        if "/api/" in url_l or "/reference/" in url_l or "api reference" in title_l:
            return "api_reference"
        return "docs_page"

    # 对比类页面用于回答方案差异、选型取舍和适用场景，不应归入 release_note。
    if contains_any(full_text, COMPARISON_HINTS):
        return "comparison_page"

    # release / changelog 页面主要提供版本与功能演进信息
    if contains_any(full_text, OFFICIAL_BLOG_HINTS):
        return "release_note"

    # 营销页通常技术信息密度较低，默认降权
    if contains_any(full_text, MARKETING_HINTS):
        return "marketing_page"

    # 教程 / 指南页常见于社区技术文章
    if any(word in full_text for word in ["tutorial", "guide", "walkthrough", "教程", "指南"]):
        return "tutorial_page"

    # 内容农场识别在第一版中采用非常保守的规则，避免误伤正常技术文章
    if any(word in full_text for word in ["top 10", "ultimate guide", "must know"]):
        return "content_farm_page"

    return "unknown"


def score_query_fit(query: str, title: str, snippet: str, url: str) -> Dict[str, Any]:
    """
    计算搜索结果与当前 query 的贴合度。

    为什么需要该维度：
    - 来源再强，若与当前问题不贴合，也不应排在最前
    - 技术 research 的排序不应只看“来源是否权威”，还应看“是否回答当前问题”

    当前评分逻辑：
    1. 标题命中 query 关键词 -> 加分
    2. 摘要命中 query 关键词 -> 加分
    3. 完整 query / 长短语命中 -> 额外加分
    4. 若 query 为对比型问题，结果也呈现对比特征 -> 加分
    5. 若 query 为实现 / 教程型问题，结果也呈现教程特征 -> 加分
    6. 若 query 明确偏向官方资料，结果也体现官方特征 -> 加分
    7. 具体内容页加分，首页或泛入口页轻微降权

    返回：
    - score: 数值分数
    - reasons: 评分原因列表
    """
    query_l = normalize_text(query)
    title_l = normalize_text(title)
    snippet_l = normalize_text(snippet)
    url_l = normalize_text(url)

    score = 0
    reasons: List[str] = []

    tokens = tokenize_query(query)

    title_hit = any(token and token in title_l for token in tokens)
    snippet_hit = any(token and token in snippet_l for token in tokens)

    if title_hit:
        score += QUERY_FIT_TITLE_HIT
        reasons.append("标题命中 query 关键词")

    if snippet_hit:
        score += QUERY_FIT_SNIPPET_HIT
        reasons.append("摘要命中 query 关键词")

    # 完整短语命中比单个 token 命中更强，适合把具体页抬高
    phrases = _extract_meaningful_query_phrases(query)
    if any(phrase and (phrase in title_l or phrase in snippet_l or phrase in url_l) for phrase in phrases):
        score += QUERY_FIT_EXACT_PHRASE_BONUS
        reasons.append("完整 query 短语命中")

    if contains_any(query_l, COMPARISON_HINTS) and any(h in title_l or h in snippet_l for h in COMPARISON_HINTS):
        score += QUERY_FIT_COMPARISON_BONUS
        reasons.append("匹配对比类问题意图")

    if contains_any(query_l, IMPLEMENTATION_HINTS) and any(h in title_l or h in snippet_l or h in url_l for h in IMPLEMENTATION_HINTS):
        score += QUERY_FIT_IMPLEMENTATION_BONUS
        reasons.append("匹配实现/教程类问题意图")

    if contains_any(query_l, OFFICIAL_INTENT_HINTS) and any(h in title_l or h in snippet_l or h in url_l for h in OFFICIAL_INTENT_HINTS):
        score += QUERY_FIT_OFFICIAL_INTENT_BONUS
        reasons.append("匹配官方资料意图")

    # 具体内容页加分：首页或泛入口页轻微降权
    if _is_specific_content_page(url):
        score += QUERY_FIT_SPECIFIC_PAGE_BONUS
        reasons.append("页面为较具体的内容页")

    if _is_home_like_page(url):
        score += QUERY_FIT_HOME_PAGE_PENALTY
        reasons.append("页面偏首页或泛入口页")

    return {
        "score": score,
        "reasons": reasons,
    }


def score_evidence_density(title: str, snippet: str) -> Dict[str, Any]:
    """
    粗略评估搜索结果摘要的信息密度。

    该维度解决的问题：
    - 某些搜索结果虽然有 title 与 url，但 snippet 极短，信息价值有限
    - 某些结果摘要更完整，适合进入后续 synthesize / report 阶段

    当前逻辑：
    - 标题为空：扣分
    - 摘要为空：扣分
    - 摘要较长：适度加分
    - 摘要过短：适度减分

    说明：
    - 该函数不判断内容真伪
    - 该函数只判断“从摘要可见信息量”是否足够
    """
    title = (title or "").strip()
    snippet = (snippet or "").strip()

    score = 0
    reasons: List[str] = []

    if not title:
        score -= 1
        reasons.append("标题为空")

    if not snippet:
        score -= 1
        reasons.append("摘要为空")
        return {
            "score": score,
            "reasons": reasons,
        }

    if len(snippet) >= EVIDENCE_SNIPPET_GOOD_LEN:
        score += 1
        reasons.append("摘要信息量较高")
    elif len(snippet) >= EVIDENCE_SNIPPET_MIN_LEN:
        score += 0
        reasons.append("摘要信息量一般")
    else:
        score -= 1
        reasons.append("摘要过短")

    return {
        "score": score,
        "reasons": reasons,
    }


def score_search_result(query: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """
    对单条搜索结果进行完整评分，并返回增强后的结果结构。

    输入：
    - query: 触发该结果的搜索子问题
    - item: 原始搜索结果，通常包含 title / url / snippet

    输出：
    - 保留原始字段
    - 补充来源类型、页面形态、评分项与解释信息

    设计原因：
    - 单纯返回整数分数不利于调试
    - 返回详细结构后，可在 search only 模式中直接观察排序依据
    - 该结构也可直接复用于 report 阶段的来源收口逻辑

    当前评分由四部分组成：
    1. 来源类型分
    2. 页面形态分
    3. query 贴合度分
    4. 信息密度分
    """
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    snippet = (item.get("snippet") or "").strip()

    source_type = classify_source_type(url, title, snippet)
    page_kind = classify_page_kind(url, title, snippet)

    source_type_score = SOURCE_TYPE_SCORES.get(source_type, 0)
    page_kind_score = PAGE_KIND_SCORES.get(page_kind, 0)

    query_fit_info = score_query_fit(query, title, snippet, url)
    evidence_info = score_evidence_density(title, snippet)

    # 第一版排序策略采用加和模型，便于解释和调试
    total_score = (
        source_type_score
        + page_kind_score
        + query_fit_info["score"]
        + evidence_info["score"]
    )

    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "query": query,
        "domain": extract_domain(url),
        "source_type": source_type,
        "page_kind": page_kind,
        "source_score": total_score,
        "source_type_score": source_type_score,
        "page_kind_score": page_kind_score,
        "query_fit_score": query_fit_info["score"],
        "evidence_score": evidence_info["score"],
        "reasons": [
            f"source_type={source_type}({source_type_score})",
            f"page_kind={page_kind}({page_kind_score})",
            *query_fit_info["reasons"],
            *evidence_info["reasons"],
        ],
    }


def rank_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对搜索结果列表进行统一增强与排序。

    输入：
    - results: 原始搜索结果列表，每条结果通常包含 title / url / snippet / query

    输出：
    - enriched_results: 带评分与解释信息的排序结果列表

    处理流程：
    1. 对每条结果调用 score_search_result()
    2. 生成增强后的结果结构
    3. 根据多个评分维度做降序排序

    当前排序优先级：
    1. source_score      总分
    2. query_fit_score   与当前问题的贴合度
    3. source_type_score 来源类型分
    4. page_kind_score   页面形态分
    5. snippet 长度      信息量兜底比较

    设计说明：
    - 第一版不只按单一分数排序，而是保留若干细粒度比较项
    - 该设计在分数接近时能提供更稳定的结果顺序
    """
    enriched_results: List[Dict[str, Any]] = []

    for item in results:
        query = item.get("query", "")
        enriched_results.append(score_search_result(query, item))

    enriched_results.sort(
        key=lambda x: (
            x.get("source_score", 0),
            x.get("query_fit_score", 0),
            x.get("source_type_score", 0),
            x.get("page_kind_score", 0),
            len(x.get("snippet", "")),
        ),
        reverse=True,
    )

    return enriched_results


def collect_unique_sources(results: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    """
    从排序结果中收集最终报告可引用的唯一来源集合。

    设计原因：
    - report 阶段通常不需要消费全部搜索结果
    - 更合理的做法是先收口成少量、去重、相对高质量的候选来源
    - 该函数为最终报告中的参考来源筛选提供基础能力

    当前策略：
    1. 先按 URL 去重
    2. 再按照已有评分字段排序
    3. 最后只保留前 limit 条

    后续可扩展方向：
    - 尽量覆盖不同来源类型，避免单一来源垄断
    - 限制同一站点的最大引用数量
    - 针对不同问题类型采用差异化引用策略
    """
    deduped: List[Dict[str, Any]] = []
    seen_urls = set()

    for item in results:
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        deduped.append(item)

    deduped.sort(
        key=lambda x: (
            x.get("source_score", 0),
            x.get("query_fit_score", 0),
            x.get("source_type_score", 0),
        ),
        reverse=True,
    )

    return deduped[:limit]
