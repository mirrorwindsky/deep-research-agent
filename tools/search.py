from typing import List, Dict
from config import USE_MOCK_SEARCH
from utils.logger import log_step


def _mock_search(query: str, max_results: int = 5) -> List[Dict]:
    """
    这是 mock 搜索函数。

    作用：
    在还没有接入真实搜索 API 时，先返回一些假数据，
    这样整个 research workflow 就能先跑通。

    参数：
    - query: 当前要搜索的子问题
    - max_results: 最多返回多少条结果

    返回：
    - 一个列表，每一项都是统一结构的搜索结果字典
    """
    mock_results = [
        {
            "title": f"{query} - 示例结果 1",
            "url": "https://example.com/1",
            "snippet": f"这是关于“{query}”的示例摘要 1。"
        },
        {
            "title": f"{query} - 示例结果 2",
            "url": "https://example.com/2",
            "snippet": f"这是关于“{query}”的示例摘要 2。"
        },
        {
            "title": f"{query} - 示例结果 3",
            "url": "https://example.com/3",
            "snippet": f"这是关于“{query}”的示例摘要 3。"
        },
    ]
    return mock_results[:max_results]


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    对外暴露的统一搜索工具函数。

    当前阶段先根据配置决定是否使用 mock search。
    以后你接入真实搜索 API 时，可以直接在这里扩展。

    返回结果结构统一为：
    - title: 结果标题
    - url: 结果链接
    - snippet: 简短摘要
    """
    log_step("SearchTool", f"执行搜索: {query}")

    if USE_MOCK_SEARCH:
        return _mock_search(query, max_results=max_results)

    # 真实搜索 API 以后接在这里
    raise NotImplementedError("当前未接入真实搜索 API，请先使用 mock search。")