"""
Query rewriter 回归测试。

这些测试保护 evidence_gaps 到补搜 query 的映射：
- 实现细节缺口应生成 implementation / code / CRD / controller 方向 query
- 对比缺口应生成 comparison / vs / tradeoff 方向 query
- fallback evidence 过多时应偏向 official docs guide reference
- 无明确缺口时应保留稳定官方文档兜底 query
"""

import unittest

from services.query_rewriter import build_rewritten_queries


class QueryRewriterTests(unittest.TestCase):
    def test_implementation_gap_generates_detail_queries(self):
        queries = build_rewritten_queries(
            question="如何实现 Kubernetes Operator？",
            original_queries=["Kubernetes Operator implementation"],
            evidence_gaps=["implementation_detail_missing"],
            max_queries=5,
        )

        self.assertEqual(len(queries), 2)
        self.assertIn("implementation guide tutorial example code official docs", queries[0])
        self.assertIn("controller CRD configuration example", queries[1])

    def test_comparison_gap_generates_comparison_queries(self):
        queries = build_rewritten_queries(
            question="Operator vs Helm",
            original_queries=["Kubernetes Operator vs Helm"],
            evidence_gaps=["comparison_missing"],
            max_queries=5,
        )

        self.assertEqual(len(queries), 2)
        self.assertIn("comparison vs difference tradeoff", queries[0])
        self.assertIn("alternatives comparison official docs", queries[1])

    def test_fallback_gap_biases_toward_official_docs(self):
        queries = build_rewritten_queries(
            question="Kubernetes Operator",
            original_queries=["Kubernetes Operator"],
            evidence_gaps=["fallback_evidence_too_many"],
            max_queries=5,
        )

        self.assertEqual(queries, ["Kubernetes Operator official docs guide reference"])

    def test_combined_gaps_are_deduplicated_and_limited(self):
        queries = build_rewritten_queries(
            question="Kubernetes Operator",
            original_queries=["Kubernetes Operator"],
            evidence_gaps=[
                "implementation_detail_missing",
                "comparison_missing",
                "official_source_missing",
                "example_source_missing",
            ],
            max_queries=3,
        )

        self.assertEqual(len(queries), 3)
        self.assertIn("implementation guide", queries[0])
        self.assertIn("controller CRD", queries[1])
        self.assertIn("comparison vs", queries[2])

    def test_no_gap_uses_official_documentation_fallback(self):
        queries = build_rewritten_queries(
            question="Kubernetes Operator",
            original_queries=["query one", "query two"],
            evidence_gaps=[],
            max_queries=5,
        )

        self.assertEqual(
            queries,
            [
                "query one official documentation",
                "query two official documentation",
            ],
        )


if __name__ == "__main__":
    unittest.main()
