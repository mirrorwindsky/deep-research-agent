"""
结构化证据卡构建模块。

模块职责：
1. 将 read_pages_node 产出的 page_results 转换为 evidence_cards
2. 从页面摘要和正文中提炼句子级 claim
3. 为每条 claim 绑定同页来源中的 evidence 片段

设计目标：
1. 将 evidence card 构建策略从 workflow 节点层中拆出
2. 保持第一版实现轻量、可解释、易调试
3. 为后续扩展 LLM 结构化抽取、置信度评分、来源覆盖分析保留独立边界

说明：
- 当前版本采用规则型抽取，不额外调用模型
- 当前版本优先使用 page_summary 生成 claim，使用 page_content 寻找 evidence
- 当前版本每个页面最多生成 1~2 条 evidence card
"""

import re
from typing import Any, Dict, List


def _split_research_sentences(text: str) -> List[str]:
    """
    将摘要或正文切分为候选证据句。

    输入：
    - text: 页面摘要、正文或搜索摘要文本

    输出：
    - 清洗后的候选句列表

    设计原因：
    - 第一版 evidence card 构建不引入额外模型调用
    - 使用句子级切分可以快速从 page_summary/page_content 中获得可绑定来源的 claim

    限制说明：
    - 当前切分规则偏启发式，不能完整处理所有缩写和复杂 Markdown
    - 后续可替换为更强的句子切分器或结构化抽取模型
    """
    if not text:
        return []

    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    # 页面正文中常见的段内软换行不应切断 evidence 句子。
    normalized = re.sub(r"(?<![。！？.!?])\n(?![。！？.!?\n])", " ", normalized)

    parts: List[str] = []
    for line in normalized.splitlines():
        line = line.strip().lstrip("-•*0123456789. ").strip()
        if not line:
            continue

        segments = re.split(r"(?<=[。！？.!?])\s+", line)
        parts.extend(segment.strip() for segment in segments if segment.strip())

    cleaned_parts: List[str] = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        part = part.strip(" -•*")
        if part:
            cleaned_parts.append(part)

    return cleaned_parts


def _extract_evidence_keywords(*texts: str) -> List[str]:
    """
    从问题、query、标题或 claim 中提取轻量关键词。

    用途：
    - 对候选 claim 做相关性排序
    - 从 page_content 中寻找与 claim 最匹配的原文证据句
    """
    keywords: List[str] = []

    for text in texts:
        text = (text or "").lower()
        if not text:
            continue

        english_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", text)
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        keywords.extend(english_tokens)
        keywords.extend(chinese_tokens)

    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "what",
        "how",
        "why",
        "official",
        "documentation",
        "docs",
    }

    result: List[str] = []
    seen = set()

    for keyword in keywords:
        keyword = keyword.strip().lower()
        if not keyword or keyword in stopwords or keyword in seen:
            continue

        seen.add(keyword)
        result.append(keyword)

    return result


def _score_sentence_for_evidence(sentence: str, keywords: List[str]) -> int:
    """
    计算候选句作为 evidence claim 的启发式分数。

    评分重点：
    - 是否命中研究问题、query 或标题关键词
    - 句子长度是否足以表达完整信息
    - 是否包含定义、机制、能力、限制等研究型信息线索
    """
    sentence_l = sentence.lower()
    score = 0

    for keyword in keywords:
        if keyword and keyword in sentence_l:
            score += 2

    if 50 <= len(sentence) <= 260:
        score += 2
    elif 24 <= len(sentence) < 50:
        score += 1

    evidence_hints = [
        "is ",
        "are ",
        "means",
        "provides",
        "supports",
        "uses",
        "allows",
        "helps",
        "requires",
        "operator",
        "controller",
        "custom resource",
        "kubernetes",
        "定义",
        "用于",
        "支持",
        "提供",
        "通过",
        "需要",
        "区别",
        "限制",
    ]

    if any(hint in sentence_l for hint in evidence_hints):
        score += 2

    return score


def _is_useful_evidence_sentence(sentence: str) -> bool:
    """
    判断候选句是否适合作为 claim 或 evidence。

    过滤目标：
    - 过短的导航残留
    - 只有符号、文件名或菜单项的文本
    - 明显的交互提示
    """
    sentence = (sentence or "").strip()
    sentence_l = sentence.lower()

    if len(sentence) < 18:
        return False

    noise_phrases = [
        "skip to content",
        "navigation menu",
        "sign in",
        "sign up",
        "reload to refresh your session",
        "repository files navigation",
        "view all files",
        "edit this page",
        "table of contents",
    ]

    if any(phrase in sentence_l for phrase in noise_phrases):
        return False

    alpha_or_cjk_count = len(re.findall(r"[a-zA-Z\u4e00-\u9fff]", sentence))
    if alpha_or_cjk_count < 12:
        return False

    return True


def _shorten_text(text: str, max_chars: int = 320) -> str:
    """
    将 claim/evidence 控制在适合 evidence card 展示和后续 prompt 使用的长度。
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip(" ,，.;；:：") + "..."


def _find_best_evidence_sentence(claim: str, page_content: str, fallback: str) -> str:
    """
    从页面正文中寻找最能支撑 claim 的原文证据句。

    回退策略：
    - 若 page_content 无可用句子，则使用 fallback
    - 若没有高质量匹配句，则使用 claim 本身作为最小可用 evidence
    """
    content_sentences = [
        sentence
        for sentence in _split_research_sentences(page_content)
        if _is_useful_evidence_sentence(sentence)
    ]

    if not content_sentences:
        return _shorten_text(fallback or claim)

    keywords = _extract_evidence_keywords(claim)

    ranked = sorted(
        content_sentences,
        key=lambda sentence: (
            _score_sentence_for_evidence(sentence, keywords),
            -abs(len(sentence) - len(claim)),
        ),
        reverse=True,
    )

    best_sentence = ranked[0] if ranked else ""
    if not best_sentence:
        return _shorten_text(fallback or claim)

    return _shorten_text(best_sentence)


def _build_cards_for_page(
    item: Dict[str, Any],
    question: str,
    max_cards_per_page: int = 2,
) -> List[Dict[str, Any]]:
    """
    从单个 page_result 构建 1~2 条 evidence card。

    输入：
    - item: read_pages_node 输出的单页结果
    - question: 原始研究问题
    - max_cards_per_page: 单页最多生成多少条证据卡

    输出：
    - evidence card 列表

    设计原因：
    - page_summary 通常比 page_content 更短，更适合作为 claim 候选来源
    - page_content 更接近原文，更适合作为 evidence 绑定来源
    - 当前阶段优先做可解释、可调试的规则型抽取
    """
    summary = item.get("page_summary", "").strip()
    snippet = item.get("snippet", "").strip()
    page_content = item.get("page_content", "").strip()

    claim_source_text = summary or snippet or page_content
    candidate_sentences = [
        sentence
        for sentence in _split_research_sentences(claim_source_text)
        if _is_useful_evidence_sentence(sentence)
    ]

    if not candidate_sentences and page_content:
        candidate_sentences = [
            sentence
            for sentence in _split_research_sentences(page_content)
            if _is_useful_evidence_sentence(sentence)
        ]

    if not candidate_sentences:
        return []

    keywords = _extract_evidence_keywords(
        question,
        item.get("query", ""),
        item.get("title", ""),
    )

    ranked_claims = sorted(
        candidate_sentences,
        key=lambda sentence: (
            _score_sentence_for_evidence(sentence, keywords),
            len(sentence),
        ),
        reverse=True,
    )

    cards: List[Dict[str, Any]] = []
    seen_claims = set()

    for claim in ranked_claims:
        claim = _shorten_text(claim, max_chars=260)
        claim_key = claim.lower()

        if claim_key in seen_claims:
            continue

        evidence = _find_best_evidence_sentence(
            claim=claim,
            page_content=page_content,
            fallback=summary or snippet,
        )

        cards.append({
            "sub_question": item.get("query", question),
            "claim": claim,
            "evidence": evidence,
            "source_url": item.get("final_url") or item.get("url", ""),
            "source_title": item.get("title", ""),
            "source_type": item.get("source_type", ""),
            "page_kind": item.get("page_kind", ""),
            "domain": item.get("domain", ""),
            "read_success": item.get("read_success", False),
            "read_error": item.get("read_error", ""),
            "status_code": item.get("status_code"),
        })
        seen_claims.add(claim_key)

        if len(cards) >= max_cards_per_page:
            break

    return cards


def build_evidence_cards_from_pages(
    question: str,
    page_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    从 page_results 构建结构化 evidence cards。

    输入：
    - question: 原始研究问题
    - page_results: read_pages_node 生成的页面级结果列表

    输出：
    - evidence card 列表，每条包含 sub_question / claim / evidence / source 信息

    当前策略：
    - 每个页面最多生成 2 条 evidence card
    - 同一来源 URL 下完全相同的 claim 只保留一次
    - 不跨页面做复杂语义去重，保留来源差异以便后续综合判断
    """
    evidence_cards: List[Dict[str, Any]] = []
    seen_source_claim_pairs = set()

    for item in page_results:
        page_cards = _build_cards_for_page(item, question=question)

        for card in page_cards:
            source_url = card.get("source_url", "")
            claim_key = card.get("claim", "").lower()
            dedupe_key = (source_url, claim_key)

            if dedupe_key in seen_source_claim_pairs:
                continue

            seen_source_claim_pairs.add(dedupe_key)
            evidence_cards.append(card)

    return evidence_cards
