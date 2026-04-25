"""
CLI runtime 展示模块。

模块职责：
1. 为 Deep Research Agent v2 提供纯文本终端展示层。
2. 基于 runtime 的 step callback、debug_trace 和 run_summary 输出运行进度。
3. 让 main.py 与 debug_run.py 复用同一套展示逻辑。

设计目标：
1. 保持展示层轻量，不引入复杂 TUI 或额外依赖。
2. 不改变节点业务逻辑与 workflow 编排，只消费已有 runtime 数据。
3. 输出适合本地演示和复盘的事件流、报告与 artifact 路径。

当前限制：
- step 完成信息来自 runtime 的 debug_trace，因此可在节点结束后立即输出摘要。
- 当前只使用纯文本格式，后续可在不改业务层的前提下替换为 rich 等更强展示实现。
"""

from typing import Any, Callable, Dict, List


PrintFunc = Callable[[str], None]


STEP_LABELS = {
    "plan": "plan",
    "search": "search",
    "read_pages": "read_pages",
    "build_evidence_cards": "build_evidence",
    "judge_search_quality": "judge",
    "rewrite_query": "rewrite",
    "retry_search": "retry_search",
    "retry_read_pages": "retry_read",
    "retry_build_evidence_cards": "retry_evidence",
    "retry_judge_search_quality": "retry_judge",
    "synthesize_evidence": "synthesize",
    "report": "report",
}

STEP_MESSAGES = {
    "plan": "规划检索问题",
    "search": "检索候选来源",
    "read_pages": "读取页面正文",
    "build_evidence_cards": "构建证据卡",
    "judge_search_quality": "判断证据质量",
    "rewrite_query": "改写补搜 query",
    "retry_search": "执行补搜",
    "retry_read_pages": "读取补搜页面",
    "retry_build_evidence_cards": "构建补搜证据",
    "retry_judge_search_quality": "复查补搜证据",
    "synthesize_evidence": "综合证据笔记",
    "report": "生成最终报告",
}


def configure_utf8_console() -> None:
    """
    尽量将 Python 标准输出切换为 UTF-8。

    设计原因：
    - Windows 控制台默认编码可能是 GBK，遇到搜索标题中的 emoji 或特殊符号时会抛出
      UnicodeEncodeError。
    - CLI 展示层应优先保证真实链路能完整输出日志、流式报告和摘要。
    - reconfigure 不是所有 stdout/stderr 对象都支持，因此失败时静默跳过。
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def _format_bool(value: Any) -> str:
    """
    将布尔或空值转换为适合终端摘要的短文本。
    """
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _format_step_detail(step: Dict[str, Any]) -> str:
    """
    根据 runtime trace 中的指标生成单行 step 说明。

    输入：
    - step: runtime 写入 debug_trace 的单个节点摘要。

    输出：
    - 适合终端展示的简短指标文本。
    """
    parts: List[str] = []

    if "search_query_count" in step:
        parts.append(f"{step['search_query_count']} queries")
    if "search_result_count" in step:
        parts.append(f"{step['search_result_count']} results")
    if "page_result_count" in step:
        pages = step.get("page_result_count", 0)
        fallback = step.get("page_read_fallback_count", 0)
        parts.append(f"{pages} pages")
        parts.append(f"{fallback} fallback")
    if "evidence_card_count" in step:
        parts.append(f"{step['evidence_card_count']} cards")
    if "needs_retry" in step:
        retry_text = "retry needed" if step.get("needs_retry") else "pass"
        parts.append(retry_text)
    if step.get("evidence_gaps"):
        parts.append("gaps=" + ",".join(step.get("evidence_gaps", [])))
    if "rewritten_query_count" in step:
        parts.append(f"{step['rewritten_query_count']} rewritten")
    if "note_count" in step:
        parts.append(f"{step['note_count']} notes")
    if "final_report_length" in step:
        parts.append(f"{step['final_report_length']} chars")
    if "report_validation_valid" in step:
        validation = "validation passed" if step.get("report_validation_valid") else "validation failed"
        parts.append(validation)
    if step.get("error"):
        parts.append(step["error"])

    return ", ".join(parts) if parts else "-"


def format_step_line(step: Dict[str, Any], width: int = 20) -> str:
    """
    将单个 debug_trace step 格式化为终端表格行。

    输入：
    - step: runtime debug_trace 中的 step 字典。
    - width: step label 的固定宽度。

    输出：
    - 单行文本，例如 `OK search               12 results`。
    """
    status = step.get("status", "unknown")
    prefix = "OK" if status == "completed" else "FAIL" if status == "failed" else ".."
    name = STEP_LABELS.get(step.get("step", ""), step.get("step", "unknown"))
    detail = _format_step_detail(step)
    return f"{prefix:<4}{name:<{width}}{detail}"


def format_step_lines(summary: Dict[str, Any]) -> List[str]:
    """
    从 run summary 中提取并格式化完整步骤表。
    """
    trace = summary.get("debug_trace", [])
    return [format_step_line(step) for step in trace]


def format_summary_lines(summary: Dict[str, Any]) -> List[str]:
    """
    将 run_summary 转换为稳定的终端摘要行。
    """
    return [
        f"run_id: {summary.get('run_id', '')}",
        f"status: {summary.get('status', '')}",
        f"search_queries: {summary.get('search_queries', 0)}",
        f"search_results: {summary.get('search_results', 0)}",
        (
            "page_results: "
            f"{summary.get('page_results', 0)} "
            f"(success={summary.get('page_read_success_count', 0)}, "
            f"fallback={summary.get('page_read_fallback_count', 0)})"
        ),
        f"evidence_cards: {summary.get('evidence_cards', 0)}",
        f"needs_retry: {_format_bool(summary.get('needs_retry'))}",
        f"retry_count: {summary.get('retry_count', 0)}",
        f"notes: {summary.get('notes', 0)}",
        f"final_report_length: {summary.get('final_report_length', 0)}",
        f"report_validation_valid: {_format_bool(summary.get('report_validation_valid'))}",
    ]


def format_artifact_lines(summary: Dict[str, Any]) -> List[str]:
    """
    从 run summary 中提取 latest artifact 路径。
    """
    artifacts = summary.get("latest_artifacts", {})
    ordered_keys = ["state", "evidence_cards", "report", "summary"]
    return [
        f"{key}: {artifacts[key]}"
        for key in ordered_keys
        if artifacts.get(key)
    ]


def _truncate_text(value: str, max_chars: int) -> str:
    """
    将长文本截断为适合终端列表展示的宽度。
    """
    text = (value or "").replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def format_run_record_line(record: Dict[str, Any]) -> str:
    """
    将 runs/index.json 中的一条记录格式化为列表行。
    """
    validation = _format_bool(record.get("report_validation_valid"))
    retry = "retry" if record.get("needs_retry") else "no-retry"
    fallback = record.get("page_read_fallback_count", 0)
    question = _truncate_text(record.get("question", ""), 56)

    return (
        f"{record.get('run_id', ''):<22} "
        f"{record.get('status', ''):<10} "
        f"cards={record.get('evidence_cards', 0):<3} "
        f"fallback={fallback:<2} "
        f"validation={validation:<7} "
        f"{retry:<8} "
        f"{question}"
    )


class CliRuntimeView:
    """
    Deep Research Agent v2 的纯文本终端视图。

    实例通过 print_func 注入输出函数，便于单元测试捕获输出，也便于后续替换为其他
    终端渲染实现。
    """

    def __init__(self, print_func: PrintFunc = print):
        self.print_func = print_func
        self.report_stream_started = False

    def print_header(self, question: str) -> None:
        """
        输出一次 research run 的标题与问题。
        """
        self.print_func("")
        self.print_func("Deep Research Agent v2")
        self.print_func(f"Question: {question}")
        self.print_func("")
        self.print_func("Research progress")

    def on_step_start(self, step_name: str) -> None:
        """
        workflow_runner 的 on_step_start 回调。
        """
        label = STEP_LABELS.get(step_name, step_name)
        message = STEP_MESSAGES.get(step_name, "执行 workflow 节点")
        self.print_func(f"- {message} ({label})")

    def on_step_complete(self, step: Dict[str, Any]) -> None:
        """
        workflow_runner 的 step 完成回调。
        """
        if step.get("step") == "report" and self.report_stream_started:
            return

        status = step.get("status", "unknown")
        label = STEP_LABELS.get(step.get("step", ""), step.get("step", "unknown"))
        detail = _format_step_detail(step)

        if status == "completed":
            self.print_func(f"  done {label}: {detail}")
        elif status == "failed":
            self.print_func(f"  failed {label}: {detail}")
        else:
            self.print_func(f"  {status} {label}: {detail}")

    def print_steps(self, summary: Dict[str, Any]) -> None:
        """
        基于 debug_trace 输出完整步骤表。
        """
        self.print_func("")
        self.print_func("Workflow Steps")
        for line in format_step_lines(summary):
            self.print_func(line)

    def print_summary(self, summary: Dict[str, Any]) -> None:
        """
        输出结构化运行摘要。
        """
        self.print_func("")
        self.print_func("Run Summary")
        for line in format_summary_lines(summary):
            self.print_func(line)

    def print_artifacts(self, summary: Dict[str, Any]) -> None:
        """
        输出 latest artifact 路径，便于快速打开最近一次运行结果。
        """
        lines = format_artifact_lines(summary)
        if not lines:
            return

        self.print_func("")
        self.print_func("Artifacts")
        for line in lines:
            self.print_func(line)

    def print_run_history(self, records: List[Dict[str, Any]]) -> None:
        """
        输出最近 run 列表。
        """
        self.print_func("")
        self.print_func("Run History")

        if not records:
            self.print_func("暂无 run history。")
            return

        self.print_func(
            f"{'run_id':<22} {'status':<10} {'cards':<9} "
            f"{'fallback':<10} {'validation':<18} question"
        )
        self.print_func("-" * 100)

        for record in records:
            self.print_func(format_run_record_line(record))

    def print_history_run(self, summary: Dict[str, Any], report: str) -> None:
        """
        输出历史 run 的报告与摘要。
        """
        if not summary and not report:
            self.print_func("未找到指定 run。")
            return

        self.print_report(report)
        if summary:
            self.print_summary(summary)

    def print_report(self, report: str) -> None:
        """
        输出最终研究报告。
        """
        self.print_func("")
        self.print_func("Final Report")
        self.print_func("")
        self.print_func(report or "未生成报告")

    def print_report_stream_start(self) -> None:
        """
        输出流式报告区域标题。
        """
        self.print_func("")
        self.print_func("Research completed. Streaming final report.")
        self.print_func("")
        self.print_func("-" * 72)
        self.print_func("")
        self.print_func("Final Report")
        self.print_func("")
        self.report_stream_started = True

    def print_report_chunk(self, chunk: str) -> None:
        """
        输出最终报告的一个流式文本片段。

        设计说明：
        - 使用 end="" 保持模型产出的换行与段落结构。
        - print_func 若不是内置 print，则回退为普通追加，便于单元测试。
        """
        try:
            self.print_func(chunk, end="")
        except TypeError:
            self.print_func(chunk)

    def print_report_stream_end(self) -> None:
        """
        结束流式报告区域，并补一个换行，避免后续摘要贴在报告末尾。
        """
        self.print_func("")

    def on_report_stream(self, chunk: str) -> None:
        """
        workflow_runner 的最终报告流式输出回调。
        """
        if not self.report_stream_started:
            self.print_report_stream_start()
        self.print_report_chunk(chunk)

    def print_run_result(
        self,
        *,
        summary: Dict[str, Any],
        report: str,
        include_artifacts: bool = True,
        include_report: bool = True,
        include_steps: bool = True,
    ) -> None:
        """
        输出 workflow 完成后的标准展示内容。

        输入：
        - summary: ResearchRuntime 生成的 run summary。
        - report: 最终研究报告文本。
        - include_artifacts: 是否输出 latest artifact 路径。
        """
        if include_steps:
            self.print_steps(summary)
        if include_report:
            self.print_report(report)
        self.print_summary(summary)
        if include_artifacts:
            self.print_artifacts(summary)
