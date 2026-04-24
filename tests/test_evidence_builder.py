"""
Evidence builder 回归测试。

这些测试保护 page_result 到 evidence_card 的核心契约：
- page_content 应生成不受软换行破坏的句子级证据
- 页面读取失败时仍应生成低可靠性的 snippet fallback 证据卡
- 来源溯源与页面读取状态字段应继续传递给下游节点
"""

import unittest

from services.evidence_builder import build_evidence_cards_from_pages


class EvidenceBuilderTests(unittest.TestCase):
    def test_soft_wrapped_page_content_keeps_evidence_sentence_intact(self):
        """
        验证清洗后的页面正文可以生成可读的 evidence 句子。
        """
        page_results = [
            {
                "title": "Operator pattern | Kubernetes",
                "url": "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                "final_url": "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                "query": "Kubernetes Operator 工作原理",
                "snippet": "Operators are software extensions to Kubernetes.",
                "page_summary": (
                    "Operators are software extensions to Kubernetes that use custom resources "
                    "to manage applications."
                ),
                "page_content": (
                    "Operators are software extensions to Kubernetes\n"
                    "that make use of custom resources to manage applications and their components."
                ),
                "domain": "kubernetes.io",
                "source_type": "official_docs",
                "page_kind": "docs_page",
                "read_success": True,
                "read_error": "",
                "status_code": 200,
            }
        ]

        cards = build_evidence_cards_from_pages(
            question="Kubernetes Operator 是什么？",
            page_results=page_results,
        )

        self.assertGreaterEqual(len(cards), 1)
        first_card = cards[0]
        self.assertIn("Operators are software extensions", first_card["evidence"])
        self.assertIn("that make use of custom resources", first_card["evidence"])
        self.assertNotIn("\n", first_card["evidence"])
        self.assertEqual(first_card["evidence_source"], "page_content")

    def test_failed_page_read_can_build_card_from_snippet_fallback(self):
        """
        验证页面读取失败时仍保留可用的 fallback evidence 与来源信息。
        """
        page_results = [
            {
                "title": "Building a Kubernetes Operator",
                "url": "https://example.com/operator-guide",
                "final_url": "https://example.com/operator-guide",
                "query": "Kubernetes Operator implementation guide",
                "snippet": (
                    "A Kubernetes operator typically combines a custom resource definition "
                    "with a controller reconciliation loop."
                ),
                "page_summary": "",
                "page_content": "",
                "domain": "example.com",
                "source_type": "community_article",
                "page_kind": "tutorial_page",
                "read_success": False,
                "read_error": "request failed",
                "status_code": None,
            }
        ]

        cards = build_evidence_cards_from_pages(
            question="如何实现 Kubernetes Operator？",
            page_results=page_results,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertIn("custom resource definition", card["claim"])
        self.assertIn("controller reconciliation loop", card["evidence"])
        self.assertEqual(card["evidence_source"], "snippet_fallback")
        self.assertFalse(card["read_success"])
        self.assertEqual(card["read_error"], "request failed")
        self.assertEqual(card["source_url"], "https://example.com/operator-guide")


if __name__ == "__main__":
    unittest.main()
