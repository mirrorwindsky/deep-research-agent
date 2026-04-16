# schemas/state.py

"""
Research workflow 共享状态定义模块。

模块职责：
1. 定义整个 research workflow 中统一使用的状态结构
2. 为各节点之间的数据传递提供一致的数据契约
3. 明确主链各阶段会读写哪些核心字段

设计目标：
1. 避免节点之间以松散、无约束的方式传递数据
2. 使 graph 中的状态流转结构清晰可读
3. 为后续增加新状态字段提供统一入口

说明：
- 当前状态定义采用 TypedDict
- total=False 表示字段允许分阶段逐步出现，而非一开始全部具备
- 该设计与当前线性 workflow 高度契合：
  question -> search_queries -> search_results -> notes -> final_report
"""

from typing import Any, Dict, List, TypedDict


class ResearchState(TypedDict, total=False):
    """
    research workflow 的共享状态结构。

    字段说明：
    - question:
        用户输入的原始研究问题
    - search_queries:
        plan 节点生成的搜索子问题列表
    - search_results:
        search 节点收集并筛选后的搜索结果
    - notes:
        synthesize 节点提炼出的研究笔记
    - final_report:
        report 节点生成的最终报告文本

    设计说明：
    - total=False 允许状态字段分阶段逐步补充
    - 该特性非常适合 LangGraph 中“节点逐步丰富 state”的使用方式
    - 当前状态字段数量保持精简，优先支撑第一阶段主链闭环
    """

    # 用户输入的原始研究问题。
    # 整条 workflow 的起点字段。
    question: str

    # plan 节点生成出的搜索子问题列表。
    # 典型形式：
    # [
    #   "LangGraph 的核心设计目标",
    #   "ordinary function calling agent architecture",
    #   "LangGraph vs function calling agent differences"
    # ]
    search_queries: List[str]

    # search 节点收集到的搜索结果。
    # 每条结果通常包含：
    # - title
    # - url
    # - snippet
    # - query
    # 以及经过排序增强后补充的评分相关字段。
    search_results: List[Dict[str, Any]]

    # synthesize 节点提炼出的研究笔记。
    # 典型形式：
    # [
    #   "LangGraph 更强调显式状态流转与节点编排",
    #   "普通函数调用 agent 通常结构更轻量，但可控性较弱"
    # ]
    notes: List[str]

    # report 节点生成的最终报告文本。
    final_report: str