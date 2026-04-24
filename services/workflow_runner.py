"""
Research workflow 运行编排模块。

模块职责：
1. 定义 Deep Research Agent v2 的标准节点执行顺序
2. 使用 ResearchRuntime 执行节点并记录运行轨迹
3. 为 main.py 与 debug_run.py 提供同一套 full v2 workflow 入口

设计目标：
1. 避免多个入口重复维护节点顺序
2. 保持 graph/node 业务逻辑不变，仅统一运行编排方式
3. 让正式主入口和 debug 入口都能获得 run_id、debug_trace、run_summary 和 report_validation

当前限制：
- 当前编排仍是同步、单进程执行
- 当前最多只支持一轮 query rewrite 补搜
- 当前 artifact 保存策略由调用方决定
"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional

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
from services.runtime import ResearchRuntime


StepCallback = Optional[Callable[[str], None]]


def _run_step(
    runtime: ResearchRuntime,
    state: Dict[str, Any],
    step_name: str,
    node_func,
    on_step_start: StepCallback = None,
) -> None:
    """
    执行一个节点，并在需要时通知调用方当前 step 名称。

    设计原因：
    - debug_run.py 需要在终端显示正在运行的节点
    - main.py 不需要逐步输出，但仍复用同一套编排逻辑
    """
    if on_step_start:
        on_step_start(step_name)

    runtime.run_step(state, step_name, node_func)


def run_full_v2_workflow(
    question: str,
    *,
    artifact_dir: str | Path = "debug_data",
    save_artifacts: bool = True,
    on_step_start: StepCallback = None,
) -> Dict[str, Any]:
    """
    执行完整 Deep Research Agent v2 workflow。

    流程：
    plan -> search -> read_pages -> build_evidence_cards -> judge_search_quality
    -> 可选 rewrite/search/read/evidence/judge 补搜轮次
    -> synthesize_evidence -> report

    输入：
    - question: 原始研究问题
    - artifact_dir: 运行产物保存目录
    - save_artifacts: 是否保存 latest_* artifacts
    - on_step_start: 可选 step 开始回调，用于 debug 入口打印进度

    输出：
    - state: 完整 workflow state
    - summary: runtime 生成的 run summary
    - runtime: 本次运行使用的 ResearchRuntime 实例
    """
    runtime = ResearchRuntime(question=question, artifact_dir=artifact_dir)
    state = runtime.initial_state()

    _run_step(runtime, state, "plan", plan_node, on_step_start)
    _run_step(runtime, state, "search", search_node, on_step_start)
    _run_step(runtime, state, "read_pages", read_pages_node, on_step_start)
    _run_step(runtime, state, "build_evidence_cards", build_evidence_cards_node, on_step_start)
    _run_step(runtime, state, "judge_search_quality", judge_search_quality_node, on_step_start)

    if state.get("needs_retry", False):
        _run_step(runtime, state, "rewrite_query", rewrite_query_node, on_step_start)
        _run_step(runtime, state, "retry_search", search_node, on_step_start)
        _run_step(runtime, state, "retry_read_pages", read_pages_node, on_step_start)
        _run_step(runtime, state, "retry_build_evidence_cards", build_evidence_cards_node, on_step_start)
        _run_step(runtime, state, "retry_judge_search_quality", judge_search_quality_node, on_step_start)

    _run_step(runtime, state, "synthesize_evidence", synthesize_evidence_node, on_step_start)
    _run_step(runtime, state, "report", report_node, on_step_start)

    if save_artifacts:
        summary = runtime.save_artifacts(state)
    else:
        summary = runtime.build_summary(state)
        state["run_summary"] = summary

    return {
        "state": state,
        "summary": summary,
        "runtime": runtime,
    }
