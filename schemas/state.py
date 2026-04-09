from typing import TypedDict, List, Dict, Any


class ResearchState(TypedDict, total=False):
    """
    ResearchState 是整个研究流程中的“共享状态”。

    你可以把它理解成：
    所有节点（plan / search / synthesize / report）共同读写的一份任务数据。

    total=False 的意思是：
    这些字段不要求一开始全部存在。
    例如：
    - 刚开始只有 question
    - plan 结束后才有 search_queries
    - search 结束后才有 search_results
    """

    # 用户输入的原始研究问题
    question: str

    # plan 节点生成出的搜索子问题列表
    # 例如：
    # [
    #   "LangGraph 的核心设计目标",
    #   "普通函数调用 agent 的典型结构",
    #   "LangGraph 与函数调用 agent 的区别"
    # ]
    search_queries: List[str]

    # search 节点收集到的搜索结果
    # 每一项通常是一个字典，里面包含 title / url / snippet / query
    search_results: List[Dict[str, Any]]

    # synthesize 节点提炼出的研究笔记
    # 例如：
    # [
    #   "LangGraph 更强调状态流转和节点编排",
    #   "普通函数调用 agent 通常结构更轻量"
    # ]
    notes: List[str]

    # report 节点生成出的最终报告文本
    final_report: str