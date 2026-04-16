# tools/search.py

"""
统一搜索工具模块。

模块职责：
1. 提供项目内部统一使用的搜索入口 `search_web()`
2. 支持 mock search 与真实搜索双模式切换
3. 将不同搜索后端的返回结果清洗为统一结构
4. 为 workflow 节点层屏蔽底层搜索服务差异

设计目标：
1. 使 search_node 无需关心底层到底是 mock 还是真实搜索
2. 保证搜索工具输出结构统一，降低后续节点复杂度
3. 利用 mock 模式支持稳定性测试与局部调试
4. 为未来扩展更多真实搜索服务保留清晰边界

统一返回结构：
[
    {
        "title": "...",
        "url": "...",
        "snippet": "..."
    }
]

说明：
- 当前真实搜索后端使用 Tavily
- 当前 mock search 支持多种测试场景，用于验证节点鲁棒性
- 若后续接入更多搜索后端，可在本模块中继续增加独立实现函数
"""

from typing import Any, Dict, List

import requests

from config import (
    MOCK_MODE,
    TAVILY_API_KEY,
    TAVILY_SEARCH_DEPTH,
    TAVILY_SEARCH_URL,
    USE_MOCK_SEARCH,
)
from utils.logger import log_step


# =========================
# Mock Search 部分
# =========================

def _normal_mock(query: str) -> List[Dict[str, str]]:
    """
    normal 模式的 mock 搜索结果生成器。

    设计用途：
    - 提供看起来较正常的搜索结果
    - 不同 query 会生成不同 URL
    - 适合验证主链在正常输入下是否能够跑通

    返回结果特征：
    - title / url / snippet 字段齐全
    - URL 与 query 相关，便于观察去重逻辑是否正常
    """
    return [
        {
            "title": f"{query} - 结果 1",
            "url": f"https://example.com/{abs(hash(query)) % 10000}/1",
            "snippet": f"{query} 的摘要 1",
        },
        {
            "title": f"{query} - 结果 2",
            "url": f"https://example.com/{abs(hash(query)) % 10000}/2",
            "snippet": f"{query} 的摘要 2",
        },
    ]


def _duplicate_mock(query: str) -> List[Dict[str, str]]:
    """
    duplicate 模式的 mock 搜索结果生成器。

    设计用途：
    - 故意制造跨 query 重复的 URL
    - 用于测试 search_node 的按 URL 去重能力

    返回结果特征：
    - 不同 query 会共享相同 URL
    - 适合验证重复搜索结果是否会被正确合并
    """
    return [
        {
            "title": f"{query} - 重复结果 A",
            "url": "https://example.com/shared/1",
            "snippet": f"{query} 的共享摘要 A",
        },
        {
            "title": f"{query} - 重复结果 B",
            "url": "https://example.com/shared/2",
            "snippet": f"{query} 的共享摘要 B",
        },
    ]


def _empty_mock(query: str) -> List[Dict[str, str]]:
    """
    empty 模式的 mock 搜索结果生成器。

    设计用途：
    - 返回空结果列表
    - 用于测试空搜索结果场景下整条 workflow 是否能够稳住

    适合验证：
    - search_node 的空结果处理
    - synthesize_node 的空输入处理
    - report_node 的保守报告分支
    """
    return []


def _dirty_mock(query: str) -> List[Dict[str, str]]:
    """
    dirty 模式的 mock 搜索结果生成器。

    设计用途：
    - 返回包含缺字段、空字段、部分正常字段的脏数据
    - 用于测试 search_node / synthesize_node / report_node 的健壮性

    返回结果特征：
    - 第一条结果缺少 snippet
    - 第二条结果 title 与 url 为空
    - 第三条结果为正常结果

    设计说明：
    - 当前脏数据场景集中测试“字段不完整”这一类常见问题
    - 后续可继续扩展更多异常场景，例如类型错误、非字典结果等
    """
    return [
        {
            "title": f"{query} - 缺摘要结果",
            "url": f"https://example.com/dirty/{abs(hash(query)) % 10000}/1",
        },
        {
            "title": "",
            "url": "",
            "snippet": f"{query} 的脏数据摘要",
        },
        {
            "title": f"{query} - 正常结果",
            "url": f"https://example.com/dirty/{abs(hash(query)) % 10000}/2",
            "snippet": f"{query} 的正常摘要",
        },
    ]


def _mock_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    根据 MOCK_MODE 选择对应的 mock 搜索场景。

    参数：
    - query: 当前搜索子问题
    - max_results: 最多返回结果数

    返回：
    - 统一结构的搜索结果列表

    支持模式：
    - normal
    - duplicate
    - empty
    - dirty

    说明：
    - 若 MOCK_MODE 未命中任何显式模式，则默认回退到 normal
    - 返回结果会在本函数末尾统一按 max_results 截断
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
    将真实搜索后端返回的单条结果清洗为项目统一结构。

    当前统一字段：
    - title
    - url
    - snippet

    设计原因：
    - 不同搜索服务返回字段命名可能不同
    - workflow 节点层不应关心底层搜索服务的字段差异
    - 将结构统一后，search_node / synthesize_node / report_node 可直接复用

    当前兼容策略：
    - title 直接读取 title 字段
    - url 直接读取 url 字段
    - snippet 优先读取 content，若不存在则回退到 snippet

    说明：
    - 当前 Tavily 返回中 content 通常比 snippet 更完整
    - 后续若接入其他搜索后端，可在此函数或独立函数中扩展兼容逻辑
    """
    return {
        "title": str(item.get("title", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "snippet": str(item.get("content", "") or item.get("snippet", "")).strip(),
    }


def _real_search_tavily(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    使用 Tavily 执行真实搜索。

    参数：
    - query: 当前搜索子问题
    - max_results: 最多请求多少条结果

    返回：
    - 统一结构的搜索结果列表

    当前实现目标：
    - 先稳定建立“真实搜索双模式结构”
    - 保持接口简单，便于观察与调试
    - 不一次性引入过多高级参数，避免增加系统复杂度

    错误处理策略：
    - 若未配置 TAVILY_API_KEY，则抛出明确错误
    - 若请求失败，则记录日志并返回空列表
    - 若返回结构异常，则记录日志并返回空列表
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
        # 当前阶段关闭额外返回字段，尽量保持结果结构简单
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

    except requests.RequestException as exc:
        log_step("SearchTool", f"真实搜索请求失败: {exc}")
        return []

    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        log_step("SearchTool", "真实搜索返回结构异常：results 字段不是列表。")
        return []

    normalized_results: List[Dict[str, str]] = []

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        cleaned = _normalize_real_result(item)

        # 至少要求 title 或 url 之一可用。
        # 若二者同时为空，则该结果基本没有保留价值。
        if not cleaned["title"] and not cleaned["url"]:
            continue

        normalized_results.append(cleaned)

    return normalized_results[:max_results]


# =========================
# 对外统一入口
# =========================

def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    项目内部统一使用的搜索函数。

    双模式逻辑：
    - USE_MOCK_SEARCH=True  -> 使用 mock search
    - USE_MOCK_SEARCH=False -> 使用真实搜索 API

    参数：
    - query: 当前搜索子问题
    - max_results: 最多返回结果数

    返回：
    - 统一结构的搜索结果列表

    设计原因：
    - workflow 节点层只依赖这一统一入口
    - 节点层无需区分当前到底是 mock 测试还是真实搜索
    - 底层后端替换或扩展时，调用方式保持不变

    当前行为：
    - mock 模式下会输出 mock_mode 日志
    - 真实搜索模式下会输出真实搜索日志
    """
    if USE_MOCK_SEARCH:
        log_step("SearchTool", f"执行搜索: {query} | mock_mode={MOCK_MODE}")
        return _mock_search(query, max_results=max_results)

    log_step("SearchTool", f"执行真实搜索: {query}")
    return _real_search_tavily(query, max_results=max_results)