"""
Page summarizer 回归测试。

这些测试保护页面摘要服务的核心契约：
- prompt 应包含研究问题、子 query、页面标题、URL 与正文
- 模型正常返回时应使用模型摘要
- 模型返回空值或异常时应回退到正文片段
- 空正文应返回空摘要
"""

import unittest

from services.page_summarizer import (
    build_page_summary_prompt,
    fallback_page_summary,
    summarize_page_content,
)


class FakeLLM:
    """
    用于测试页面摘要服务的 LLM 替身。
    """

    def __init__(self, response="", error=None):
        self.response = response
        self.error = error
        self.calls = []

    def chat(self, system_prompt, user_prompt):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        })
        if self.error:
            raise self.error
        return self.response


class PageSummarizerTests(unittest.TestCase):
    def test_build_page_summary_prompt_includes_context(self):
        prompt = build_page_summary_prompt(
            question="Kubernetes Operator 是什么？",
            query="Kubernetes Operator official docs",
            title="Operator pattern",
            url="https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
            page_content="Operators are software extensions to Kubernetes.",
        )

        self.assertIn("Kubernetes Operator 是什么？", prompt)
        self.assertIn("Kubernetes Operator official docs", prompt)
        self.assertIn("Operator pattern", prompt)
        self.assertIn("https://kubernetes.io/docs/concepts/extend-kubernetes/operator/", prompt)
        self.assertIn("Operators are software extensions", prompt)

    def test_summarize_page_content_uses_model_summary(self):
        llm = FakeLLM(response="Operator 使用 CRD 和控制器管理应用。")

        summary = summarize_page_content(
            question="Kubernetes Operator 是什么？",
            query="Kubernetes Operator docs",
            title="Operator pattern",
            url="https://example.com",
            page_content="正文内容",
            llm_service=llm,
        )

        self.assertEqual(summary, "Operator 使用 CRD 和控制器管理应用。")
        self.assertEqual(len(llm.calls), 1)

    def test_summarize_page_content_falls_back_when_model_returns_empty(self):
        llm = FakeLLM(response="")

        summary = summarize_page_content(
            question="问题",
            query="query",
            title="title",
            url="https://example.com",
            page_content="正文内容" * 100,
            llm_service=llm,
        )

        self.assertEqual(summary, ("正文内容" * 100)[:500].strip())

    def test_summarize_page_content_falls_back_when_model_raises(self):
        llm = FakeLLM(error=RuntimeError("model failed"))

        summary = summarize_page_content(
            question="问题",
            query="query",
            title="title",
            url="https://example.com",
            page_content="fallback text",
            llm_service=llm,
        )

        self.assertEqual(summary, "fallback text")

    def test_summarize_page_content_returns_empty_for_empty_content(self):
        llm = FakeLLM(response="不应调用")

        summary = summarize_page_content(
            question="问题",
            query="query",
            title="title",
            url="https://example.com",
            page_content="",
            llm_service=llm,
        )

        self.assertEqual(summary, "")
        self.assertEqual(llm.calls, [])

    def test_fallback_page_summary_respects_limit(self):
        summary = fallback_page_summary("abcdef", limit=3)

        self.assertEqual(summary, "abc")


if __name__ == "__main__":
    unittest.main()
