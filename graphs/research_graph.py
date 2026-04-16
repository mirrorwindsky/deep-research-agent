# graphs/research_graph.py

"""
Research workflow 图编排模块。

模块职责：
1. 定义 research workflow 的节点集合
2. 定义各节点之间的执行顺序
3. 构建并编译可执行的 LangGraph 对象

设计目标：
1. 将 graph 编排逻辑从 main.py 中分离
2. 保持 workflow 结构清晰、集中、易修改
3. 为后续引入条件分支、循环补搜、子图等能力预留扩展入口

当前结构：
START -> plan -> search -> synthesize -> report -> END

说明：
- 当前版本采用第一阶段最简单的线性主链
- 该结构适合初期验证状态流转、节点边界与主链闭环
- 若后续需要加入 judge_search_quality / rewrite_query 等节点，
  可在本文件中统一扩展 graph 结构
"""

from langgraph.graph import END, START, StateGraph

from agents.researcher import (
    plan_node,
    report_node,
    search_node,
    synthesize_node,
)
from schemas.state import ResearchState


def build_research_graph():
    """
    构建并编译整个 research workflow 的 LangGraph。

    返回：
    - 编译后的 LangGraph 可执行对象

    当前流程：
    START -> plan -> search -> synthesize -> report -> END

    设计说明：
    - graph 构建逻辑集中在单独模块中，避免 main.py 承担编排职责
    - 节点注册与边定义显式展开，便于观察整体 workflow 结构
    - 当前阶段优先保持流程简单，降低调试与扩展成本
    """
    graph = StateGraph(ResearchState)

    # 注册 workflow 节点。
    # 节点名称用于 graph 内部连接，节点函数负责具体状态变换。
    graph.add_node("plan", plan_node)
    graph.add_node("search", search_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("report", report_node)

    # 定义节点之间的执行顺序。
    # 当前版本采用最小线性主链，不引入条件分支或循环。
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "synthesize")
    graph.add_edge("synthesize", "report")
    graph.add_edge("report", END)

    # 编译 graph，返回可执行对象。
    return graph.compile()