"""
Runtime 回归测试。

这些测试保护轻量运行时的工程化能力：
- 节点执行结果应合并回 state
- debug_trace 应记录关键数量指标
- run summary 应反映页面读取、报告长度和引用校验状态
- 节点失败时应记录失败 trace 并继续抛出异常
"""

import unittest

from services.runtime import ResearchRuntime


class ResearchRuntimeTests(unittest.TestCase):
    def test_run_step_merges_result_and_records_trace(self):
        runtime = ResearchRuntime(
            question="测试问题",
            run_id="run-test",
        )
        state = runtime.initial_state()

        def node_func(current_state):
            self.assertEqual(current_state["question"], "测试问题")
            return {
                "search_results": [
                    {"title": "A"},
                    {"title": "B"},
                ]
            }

        result = runtime.run_step(state, "search", node_func)

        self.assertEqual(len(result["search_results"]), 2)
        self.assertEqual(len(state["search_results"]), 2)
        self.assertEqual(state["debug_trace"][0]["step"], "search")
        self.assertEqual(state["debug_trace"][0]["status"], "completed")
        self.assertEqual(state["debug_trace"][0]["search_result_count"], 2)

    def test_build_summary_includes_runtime_metrics(self):
        runtime = ResearchRuntime(
            question="测试问题",
            run_id="run-summary",
        )
        state = runtime.initial_state()
        state.update({
            "search_queries": ["q1", "q2"],
            "search_results": [{"url": "https://example.com"}],
            "page_results": [
                {"read_success": True},
                {"read_success": False},
            ],
            "evidence_cards": [{}, {}, {}],
            "needs_retry": False,
            "retry_count": 0,
            "notes": ["note"],
            "final_report": "report text",
            "report_validation": {"valid": True},
        })

        summary = runtime.build_summary(state)

        self.assertEqual(summary["run_id"], "run-summary")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["search_queries"], 2)
        self.assertEqual(summary["page_read_success_count"], 1)
        self.assertEqual(summary["page_read_fallback_count"], 1)
        self.assertEqual(summary["evidence_cards"], 3)
        self.assertTrue(summary["report_validation_valid"])

    def test_save_artifacts_writes_latest_files(self):
        class MemoryRuntime(ResearchRuntime):
            """
            使用内存记录 artifact 写入，避免单元测试依赖真实文件系统权限。
            """

            def __init__(self):
                super().__init__(question="测试问题", run_id="run-artifact")
                self.saved_json = {}
                self.saved_text = {}

            def _save_json(self, filename, data):
                self.saved_json[filename] = data

            def _save_text(self, filename, content):
                self.saved_text[filename] = content

            def _load_json(self, filename, default):
                return self.saved_json.get(filename, default)

        runtime = MemoryRuntime()
        state = runtime.initial_state()
        state.update({
            "evidence_cards": [{"claim": "sample"}],
            "final_report": "# 报告",
            "report_validation": {"valid": True},
        })

        summary = runtime.save_artifacts(state)

        self.assertIn("latest_run_state.json", runtime.saved_json)
        self.assertIn("latest_evidence_cards.json", runtime.saved_json)
        self.assertIn("latest_run_summary.json", runtime.saved_json)
        self.assertIn("runs/run-artifact/state.json", runtime.saved_json)
        self.assertIn("runs/run-artifact/evidence_cards.json", runtime.saved_json)
        self.assertIn("runs/run-artifact/summary.json", runtime.saved_json)
        self.assertIn("runs/index.json", runtime.saved_json)
        self.assertEqual(runtime.saved_text["latest_report.md"], "# 报告")
        self.assertEqual(runtime.saved_text["runs/run-artifact/report.md"], "# 报告")
        self.assertEqual(summary["run_id"], "run-artifact")
        self.assertEqual(runtime.saved_json["latest_run_summary.json"]["run_id"], "run-artifact")
        self.assertEqual(runtime.saved_json["runs/run-artifact/summary.json"]["run_id"], "run-artifact")
        self.assertEqual(runtime.saved_json["runs/index.json"][0]["run_id"], "run-artifact")
        self.assertTrue(runtime.saved_json["latest_run_summary.json"]["report_validation_valid"])

    def test_run_index_keeps_latest_twenty_records(self):
        class MemoryRuntime(ResearchRuntime):
            """
            使用内存索引验证 run history 裁剪策略。
            """

            def __init__(self):
                super().__init__(question="测试问题", run_id="run-current")
                self.saved_json = {
                    "runs/index.json": [
                        {
                            "run_id": f"run-old-{idx}",
                            "started_at": f"2026-01-{idx:02d}T00:00:00+00:00",
                        }
                        for idx in range(1, 25)
                    ]
                }
                self.saved_text = {}

            def _save_json(self, filename, data):
                self.saved_json[filename] = data

            def _save_text(self, filename, content):
                self.saved_text[filename] = content

            def _load_json(self, filename, default):
                return self.saved_json.get(filename, default)

        runtime = MemoryRuntime()
        state = runtime.initial_state()
        state.update({
            "final_report": "report",
            "report_validation": {"valid": True},
        })

        runtime.save_artifacts(state)

        records = runtime.saved_json["runs/index.json"]
        self.assertEqual(len(records), 20)
        self.assertEqual(records[0]["run_id"], "run-current")
        self.assertNotIn("run-old-1", {item["run_id"] for item in records})

    def test_run_step_records_failed_trace_and_reraises(self):
        runtime = ResearchRuntime(
            question="测试问题",
            run_id="run-failed",
        )
        state = runtime.initial_state()

        def failing_node(_state):
            raise RuntimeError("node failed")

        with self.assertRaises(RuntimeError):
            runtime.run_step(state, "failing_step", failing_node)

        self.assertEqual(runtime.status, "failed")
        self.assertEqual(state["debug_trace"][0]["step"], "failing_step")
        self.assertEqual(state["debug_trace"][0]["status"], "failed")
        self.assertIn("node failed", state["debug_trace"][0]["error"])


if __name__ == "__main__":
    unittest.main()
