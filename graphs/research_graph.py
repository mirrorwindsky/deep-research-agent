from langgraph.graph import StateGraph, START, END

from schemas.state import ResearchState
from agents.researcher import (
    plan_node,
    search_node,
    synthesize_node,
    report_node,
)


def build_research_graph():
    """
    构建并编译整个 research workflow 的 LangGraph。

    当前第一阶段采用最简单的线性流程：
    START -> plan -> search -> synthesize -> report -> END
    """
    graph = StateGraph(ResearchState)

    # 注册节点
    graph.add_node("plan", plan_node)
    graph.add_node("search", search_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("report", report_node)

    # 定义节点之间的执行顺序
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "synthesize")
    graph.add_edge("synthesize", "report")
    graph.add_edge("report", END)

    # 编译 graph，返回可执行对象
    return graph.compile()