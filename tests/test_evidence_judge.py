"""
Evidence judge 策略测试。

这些测试保护 evidence card 构建后的补搜判断规则：
- 证据不足时应触发一轮补搜
- retry_count 应阻止重复补搜循环
- 官方、多域名、实现导向证据充分时应通过质量判断
- 过多 snippet fallback 证据应被视为可靠性不足
"""

import unittest

from services.evidence_judge import judge_evidence_quality


def make_card(
    *,
    url: str,
    domain: str,
    source_type: str = "community_article",
    page_kind: str = "docs_page",
    evidence_source: str = "page_content",
):
    """
    构造 judge 策略测试所需的最小 evidence card。
    """
    return {
        "claim": "sample claim",
        "evidence": "sample evidence",
        "source_url": url,
        "domain": domain,
        "source_type": source_type,
        "page_kind": page_kind,
        "evidence_source": evidence_source,
    }


class EvidenceJudgeTests(unittest.TestCase):
    def test_insufficient_evidence_triggers_retry_before_retry_limit(self):
        result = judge_evidence_quality(
            evidence_cards=[
                make_card(
                    url="https://example.com/a",
                    domain="example.com",
                    source_type="community_article",
                    page_kind="docs_page",
                )
            ],
            retry_count=0,
        )

        self.assertTrue(result["needs_retry"])
        self.assertIn("insufficient_evidence", result["evidence_gaps"])
        self.assertIn("official_source_missing", result["evidence_gaps"])

    def test_retry_limit_prevents_second_retry_even_with_gaps(self):
        result = judge_evidence_quality(evidence_cards=[], retry_count=1)

        self.assertFalse(result["needs_retry"])
        self.assertIn("insufficient_evidence", result["evidence_gaps"])

    def test_sufficient_official_diverse_implementation_evidence_passes(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
            ),
            make_card(
                url="https://github.com/example/operator-sample",
                domain="github.com",
                source_type="official_repo",
                page_kind="example_page",
            ),
            make_card(
                url="https://dev.to/example/operator-guide",
                domain="dev.to",
                source_type="community_article",
                page_kind="tutorial_page",
            ),
        ]

        result = judge_evidence_quality(evidence_cards=cards, retry_count=0)

        self.assertFalse(result["needs_retry"])
        self.assertEqual(result["evidence_gaps"], [])
        self.assertEqual(result["metrics"]["official_count"], 2)
        self.assertEqual(result["metrics"]["domain_count"], 3)
        self.assertEqual(result["metrics"]["implementation_count"], 2)
        self.assertEqual(result["metrics"]["fallback_count"], 0)
        self.assertEqual(result["metrics"]["fallback_ratio"], 0)

    def test_single_domain_evidence_reports_source_diversity_gap(self):
        cards = [
            make_card(
                url=f"https://example.com/{idx}",
                domain="example.com",
                source_type="official_docs",
                page_kind="docs_page",
            )
            for idx in range(3)
        ]

        result = judge_evidence_quality(evidence_cards=cards, retry_count=0)

        self.assertTrue(result["needs_retry"])
        self.assertIn("source_diversity_low", result["evidence_gaps"])

    def test_many_fallback_evidence_cards_trigger_retry(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/operator",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
                evidence_source="snippet_fallback",
            ),
            make_card(
                url="https://github.com/example/operator",
                domain="github.com",
                source_type="official_repo",
                page_kind="example_page",
                evidence_source="snippet_fallback",
            ),
            make_card(
                url="https://dev.to/example/operator",
                domain="dev.to",
                source_type="community_article",
                page_kind="tutorial_page",
                evidence_source="page_content",
            ),
        ]

        result = judge_evidence_quality(evidence_cards=cards, retry_count=0)

        self.assertTrue(result["needs_retry"])
        self.assertIn("fallback_evidence_too_many", result["evidence_gaps"])
        self.assertEqual(result["metrics"]["fallback_count"], 2)
        self.assertAlmostEqual(result["metrics"]["fallback_ratio"], 2 / 3)

    def test_many_fallback_evidence_cards_do_not_retry_after_retry_limit(self):
        cards = [
            make_card(
                url=f"https://example.com/{idx}",
                domain=f"example{idx}.com",
                source_type="official_docs" if idx == 0 else "community_article",
                page_kind="example_page" if idx == 1 else "docs_page",
                evidence_source="snippet_fallback",
            )
            for idx in range(3)
        ]

        result = judge_evidence_quality(evidence_cards=cards, retry_count=1)

        self.assertFalse(result["needs_retry"])
        self.assertIn("fallback_evidence_too_many", result["evidence_gaps"])

    def test_implementation_question_without_detail_reports_specific_gap(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/operator",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
            ),
            make_card(
                url="https://example.com/concepts",
                domain="example.com",
                source_type="community_article",
                page_kind="docs_page",
            ),
            make_card(
                url="https://cncf.io/operator",
                domain="cncf.io",
                source_type="official_blog",
                page_kind="docs_page",
            ),
        ]

        result = judge_evidence_quality(
            evidence_cards=cards,
            retry_count=0,
            question="如何实现 Kubernetes Operator？",
        )

        self.assertTrue(result["needs_retry"])
        self.assertIn("implementation_detail_missing", result["evidence_gaps"])
        self.assertTrue(result["metrics"]["needs_implementation_detail"])
        self.assertFalse(result["metrics"]["has_implementation_evidence"])

    def test_implementation_evidence_satisfies_implementation_question(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/operator",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
            ),
            make_card(
                url="https://github.com/example/operator",
                domain="github.com",
                source_type="official_repo",
                page_kind="readme",
            ),
            make_card(
                url="https://dev.to/operator",
                domain="dev.to",
                source_type="community_article",
                page_kind="tutorial_page",
            ),
        ]

        result = judge_evidence_quality(
            evidence_cards=cards,
            retry_count=0,
            question="如何实现 Kubernetes Operator？",
        )

        self.assertNotIn("implementation_detail_missing", result["evidence_gaps"])
        self.assertTrue(result["metrics"]["has_implementation_evidence"])

    def test_comparison_question_without_comparison_material_reports_gap(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/operator",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
            ),
            make_card(
                url="https://github.com/example/operator",
                domain="github.com",
                source_type="official_repo",
                page_kind="example_page",
            ),
            make_card(
                url="https://dev.to/operator",
                domain="dev.to",
                source_type="community_article",
                page_kind="tutorial_page",
            ),
        ]

        result = judge_evidence_quality(
            evidence_cards=cards,
            retry_count=0,
            question="Kubernetes Operator 和 Helm chart 的区别是什么？",
        )

        self.assertTrue(result["needs_retry"])
        self.assertIn("comparison_missing", result["evidence_gaps"])
        self.assertTrue(result["metrics"]["needs_comparison"])
        self.assertFalse(result["metrics"]["has_comparison_evidence"])

    def test_comparison_evidence_satisfies_comparison_question(self):
        cards = [
            make_card(
                url="https://kubernetes.io/docs/operator",
                domain="kubernetes.io",
                source_type="official_docs",
                page_kind="docs_page",
            ),
            make_card(
                url="https://example.com/operator-vs-helm",
                domain="example.com",
                source_type="community_article",
                page_kind="comparison_page",
            ),
            make_card(
                url="https://github.com/example/operator",
                domain="github.com",
                source_type="official_repo",
                page_kind="example_page",
            ),
        ]

        result = judge_evidence_quality(
            evidence_cards=cards,
            retry_count=0,
            question="Kubernetes Operator vs Helm chart 如何选择？",
        )

        self.assertNotIn("comparison_missing", result["evidence_gaps"])
        self.assertTrue(result["metrics"]["has_comparison_evidence"])


if __name__ == "__main__":
    unittest.main()
