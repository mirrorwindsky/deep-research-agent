# graphs/research_graph.py

"""
Deep Research workflow 图编排模块。

模块职责：
1. 定义 deep research workflow 的节点集合
2. 定义各节点之间的执行顺序
3. 构建并编译可执行的 LangGraph 对象

设计目标：
1. 将 workflow 编排逻辑集中管理
2. 将项目主链从“单轮搜索总结”升级为“搜索 -> 阅读 -> 证据 -> 判断 -> 补搜 -> 报告”
3. 为后续扩展更复杂的分支与循环保留结构基础

当前结构：
START
  -> plan
  -> search
  -> read_pages
  -> build_evidence_cards
  -> judge_search_quality
      -> rewrite_query
      -> synthesize_evidence
  -> report
  -> END

说明：
- 当前版本最多允许一次补搜
- 第一次 judge 若判定质量不足，则进入 rewrite_query 后再次回到 search
- 第二轮 judge 后应直接进入 synthesize_evidence，不再无限循环
"""

from langgraph.graph import END, START, StateGraph

from agents.researcher import (
    build_evidence_cards_node,
    judge_search_quality_node,
    plan_node,
    read_pages_node,
    report_node,
    rewrite_query_node,
    search_node,
    synthesize_evidence_node,
)
from schemas.state import ResearchState


def _route_after_judge(state: ResearchState) -> str:
    """
    根据搜索质量判断结果决定后续流向。

    路由规则：
    - 若 needs_retry 为 True，则进入 rewrite_query
    - 否则进入 synthesize_evidence
    """
    if state.get("needs_retry", False):
        return "rewrite_query"
    return "synthesize_evidence"


def build_research_graph():
    """
    构建并编译整个 deep research workflow 的 LangGraph。

    返回：
    - 编译后的 LangGraph 可执行对象

    设计说明：
    - 节点注册与边定义显式展开，便于观察整体流程
    - 条件分支仅保留一处：judge_search_quality 之后的补搜判断
    - 当前阶段先实现最小闭环版本，避免过早增加复杂度
    """
    graph = StateGraph(ResearchState)

    # 注册 workflow 节点。
    graph.add_node("plan", plan_node)
    graph.add_node("search", search_node)
    graph.add_node("read_pages", read_pages_node)
    graph.add_node("build_evidence_cards", build_evidence_cards_node)
    graph.add_node("judge_search_quality", judge_search_quality_node)
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("synthesize_evidence", synthesize_evidence_node)
    graph.add_node("report", report_node)

    # 定义主链顺序。
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "read_pages")
    graph.add_edge("read_pages", "build_evidence_cards")
    graph.add_edge("build_evidence_cards", "judge_search_quality")

    # 在搜索质量判断后，根据 needs_retry 决定流向。
    graph.add_conditional_edges(
        "judge_search_quality",
        _route_after_judge,
        {
            "rewrite_query": "rewrite_query",
            "synthesize_evidence": "synthesize_evidence",
        },
    )

    # 补搜分支。
    graph.add_edge("rewrite_query", "search")

    # 报告生成分支。
    graph.add_edge("synthesize_evidence", "report")
    graph.add_edge("report", END)

    return graph.compile()