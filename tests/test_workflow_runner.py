"""
Workflow runner 回归测试。

这些测试保护 full v2 workflow 的节点编排顺序：
- 正常路径应从 plan 运行到 report
- 需要补搜时应执行 rewrite/search/read/evidence/judge 补搜轮次
- runner 应返回 state、summary 和 runtime
"""

import unittest
from unittest.mock import patch

from services.workflow_runner import run_full_v2_workflow


def _make_node(step_name, output):
    """
    构造可记录执行顺序的测试节点。
    """
    def node(state):
        state.setdefault("test_steps", []).append(step_name)
        return output

    return node


class WorkflowRunnerTests(unittest.TestCase):
    def test_full_v2_workflow_runs_without_retry(self):
        with (
            patch("services.workflow_runner.plan_node", _make_node("plan", {"search_queries": ["q"]})),
            patch("services.workflow_runner.search_node", _make_node("search", {"search_results": [{}]})),
            patch("services.workflow_runner.read_pages_node", _make_node("read_pages", {"page_results": []})),
            patch("services.workflow_runner.build_evidence_cards_node", _make_node("build_evidence_cards", {"evidence_cards": []})),
            patch("services.workflow_runner.judge_search_quality_node", _make_node("judge_search_quality", {"needs_retry": False})),
            patch("services.workflow_runner.synthesize_evidence_node", _make_node("synthesize_evidence", {"notes": []})),
            patch("services.workflow_runner.report_node", _make_node("report", {"final_report": "report", "report_validation": {"valid": True}})),
        ):
            result = run_full_v2_workflow(
                question="测试问题",
                save_artifacts=False,
            )

        state = result["state"]
        summary = result["summary"]

        self.assertEqual(
            state["test_steps"],
            [
                "plan",
                "search",
                "read_pages",
                "build_evidence_cards",
                "judge_search_quality",
                "synthesize_evidence",
                "report",
            ],
        )
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(summary["report_validation_valid"])
        self.assertIn("runtime", result)

    def test_full_v2_workflow_runs_retry_branch_when_needed(self):
        with (
            patch("services.workflow_runner.plan_node", _make_node("plan", {"search_queries": ["q"]})),
            patch("services.workflow_runner.search_node", _make_node("search", {"search_results": [{}]})),
            patch("services.workflow_runner.read_pages_node", _make_node("read_pages", {"page_results": []})),
            patch("services.workflow_runner.build_evidence_cards_node", _make_node("build_evidence_cards", {"evidence_cards": []})),
            patch(
                "services.workflow_runner.judge_search_quality_node",
                _make_node("judge_search_quality", {"needs_retry": True, "evidence_gaps": ["example_source_missing"]}),
            ),
            patch("services.workflow_runner.rewrite_query_node", _make_node("rewrite_query", {"rewritten_queries": ["rq"], "retry_count": 1})),
            patch("services.workflow_runner.synthesize_evidence_node", _make_node("synthesize_evidence", {"notes": []})),
            patch("services.workflow_runner.report_node", _make_node("report", {"final_report": "report", "report_validation": {"valid": True}})),
        ):
            result = run_full_v2_workflow(
                question="测试问题",
                save_artifacts=False,
            )

        state = result["state"]

        self.assertIn("rewrite_query", state["test_steps"])
        self.assertIn("search", state["test_steps"])
        self.assertIn("read_pages", state["test_steps"])
        self.assertIn("build_evidence_cards", state["test_steps"])
        self.assertEqual(state["retry_count"], 1)
        self.assertTrue(result["summary"]["report_validation_valid"])


if __name__ == "__main__":
    unittest.main()
