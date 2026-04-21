import unittest

from services.report_builder import build_report_prompt, collect_unique_evidence_sources


class ReportBuilderTests(unittest.TestCase):
    def test_report_prompt_contains_structured_evidence_and_source_limits(self):
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
        self.assertIn("evidence_source: page_content", prompt)
        self.assertEqual(len(result["unique_sources"]), 1)
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
        self.assertIn("Official docs", result["prompt"])
        self.assertIn("Low score article", result["prompt"])

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


if __name__ == "__main__":
    unittest.main()
