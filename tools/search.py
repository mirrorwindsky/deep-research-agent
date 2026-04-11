from typing import List, Dict

from config import USE_MOCK_SEARCH, MOCK_MODE
from utils.logger import log_step


def _normal_mock(query: str) -> List[Dict]:
    """
    normal 模式：
    返回看起来较正常的 mock 结果。
    不同 query 会生成不同 url，适合测试主链的正常运行。
    """
    return [
        {
            "title": f"{query} - 结果 1",
            "url": f"https://example.com/{abs(hash(query)) % 10000}/1",
            "snippet": f"{query} 的摘要 1"
        },
        {
            "title": f"{query} - 结果 2",
            "url": f"https://example.com/{abs(hash(query)) % 10000}/2",
            "snippet": f"{query} 的摘要 2"
        },
    ]


def _duplicate_mock(query: str) -> List[Dict]:
    """
    duplicate 模式：
    故意制造跨 query 重复的 url，
    用来测试 search_node 的“按 url 去重”是否真的生效。
    """
    return [
        {
            "title": f"{query} - 重复结果 A",
            "url": "https://example.com/shared/1",
            "snippet": f"{query} 的共享摘要 A"
        },
        {
            "title": f"{query} - 重复结果 B",
            "url": "https://example.com/shared/2",
            "snippet": f"{query} 的共享摘要 B"
        },
    ]


def _empty_mock(query: str) -> List[Dict]:
    """
    empty 模式：
    直接返回空列表，
    用来测试 search_node / synthesize_node / report_node
    在“没有搜索结果”时是否还能稳住。
    """
    return []


def _dirty_mock(query: str) -> List[Dict]:
    """
    dirty 模式：
    故意返回不完整、脏的搜索结果，
    用来测试代码对异常数据的健壮性。

    包含：
    - 缺少 snippet 的结果
    - title/url 为空的结果
    - 一条正常结果
    """
    return [
        {
            "title": f"{query} - 缺摘要结果",
            "url": f"https://example.com/dirty/{abs(hash(query)) % 10000}/1",
        },
        {
            "title": "",
            "url": "",
            "snippet": f"{query} 的脏数据摘要"
        },
        {
            "title": f"{query} - 正常结果",
            "url": f"https://example.com/dirty/{abs(hash(query)) % 10000}/2",
            "snippet": f"{query} 的正常摘要"
        },
    ]


def _mock_search(query: str, max_results: int = 5) -> List[Dict]:
    """
    根据 MOCK_MODE 切换不同测试场景。

    这样做的好处是：
    以后你测试不同 node 时，不需要反复改代码，
    只需要改 .env 里的 MOCK_MODE。
    """
    if MOCK_MODE == "duplicate":
        results = _duplicate_mock(query)
    elif MOCK_MODE == "empty":
        results = _empty_mock(query)
    elif MOCK_MODE == "dirty":
        results = _dirty_mock(query)
    else:
        # 默认走 normal
        results = _normal_mock(query)

    return results[:max_results]


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    对外暴露的统一搜索工具函数。

    当前阶段：
    - 如果 USE_MOCK_SEARCH=True，就使用 mock search
    - 否则以后这里接真实搜索 API
    """
    log_step("SearchTool", f"执行搜索: {query} | mock_mode={MOCK_MODE}")

    if USE_MOCK_SEARCH:
        return _mock_search(query, max_results=max_results)

    raise NotImplementedError("当前未接入真实搜索 API，请先使用 mock search。")