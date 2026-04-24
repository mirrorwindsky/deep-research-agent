"""
报告引用校验回归测试。

这些测试保护最终报告引用编号的确定性校验逻辑：
- 正文引用编号和参考来源编号应分开提取
- 正文不得引用候选来源之外的编号
- 参考来源不得列出候选来源之外的编号
- 正文引用过的候选编号必须出现在参考来源列表中
"""

import unittest

from services.report_validator import (
    collect_allowed_source_ids,
    extract_citation_ids,
    extract_reference_ids,
    validate_report_citations,
)


class ReportValidatorTests(unittest.TestCase):
    def test_extract_citation_ids_deduplicates_and_sorts_numbers(self):
        result = extract_citation_ids("核心结论 [2][1]，后续再次引用 [2]。")

        self.assertEqual(result, [1, 2])

    def test_extract_reference_ids_only_reads_reference_entries(self):
        reference_text = """# 参考来源

[1] Official docs
链接: https://example.com/docs
说明文本中出现 [9] 不应被视为参考来源条目。

[2] Guide
链接: https://example.com/guide
"""

        result = extract_reference_ids(reference_text)

        self.assertEqual(result, [1, 2])

    def test_collect_allowed_source_ids_ignores_sources_without_integer_id(self):
        result = collect_allowed_source_ids([
            {"source_id": 2, "title": "Guide"},
            {"source_id": "3", "title": "String id"},
            {"title": "Missing id"},
            {"source_id": 1, "title": "Docs"},
        ])

        self.assertEqual(result, [1, 2])

    def test_validate_report_citations_passes_when_ids_are_consistent(self):
        report = """# 核心结论
结论来自官方文档 [1]，并由实践指南补充 [2]。

# 参考来源

[1] Official docs
链接: https://example.com/docs

[2] Guide
链接: https://example.com/guide
"""
        unique_sources = [
            {"source_id": 1, "title": "Official docs"},
            {"source_id": 2, "title": "Guide"},
        ]

        result = validate_report_citations(report, unique_sources)

        self.assertTrue(result["valid"])
        self.assertEqual(result["cited_ids"], [1, 2])
        self.assertEqual(result["reference_ids"], [1, 2])
        self.assertEqual(result["invalid_citation_ids"], [])
        self.assertEqual(result["missing_reference_ids"], [])

    def test_validate_report_citations_reports_invalid_body_citation(self):
        report = """# 核心结论
报告正文引用了不存在的来源 [9]。

# 参考来源

[1] Official docs
链接: https://example.com/docs
"""

        result = validate_report_citations(
            report=report,
            unique_sources=[{"source_id": 1, "title": "Official docs"}],
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_citation_ids"], [9])

    def test_validate_report_citations_reports_missing_reference_entry(self):
        report = """# 核心结论
报告正文引用了候选来源 [1] 和 [2]。

# 参考来源

[1] Official docs
链接: https://example.com/docs
"""

        result = validate_report_citations(
            report=report,
            unique_sources=[
                {"source_id": 1, "title": "Official docs"},
                {"source_id": 2, "title": "Guide"},
            ],
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["missing_reference_ids"], [2])

    def test_validate_report_citations_reports_invalid_reference_entry(self):
        report = """# 核心结论
报告正文只引用了官方来源 [1]。

# 参考来源

[1] Official docs
链接: https://example.com/docs

[7] Invented source
链接: https://example.com/invented
"""

        result = validate_report_citations(
            report=report,
            unique_sources=[{"source_id": 1, "title": "Official docs"}],
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_reference_ids"], [7])

    def test_validate_report_citations_requires_reference_section(self):
        report = "# 核心结论\n报告正文引用了官方来源 [1]。"

        result = validate_report_citations(
            report=report,
            unique_sources=[{"source_id": 1, "title": "Official docs"}],
        )

        self.assertFalse(result["valid"])
        self.assertFalse(result["has_reference_section"])
        self.assertEqual(result["missing_reference_ids"], [1])


if __name__ == "__main__":
    unittest.main()
