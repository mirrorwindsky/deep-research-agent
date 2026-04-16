# schemas/state.py

"""
Research workflow 共享状态定义模块。

模块职责：
1. 定义整个 deep research workflow 的统一状态结构
2. 为各节点之间的数据传递提供一致的数据契约
3. 明确主链各阶段会读写哪些核心字段

设计目标：
1. 支持从“搜索结果级”流程升级到“页面阅读 + 证据组织 + 质量判断”流程
2. 保持状态字段命名清晰，便于节点开发与调试
3. 为后续增加更多中间产物预留扩展空间

说明：
- 当前状态定义采用 TypedDict
- total=False 表示字段允许分阶段逐步出现，而非一开始全部具备
- 该设计与当前的多阶段 graph 流程相匹配
"""

from typing import Any, Dict, List, TypedDict


class ResearchState(TypedDict, total=False):
    """
    deep research workflow 的共享状态结构。

    字段说明：
    - question:
        用户输入的原始研究问题
    - search_queries:
        planner 生成的初始搜索子问题列表
    - search_results:
        search 节点返回的搜索结果列表
    - page_results:
        read_pages 节点读取页面后的结果列表
    - evidence_cards:
        build_evidence_cards 节点生成的结构化证据卡列表
    - needs_retry:
        judge_search_quality 节点输出的补搜标记
    - retry_count:
        当前补搜轮次计数
    - rewritten_queries:
        rewrite_query 节点生成的补搜 query 列表
    - notes:
        synthesize_evidence 节点生成的综合笔记
    - final_report:
        report 节点生成的最终报告文本
    """

    # 用户输入的原始研究问题。
    question: str

    # planner 生成的初始搜索子问题列表。
    search_queries: List[str]

    # search 节点返回的搜索结果。
    # 每条结果通常包含：
    # - title
    # - url
    # - snippet
    # - query
    # 以及来源评分相关字段。
    search_results: List[Dict[str, Any]]

    # read_pages 节点读取页面后的结果。
    # 每条结果通常包含：
    # - 原始搜索结果字段
    # - page_content
    # - page_summary
    page_results: List[Dict[str, Any]]

    # build_evidence_cards 节点生成的结构化证据卡。
    # 每条证据卡通常包含：
    # - sub_question
    # - claim
    # - evidence
    # - source_url
    # - source_title
    # - source_type
    evidence_cards: List[Dict[str, Any]]

    # judge_search_quality 节点输出的补搜标记。
    needs_retry: bool

    # 当前补搜轮次。
    retry_count: int

    # rewrite_query 节点生成的补搜 query。
    rewritten_queries: List[str]

    # synthesize_evidence 节点输出的综合笔记。
    notes: List[str]

    # report 节点生成的最终报告文本。
    final_report: str