from typing import List, Dict, Any
import requests

from config import (
    USE_MOCK_SEARCH,
    MOCK_MODE,
    TAVILY_API_KEY,
    TAVILY_SEARCH_URL,
    TAVILY_SEARCH_DEPTH,
)
from utils.logger import log_step


# =========================
# Mock Search 部分
# =========================

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
    用来测试 search_node 的按 url 去重逻辑。
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
    返回空结果，测试空搜索结果时整条链是否稳住。
    """
    return []


def _dirty_mock(query: str) -> List[Dict]:
    """
    dirty 模式：
    返回带缺字段、空字段的脏数据，
    用来测试 search_node / synthesize_node / report_node 的健壮性。
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
    根据 MOCK_MODE 返回不同测试场景。
    """
    if MOCK_MODE == "duplicate":
        results = _duplicate_mock(query)
    elif MOCK_MODE == "empty":
        results = _empty_mock(query)
    elif MOCK_MODE == "dirty":
        results = _dirty_mock(query)
    else:
        results = _normal_mock(query)

    return results[:max_results]


# =========================
# 真实搜索部分
# =========================

def _normalize_real_result(item: Dict[str, Any]) -> Dict[str, str]:
    """
    把真实搜索 API 返回的数据统一清洗成项目内部使用的结构：
    - title
    - url
    - snippet

    这样做的好处是：
    后面的 search_node / synthesize_node / report_node
    完全不用关心底层接的是哪个搜索服务。
    """
    return {
        "title": str(item.get("title", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "snippet": str(item.get("content", "") or item.get("snippet", "")).strip(),
    }


def _real_search_tavily(query: str, max_results: int = 5) -> List[Dict]:
    """
    使用 Tavily 进行真实搜索。

    注意：
    这里的实现目标是“先把真实搜索双模式结构搭起来”，
    不是一次性追求所有高级参数都齐全。
    """
    if not TAVILY_API_KEY:
        raise ValueError(
            "USE_MOCK_SEARCH=False 时，必须在 .env 中配置 TAVILY_API_KEY。"
        )

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": TAVILY_SEARCH_DEPTH,
        "max_results": max_results,
        # 先关闭这些额外返回，保持结果结构尽量简单
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        response = requests.post(
            TAVILY_SEARCH_URL,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as e:
        log_step("SearchTool", f"真实搜索请求失败: {e}")
        return []

    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        log_step("SearchTool", "真实搜索返回结果格式异常：results 不是列表。")
        return []

    normalized_results = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue

        cleaned = _normalize_real_result(item)

        # 保证至少 url 或 title 有一个是像样的
        if not cleaned["title"] and not cleaned["url"]:
            continue

        normalized_results.append(cleaned)

    return normalized_results[:max_results]


# =========================
# 对外统一接口
# =========================

def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    项目对外统一使用的搜索函数。

    双模式逻辑：
    - USE_MOCK_SEARCH=True  -> 使用 mock search
    - USE_MOCK_SEARCH=False -> 使用真实搜索 API

    返回统一结构：
    [
        {
            "title": "...",
            "url": "...",
            "snippet": "..."
        }
    ]
    """
    if USE_MOCK_SEARCH:
        log_step("SearchTool", f"执行搜索: {query} | mock_mode={MOCK_MODE}")
        return _mock_search(query, max_results=max_results)

    log_step("SearchTool", f"执行真实搜索: {query}")
    return _real_search_tavily(query, max_results=max_results)