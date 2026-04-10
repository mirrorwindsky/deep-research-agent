from typing import List, Dict
from config import USE_MOCK_SEARCH
from utils.logger import log_step


# 预置几组更像真实世界的 mock 数据
MOCK_SEARCH_DB = {
    "LangGraph 的核心概念和架构特点": [
        {
            "title": "LangGraph Overview",
            "url": "https://docs.langchain.com/langgraph/overview",
            "snippet": "LangGraph 是一个面向有状态 agent workflow 的编排框架，强调状态、节点与边。"
        },
        {
            "title": "LangGraph Quickstart",
            "url": "https://docs.langchain.com/langgraph/quickstart",
            "snippet": "LangGraph 提供 StateGraph 等核心抽象，用于构建复杂流程。"
        },
        {
            "title": "What is LangGraph",
            "url": "https://example.com/langgraph-intro",
            "snippet": "LangGraph 适合长流程、多步骤、带状态的 agent 系统。"
        },
    ],
    "普通函数调用 agent 的工作原理和典型实现": [
        {
            "title": "Function Calling Agent Basics",
            "url": "https://example.com/function-calling-agent",
            "snippet": "普通函数调用 agent 通常由 LLM 决定是否调用工具，再由程序执行函数并回填结果。"
        },
        {
            "title": "Tool Calling Pattern",
            "url": "https://example.com/tool-calling-pattern",
            "snippet": "这类 agent 常采用线性循环：思考、调用工具、接收结果、继续回答。"
        },
        {
            "title": "LangGraph Overview",
            "url": "https://docs.langchain.com/langgraph/overview",
            "snippet": "有些函数调用 agent 在复杂任务上会遇到状态管理困难。"
        },
    ],
    "LangGraph 与普通函数调用 agent 在应用场景和性能上的对比": [
        {
            "title": "Agent Architecture Comparison",
            "url": "https://example.com/agent-compare",
            "snippet": "LangGraph 更适合复杂长流程，普通函数调用 agent 更适合轻量、线性任务。"
        },
        {
            "title": "LangGraph vs Tool Calling",
            "url": "https://example.com/langgraph-vs-toolcalling",
            "snippet": "LangGraph 在状态管理和可扩展性方面更强，但实现复杂度也更高。"
        },
        {
            "title": "Tool Calling Pattern",
            "url": "https://example.com/tool-calling-pattern",
            "snippet": "普通函数调用 agent 开销更低，但复杂控制流支持较弱。"
        },
    ],
}


def _default_mock_results(query: str) -> List[Dict]:
    """
    当 query 没命中预置 mock 数据时，使用兜底假数据。
    """
    return [
        {
            "title": f"{query} - 示例结果 1",
            "url": f"https://example.com/search/{abs(hash(query)) % 10000}/1",
            "snippet": f"这是关于“{query}”的示例摘要 1。"
        },
        {
            "title": f"{query} - 示例结果 2",
            "url": f"https://example.com/search/{abs(hash(query)) % 10000}/2",
            "snippet": f"这是关于“{query}”的示例摘要 2。"
        },
    ]


def _mock_search(query: str, max_results: int = 5) -> List[Dict]:
    """
    更真实的 mock search：
    1. 不同 query 返回不同数据
    2. 某些 url 会跨 query 重复，用来测试去重
    3. 没命中时用默认假数据兜底
    """
    results = MOCK_SEARCH_DB.get(query, _default_mock_results(query))
    return results[:max_results]


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    log_step("SearchTool", f"执行搜索: {query}")

    if USE_MOCK_SEARCH:
        return _mock_search(query, max_results=max_results)

    raise NotImplementedError("当前未接入真实搜索 API，请先使用 mock search。")