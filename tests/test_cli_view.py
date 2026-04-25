"""
CLI runtime view 回归测试。

这些测试保护终端展示层的稳定格式：
- debug_trace 应转换为紧凑步骤行
- run_summary 应转换为可读摘要行
- CliRuntimeView 应能通过注入 print 函数捕获输出
"""

import unittest

from services.cli_view import (
    CliRuntimeView,
    configure_utf8_console,
    format_artifact_lines,
    format_run_record_line,
    format_step_line,
    format_step_lines,
    format_summary_lines,
)


class CliRuntimeViewTests(unittest.TestCase):
    def test_format_step_line_includes_core_metrics(self):
        line = format_step_line({
            "step": "read_pages",
            "status": "completed",
            "page_result_count": 5,
            "page_read_success_count": 4,
            "page_read_fallback_count": 1,
        })

        self.assertIn("OK", line)
        self.assertIn("read_pages", line)
        self.assertIn("5 pages", line)
        self.assertIn("1 fallback", line)

    def test_format_step_line_reports_validation_status(self):
        line = format_step_line({
            "step": "report",
            "status": "completed",
            "final_report_length": 1200,
            "report_validation_valid": True,
        })

        self.assertIn("report", line)
        self.assertIn("1200 chars", line)
        self.assertIn("validation passed", line)

    def test_format_summary_lines_includes_run_metrics(self):
        lines = format_summary_lines({
            "run_id": "run-test",
            "status": "completed",
            "search_queries": 2,
            "search_results": 8,
            "page_results": 5,
            "page_read_success_count": 4,
            "page_read_fallback_count": 1,
            "evidence_cards": 5,
            "needs_retry": False,
            "retry_count": 0,
            "notes": 4,
            "final_report_length": 1000,
            "report_validation_valid": True,
        })

        self.assertIn("run_id: run-test", lines)
        self.assertIn("page_results: 5 (success=4, fallback=1)", lines)
        self.assertIn("needs_retry: no", lines)
        self.assertIn("report_validation_valid: yes", lines)

    def test_format_artifact_lines_uses_latest_artifacts(self):
        lines = format_artifact_lines({
            "latest_artifacts": {
                "state": "debug_data/latest_run_state.json",
                "evidence_cards": "debug_data/latest_evidence_cards.json",
                "report": "debug_data/latest_report.md",
                "summary": "debug_data/latest_run_summary.json",
            }
        })

        self.assertEqual(lines[0], "state: debug_data/latest_run_state.json")
        self.assertIn("report: debug_data/latest_report.md", lines)

    def test_format_run_record_line_includes_history_metrics(self):
        line = format_run_record_line({
            "run_id": "run-test",
            "status": "completed",
            "evidence_cards": 5,
            "page_read_fallback_count": 1,
            "needs_retry": False,
            "report_validation_valid": True,
            "question": "这是一个很长的研究问题，用于验证 run history 列表展示会截断问题文本。",
        })

        self.assertIn("run-test", line)
        self.assertIn("cards=5", line)
        self.assertIn("fallback=1", line)
        self.assertIn("validation=yes", line)

    def test_view_print_run_result_uses_injected_printer(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)
        summary = {
            "run_id": "run-test",
            "status": "completed",
            "debug_trace": [
                {
                    "step": "search",
                    "status": "completed",
                    "search_result_count": 3,
                }
            ],
            "report_validation_valid": True,
        }

        view.print_run_result(
            summary=summary,
            report="最终报告",
            include_artifacts=False,
        )

        output = "\n".join(printed)
        self.assertIn("Workflow Steps", output)
        self.assertIn("OK  search", output)
        self.assertIn("Final Report", output)
        self.assertIn("最终报告", output)
        self.assertIn("Run Summary", output)

    def test_view_can_hide_steps_after_streaming_report(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)

        view.print_run_result(
            summary={
                "run_id": "run-test",
                "status": "completed",
                "debug_trace": [
                    {
                        "step": "search",
                        "status": "completed",
                        "search_result_count": 3,
                    }
                ],
            },
            report="最终报告",
            include_artifacts=False,
            include_report=False,
            include_steps=False,
        )

        output = "\n".join(printed)
        self.assertNotIn("Workflow Steps", output)
        self.assertNotIn("Final Report", output)
        self.assertIn("Run Summary", output)

    def test_view_print_run_history_handles_empty_and_records(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)

        view.print_run_history([])
        self.assertIn("暂无 run history。", "\n".join(printed))

        printed.clear()
        view.print_run_history([
            {
                "run_id": "run-test",
                "status": "completed",
                "evidence_cards": 2,
                "page_read_fallback_count": 0,
                "report_validation_valid": True,
                "question": "测试问题",
            }
        ])

        output = "\n".join(printed)
        self.assertIn("Run History", output)
        self.assertIn("run-test", output)
        self.assertIn("测试问题", output)

    def test_view_print_history_run_outputs_report_and_summary(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)

        view.print_history_run(
            summary={
                "run_id": "run-test",
                "status": "completed",
                "report_validation_valid": True,
            },
            report="# 历史报告",
        )

        output = "\n".join(printed)
        self.assertIn("Final Report", output)
        self.assertIn("# 历史报告", output)
        self.assertIn("Run Summary", output)

    def test_view_report_stream_callback_prints_header_once(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)

        view.on_report_stream("第一段")
        view.on_report_stream("第二段")
        view.print_report_stream_end()

        output = "\n".join(printed)
        self.assertEqual(printed.count("Final Report"), 1)
        self.assertTrue(view.report_stream_started)
        self.assertIn("Research completed. Streaming final report.", output)
        self.assertIn("-" * 72, output)
        self.assertIn("第一段", output)
        self.assertIn("第二段", output)

    def test_view_step_callbacks_print_event_stream(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)

        view.on_step_start("search")
        view.on_step_complete({
            "step": "search",
            "status": "completed",
            "search_result_count": 12,
        })

        output = "\n".join(printed)
        self.assertIn("检索候选来源", output)
        self.assertIn("done search: 12 results", output)

    def test_view_skips_report_done_line_after_streaming_report(self):
        printed = []
        view = CliRuntimeView(print_func=printed.append)
        view.report_stream_started = True

        view.on_step_complete({
            "step": "report",
            "status": "completed",
            "final_report_length": 1200,
            "report_validation_valid": True,
        })

        self.assertEqual(printed, [])

    def test_format_step_lines_reads_summary_trace(self):
        lines = format_step_lines({
            "debug_trace": [
                {
                    "step": "plan",
                    "status": "completed",
                    "search_query_count": 3,
                }
            ]
        })

        self.assertEqual(len(lines), 1)
        self.assertIn("3 queries", lines[0])

    def test_configure_utf8_console_is_safe_to_call(self):
        configure_utf8_console()


if __name__ == "__main__":
    unittest.main()
