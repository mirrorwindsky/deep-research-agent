"""
Report builder 回归测试。

这些测试保护 citation-grounded report 的材料构建逻辑：
- 候选引用来源应拥有稳定 source_id
- prompt 中的 evidence 应绑定到对应来源编号
- evidence cards 不可用时应回退到搜索结果来源
- 生成报告引用了编号但漏列参考来源时，应进行确定性补齐
"""

import unittest

from services.report_builder import (
    build_report_prompt,
    collect_unique_evidence_sources,
    ensure_referenced_sources_are_listed,
)


class ReportBuilderTests(unittest.TestCase):
    def test_report_prompt_contains_structured_evidence_and_source_limits(self):
        """
        验证 evidence cards 同时驱动 prompt 内容和候选来源收口。
        """
        evidence_cards = [
            {
                "sub_question": "Kubernetes Operator 是什么？",
                "claim": "Operators extend Kubernetes with custom resources.",
                "evidence": "Operators use custom resources and controllers to manage applications.",
                "source_title": "Operator pattern | Kubernetes",
                "source_url": "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                "domain": "kubernetes.io",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "evidence_source": "page_content",
                "read_success": True,
                "read_error": "",
                "status_code": 200,
            }
        ]

        result = build_report_prompt(
            question="Kubernetes Operator 是什么？",
            notes=["Operators automate application operations."],
            search_results=[],
            evidence_cards=evidence_cards,
        )

        prompt = result["prompt"]
        self.assertIn("Operators extend Kubernetes with custom resources.", prompt)
        self.assertIn("Operators use custom resources and controllers", prompt)
        self.assertIn("Operator pattern | Kubernetes", prompt)
        self.assertIn("https://kubernetes.io/docs/concepts/extend-kubernetes/operator/", prompt)
        self.assertIn("source_id: [1]", prompt)
        self.assertIn("[1] Operator pattern | Kubernetes", prompt)
        self.assertIn("evidence_source: page_content", prompt)
        self.assertEqual(len(result["unique_sources"]), 1)
        self.assertEqual(result["unique_sources"][0]["source_id"], 1)
        self.assertEqual(
            result["unique_sources"][0]["url"],
            "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
        )

    def test_failed_read_status_is_visible_in_report_prompt(self):
        evidence_cards = [
            {
                "sub_question": "How to implement an Operator?",
                "claim": "Operators require a controller reconciliation loop.",
                "evidence": "A controller watches resources and reconciles desired state.",
                "source_title": "Operator implementation guide",
                "source_url": "https://example.com/operator-guide",
                "domain": "example.com",
                "source_type": "community_article",
                "page_kind": "tutorial_page",
                "evidence_source": "snippet_fallback",
                "read_success": False,
                "read_error": "timeout",
                "status_code": None,
            }
        ]

        result = build_report_prompt(
            question="如何实现 Kubernetes Operator？",
            notes=[],
            search_results=[],
            evidence_cards=evidence_cards,
        )

        prompt = result["prompt"]
        self.assertIn("timeout", prompt)
        self.assertIn("evidence_source: snippet_fallback", prompt)
        self.assertIn("Operator implementation guide", prompt)
        self.assertIn("https://example.com/operator-guide", prompt)
        self.assertIn("[1] Operator implementation guide", prompt)

    def test_sources_fall_back_to_ranked_search_results_without_evidence(self):
        search_results = [
            {
                "title": "Official docs",
                "url": "https://docs.example.com/operator",
                "snippet": "Official reference.",
                "domain": "docs.example.com",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "source_score": 10,
                "query_fit_score": 2,
                "source_type_score": 5,
                "read_success": False,
                "read_error": "",
            },
            {
                "title": "Low score article",
                "url": "https://blog.example.com/operator",
                "snippet": "Blog post.",
                "domain": "blog.example.com",
                "source_type": "community_article",
                "page_kind": "tutorial_page",
                "source_score": 3,
                "query_fit_score": 1,
                "source_type_score": 2,
                "read_success": False,
                "read_error": "",
            },
        ]

        result = build_report_prompt(
            question="Kubernetes Operator 是什么？",
            notes=[],
            search_results=search_results,
            evidence_cards=[],
        )

        self.assertEqual(result["unique_sources"][0]["url"], "https://docs.example.com/operator")
        self.assertEqual(result["unique_sources"][0]["source_id"], 1)
        self.assertIn("Official docs", result["prompt"])
        self.assertIn("Low score article", result["prompt"])
        self.assertIn("[1] Official docs", result["prompt"])

    def test_evidence_sources_are_deduplicated_by_url(self):
        evidence_cards = [
            {
                "source_title": "Same source",
                "source_url": "https://example.com/a",
                "domain": "example.com",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "read_success": True,
                "evidence_source": "page_content",
            },
            {
                "source_title": "Same source duplicate",
                "source_url": "https://example.com/a",
                "domain": "example.com",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "read_success": True,
                "evidence_source": "page_content",
            },
        ]

        sources = collect_unique_evidence_sources(evidence_cards)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["title"], "Same source")
        self.assertEqual(sources[0]["evidence_source"], "page_content")

    def test_same_source_url_uses_same_source_id_in_evidence_prompt(self):
        """
        验证同一 URL 的多条 evidence 复用同一个 citation id。
        """
        evidence_cards = [
            {
                "sub_question": "Definition",
                "claim": "First claim.",
                "evidence": "First evidence.",
                "source_title": "Shared source",
                "source_url": "https://example.com/shared",
                "domain": "example.com",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "evidence_source": "page_content",
                "read_success": True,
                "status_code": 200,
            },
            {
                "sub_question": "Implementation",
                "claim": "Second claim.",
                "evidence": "Second evidence.",
                "source_title": "Shared source duplicate",
                "source_url": "https://example.com/shared",
                "domain": "example.com",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "evidence_source": "page_content",
                "read_success": True,
                "status_code": 200,
            },
        ]

        result = build_report_prompt(
            question="How does the feature work?",
            notes=[],
            search_results=[],
            evidence_cards=evidence_cards,
        )

        prompt = result["prompt"]
        self.assertEqual(len(result["unique_sources"]), 1)
        self.assertEqual(prompt.count("source_id: [1]"), 2)
        self.assertEqual(prompt.count("[1] Shared source\nURL:"), 1)

    def test_prompt_restricts_citations_to_candidate_source_ids(self):
        """
        验证 prompt 明确约束模型只能引用候选来源编号。
        """
        result = build_report_prompt(
            question="What is citation-grounded reporting?",
            notes=[],
            search_results=[
                {
                    "title": "Candidate source",
                    "url": "https://example.com/source",
                    "snippet": "Useful source.",
                    "domain": "example.com",
                    "source_type": "official_docs",
                    "page_kind": "docs_page",
                    "source_score": 10,
                    "query_fit_score": 2,
                    "source_type_score": 5,
                }
            ],
            evidence_cards=[],
        )

        prompt = result["prompt"]
        self.assertIn("只能引用“优先引用来源（已筛选）”中列出的编号", prompt)
        self.assertIn("不得引用未列出的编号", prompt)
        self.assertIn("关键结论、分问题分析和参考来源必须使用 [1]、[2] 这类来源编号", prompt)
        self.assertIn("引用过的每一个编号，都必须在“参考来源”中列出对应来源", prompt)

    def test_missing_cited_candidate_source_is_appended_to_references(self):
        """
        验证正文已引用但参考来源漏列时，会补齐对应候选来源。
        """
        report = """# 核心结论
结论来自官方文档 [1]，但局限性提到了兜底来源 [3]。

# 参考来源

[1] Official docs
链接: https://example.com/docs
"""
        unique_sources = [
            {
                "source_id": 1,
                "title": "Official docs",
                "url": "https://example.com/docs",
            },
            {
                "source_id": 3,
                "title": "Fallback source",
                "url": "https://example.com/fallback",
            },
        ]

        fixed_report = ensure_referenced_sources_are_listed(
            report=report,
            unique_sources=unique_sources,
        )

        self.assertIn("[1] Official docs", fixed_report)
        self.assertIn("[3] Fallback source", fixed_report)
        self.assertIn("链接: https://example.com/fallback", fixed_report)

    def test_unknown_citation_id_is_not_appended(self):
        """
        验证后处理不会为未知编号编造参考来源。
        """
        report = """# 核心结论
结论误引了未知来源 [9]。

# 参考来源

[1] Official docs
链接: https://example.com/docs
"""

        fixed_report = ensure_referenced_sources_are_listed(
            report=report,
            unique_sources=[
                {
                    "source_id": 1,
                    "title": "Official docs",
                    "url": "https://example.com/docs",
                }
            ],
        )

        self.assertNotIn("[9]", fixed_report.split("# 参考来源", 1)[1])


if __name__ == "__main__":
    unittest.main()
