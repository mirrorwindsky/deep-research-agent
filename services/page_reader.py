# services/page_reader.py

"""
页面读取与正文抽取模块。

模块职责：
1. 根据 URL 请求网页内容
2. 对 HTML 做轻量清洗
3. 提取可供后续摘要与证据构建使用的正文文本

设计目标：
1. 为 read_pages_node 提供真实页面读取能力
2. 在不引入额外复杂依赖的前提下，实现可用的正文抽取
3. 保持失败可回退，不因单页抓取异常中断整个 workflow

说明：
- 当前版本采用 requests + 正则清洗的轻量实现
- 当前版本不依赖浏览器自动化，不处理复杂 JS 渲染页面
- 当前版本优先覆盖常见文档页、博客页、README 镜像页等静态内容
"""

import html
import json
import re
from typing import Any, Dict, List, Tuple

import requests

from config import PAGE_CONTENT_MAX_CHARS, PAGE_READ_TIMEOUT


def _iter_json_values(value: Any):
    """
    深度遍历 JSON 对象中的值。

    用途：
    - GitHub 仓库页会把 README richText 放入嵌入式 JSON 数据
    - 该函数用于从未知层级中找出包含正文 HTML 的字符串
    """
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_values(child)
    else:
        yield value


def _extract_github_readme_html(html_text: str) -> str:
    """
    从 GitHub 仓库页中提取 README 的 richText HTML。

    设计原因：
    - GitHub 仓库首页常同时包含文件列表、仓库操作区、README 正文
    - 直接清洗 body 容易让文件列表和登录提示污染 page_content
    - GitHub 的 SSR 数据中通常包含 README richText，可作为更精准的正文来源

    返回：
    - 命中时返回 README HTML 片段
    - 未命中时返回空字符串，并交由通用正文抽取流程处理
    """
    if "github.com" not in html_text and "react-app.embeddedData" not in html_text:
        return ""

    script_pattern = (
        r"<script\b[^>]*data-target=[\"']react-app\.embeddedData[\"'][^>]*>"
        r"(?P<body>.*?)</script>"
    )
    matches = re.finditer(script_pattern, html_text, flags=re.IGNORECASE | re.DOTALL)

    candidates: List[str] = []

    for match in matches:
        script_body = html.unescape(match.group("body")).strip()
        if not script_body:
            continue

        try:
            data = json.loads(script_body)
        except json.JSONDecodeError:
            continue

        for value in _iter_json_values(data):
            if not isinstance(value, str):
                continue

            if "markdown-body" in value and "<article" in value:
                candidates.append(value)

    if candidates:
        return max(candidates, key=len)

    # GitHub 页面结构变化时，保留一个窄范围的字符串级回退。
    fallback_pattern = r"\"richText\":\"(?P<body>(?:\\.|[^\"\\])*)\""
    for match in re.finditer(fallback_pattern, html_text, flags=re.DOTALL):
        try:
            value = json.loads(f"\"{match.group('body')}\"")
        except json.JSONDecodeError:
            continue

        if "markdown-body" in value and "<article" in value:
            candidates.append(value)

    return max(candidates, key=len) if candidates else ""


def _normalize_whitespace(text: str) -> str:
    """
    规范化正文中的空白字符。

    处理内容：
    1. HTML 实体反转义
    2. 连续空白折叠
    3. 多余空行压缩
    """
    text = html.unescape(text or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\t+", " ", text)
    text = re.sub(r"[ \xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_noise_blocks(html_text: str) -> str:
    """
    移除常见噪音块。

    当前移除对象：
    - script
    - style
    - noscript
    - svg
    - iframe
    - form
    - header / nav / footer / aside 等页面壳子区域
    """
    cleaned = html_text

    noise_patterns = [
        r"<script\b[^>]*>.*?</script>",
        r"<style\b[^>]*>.*?</style>",
        r"<noscript\b[^>]*>.*?</noscript>",
        r"<svg\b[^>]*>.*?</svg>",
        r"<iframe\b[^>]*>.*?</iframe>",
        r"<form\b[^>]*>.*?</form>",
        r"<header\b[^>]*>.*?</header>",
        r"<nav\b[^>]*>.*?</nav>",
        r"<footer\b[^>]*>.*?</footer>",
        r"<aside\b[^>]*>.*?</aside>",
        r"<dialog\b[^>]*>.*?</dialog>",
        r"<button\b[^>]*>.*?</button>",
        r"<select\b[^>]*>.*?</select>",
        r"<template\b[^>]*>.*?</template>",
        r"<[^>]+\brole=[\"'](?:navigation|banner|contentinfo|search)[\"'][^>]*>.*?</[^>]+>",
    ]

    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

    return cleaned


def _text_length_from_html(html_text: str) -> int:
    """
    估算 HTML 候选块中的可读文本长度。

    该函数用于候选正文块排序，不作为最终正文输出。
    """
    text = _strip_html_tags(html_text)
    text = _normalize_whitespace(text)
    return len(text)


def _extract_attr_based_blocks(html_text: str) -> List[str]:
    """
    提取带有常见正文容器属性的 HTML 片段。

    设计原因：
    - GitHub README 常见于 markdown-body / readme 等容器中
    - 文档站常见于 docs-content / theme-doc-markdown / role=main 等容器中
    - 在不引入 HTML parser 的阶段，先用保守属性线索补强正文定位

    限制说明：
    - 正则无法完美处理任意嵌套 HTML
    - 当前函数只作为 article/main/body 之外的候选补充
    """
    attr_hints = [
        "markdown-body",
        "repository-content",
        "readme",
        "wiki-content",
        "docs-content",
        "doc-content",
        "documentation",
        "theme-doc-markdown",
        "docMainContainer",
        "main-content",
        "article-content",
        "post-content",
        "prose",
    ]

    candidates: List[str] = []

    for hint in attr_hints:
        pattern = (
            r"<(?P<tag>article|main|section|div)\b"
            r"(?=[^>]*(?:class|id)=[\"'][^\"']*"
            + re.escape(hint)
            + r"[^\"']*[\"'])[^>]*>"
            r"(?P<body>.*?)</(?P=tag)>"
        )
        matches = re.finditer(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(match.group("body") for match in matches)

    role_main_pattern = (
        r"<(?P<tag>main|section|div)\b"
        r"(?=[^>]*role=[\"']main[\"'])[^>]*>"
        r"(?P<body>.*?)</(?P=tag)>"
    )
    matches = re.finditer(role_main_pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(match.group("body") for match in matches)

    return candidates


def _extract_best_html_block(html_text: str) -> str:
    """
    从 HTML 中优先提取更像正文的区块。

    优先级：
    1. 常见正文容器属性，如 markdown-body / docs-content
    2. <article>
    3. <main>
    4. <body>
    4. 整页 HTML

    设计原因：
    - 技术文档页和博客页通常会把主内容放在 article/main/body 中
    - 相比直接清洗整页 HTML，该策略能减少导航栏、侧边栏等噪音
    - GitHub 与部分文档站的正文容器更依赖 class/id，而不是标准 article 标签
    """
    block_patterns = [
        r"<article\b[^>]*>(.*?)</article>",
        r"<main\b[^>]*>(.*?)</main>",
        r"<body\b[^>]*>(.*?)</body>",
    ]

    candidates: List[str] = _extract_attr_based_blocks(html_text)

    for pattern in block_patterns:
        matches = re.findall(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(matches)

    if not candidates:
        return html_text

    candidates_with_lengths: List[Tuple[str, int]] = [
        (candidate, _text_length_from_html(candidate))
        for candidate in candidates
    ]
    candidates_with_lengths = [
        (candidate, length)
        for candidate, length in candidates_with_lengths
        if length >= 120
    ]

    if not candidates_with_lengths:
        return max(candidates, key=len)

    # 取可读文本最长的块，通常比原始 HTML 长度更接近真实正文密度。
    return max(candidates_with_lengths, key=lambda item: item[1])[0]


def _strip_html_tags(html_text: str) -> str:
    """
    去除 HTML 标签，仅保留可读文本。
    """
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</section\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</article\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</tr\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text, flags=re.DOTALL)
    return text


def _is_noise_line(line: str) -> bool:
    """
    判断单行文本是否属于常见页面壳子噪音。

    当前过滤重点：
    - GitHub 平台导航
    - 文档站顶部导航、版本切换、语言切换
    - 登录、搜索、跳转等短操作文本
    """
    normalized = re.sub(r"\s+", " ", line).strip()
    lowered = normalized.lower()

    if not normalized:
        return True

    exact_noise = {
        "skip to content",
        "sign in",
        "sign up",
        "pricing",
        "product",
        "products",
        "solutions",
        "resources",
        "open source",
        "enterprise",
        "navigation menu",
        "toggle navigation",
        "search",
        "search docs",
        "search documentation",
        "edit this page",
        "copy page",
        "table of contents",
        "on this page",
        "previous",
        "next",
        "language",
        "languages",
        "version",
        "versions",
        "latest",
        "main navigation",
        "code",
        "issues",
        "pull requests",
        "actions",
        "projects",
        "security",
        "insights",
    }

    if lowered in exact_noise:
        return True

    startswith_noise = (
        "you signed in with another tab",
        "reload to refresh your session",
        "github is where people build software",
        "this repository has been archived",
        "dismiss alert",
        "view all files",
        "go to file",
        "code issues pull requests actions",
    )

    if any(lowered.startswith(prefix) for prefix in startswith_noise):
        return True

    if len(normalized) <= 2:
        return True

    # 短文本且缺少句子或技术内容特征时，通常是导航项。
    if len(normalized) <= 24 and not re.search(r"[.:;，。:/_-]", normalized):
        common_nav_words = {
            "overview",
            "concepts",
            "tasks",
            "tutorials",
            "reference",
            "community",
            "blog",
            "about",
            "download",
            "releases",
            "branches",
            "tags",
            "activity",
            "stars",
            "forks",
            "watching",
        }
        if lowered in common_nav_words:
            return True

    return False


def _filter_noise_lines(text: str) -> str:
    """
    对标签清洗后的文本做行级噪音过滤。

    设计原因：
    - 即使已经移除 nav/header 等结构块，GitHub 与文档站仍可能残留短导航文本
    - 行级过滤可在不引入额外依赖的前提下快速降低噪音密度
    """
    lines = text.splitlines()
    cleaned_lines: List[str] = []
    previous_line = ""

    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()

        if _is_noise_line(normalized):
            continue

        if normalized == previous_line:
            continue

        cleaned_lines.append(normalized)
        previous_line = normalized

    return "\n".join(cleaned_lines)


def extract_page_text_from_html(html_text: str) -> str:
    """
    从原始 HTML 中提取可读正文文本。

    处理流程：
    1. 移除常见噪音块
    2. 提取更像正文的 HTML 区块
    3. 去除 HTML 标签
    4. 规范化空白字符
    5. 按最大字符数截断
    """
    github_readme_html = _extract_github_readme_html(html_text)
    if github_readme_html:
        cleaned = _remove_noise_blocks(github_readme_html)
    else:
        cleaned = _remove_noise_blocks(html_text)

    main_block = _extract_best_html_block(cleaned)
    text = _strip_html_tags(main_block)
    text = _filter_noise_lines(text)
    text = _normalize_whitespace(text)

    if len(text) > PAGE_CONTENT_MAX_CHARS:
        text = text[:PAGE_CONTENT_MAX_CHARS].strip()

    return text


def fetch_page_content(url: str) -> Dict[str, Any]:
    """
    读取单个 URL 对应的页面正文。

    返回字段：
    - read_success: 是否读取成功
    - final_url: 请求后的最终 URL
    - status_code: HTTP 状态码
    - content_type: 响应内容类型
    - page_content: 提取后的正文文本
    - read_error: 失败原因
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=PAGE_READ_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        html_text = response.text or ""

        page_content = extract_page_text_from_html(html_text)

        if not page_content:
            return {
                "read_success": False,
                "final_url": response.url,
                "status_code": response.status_code,
                "content_type": content_type,
                "page_content": "",
                "read_error": "页面正文提取为空",
            }

        return {
            "read_success": True,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": content_type,
            "page_content": page_content,
            "read_error": "",
        }

    except requests.RequestException as exc:
        return {
            "read_success": False,
            "final_url": url,
            "status_code": None,
            "content_type": "",
            "page_content": "",
            "read_error": f"请求失败: {exc}",
        }
