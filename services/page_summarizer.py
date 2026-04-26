"""
页面摘要服务模块。

模块职责：
1. 将页面正文压缩为适合 evidence card 构建的研究摘要。
2. 根据原始问题、搜索子问题、页面标题和 URL 组织摘要 prompt。
3. 为页面摘要失败场景提供稳定 fallback。

设计目标：
1. 将 read_pages_node 中不断累积的摘要策略下沉到服务层。
2. 让 agents/researcher.py 更接近 workflow 节点编排职责。
3. 保持页面摘要行为与原有实现一致，避免影响 v2 主链稳定性。

当前限制：
- 当前摘要仍依赖通用 SYNTHESIZER_SYSTEM_PROMPT。
- 当前 fallback 只截取页面正文前 500 字符，后续可替换为更结构化的抽取策略。
"""

from typing import Any

from prompts.system_prompts import SYNTHESIZER_SYSTEM_PROMPT


def build_page_summary_prompt(
    *,
    question: str,
    query: str,
    title: str,
    url: str,
    page_content: str,
) -> str:
    """
    构造页面摘要 prompt。

    输入：
    - question: 用户原始研究问题。
    - query: 当前搜索子问题。
    - title: 页面标题。
    - url: 页面 URL。
    - page_content: 已清洗或 fallback 后的页面正文。

    输出：
    - 可直接传入 LLM 的用户 prompt。
    """
    return f"""
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


def fallback_page_summary(page_content: str, limit: int = 500) -> str:
    """
    生成页面摘要失败时的兜底摘要。

    当前策略：
    - 保留页面正文前 limit 个字符。
    - 去除首尾空白，避免下游节点处理多余空行。
    """
    return (page_content or "").strip()[:limit].strip()


def summarize_page_content(
    *,
    question: str,
    query: str,
    title: str,
    url: str,
    page_content: str,
    llm_service: Any,
) -> str:
    """
    对页面正文生成简要研究摘要。

    输入：
    - question: 用户原始研究问题。
    - query: 当前搜索子问题。
    - title: 页面标题。
    - url: 页面 URL。
    - page_content: 页面正文或 snippet fallback。
    - llm_service: 提供 chat(system_prompt, user_prompt) 方法的 LLM 服务。

    输出：
    - 页面摘要文本。
    - page_content 为空时返回空字符串。

    回退策略：
    - 模型调用异常、模型返回空值或 llm_service 不可用时，返回正文前 500 字符。
    """
    page_content = (page_content or "").strip()
    if not page_content:
        return ""

    prompt = build_page_summary_prompt(
        question=question,
        query=query,
        title=title,
        url=url,
        page_content=page_content,
    )

    try:
        summary = llm_service.chat(SYNTHESIZER_SYSTEM_PROMPT, prompt).strip()
        if summary:
            return summary
    except Exception:
        pass

    return fallback_page_summary(page_content)
