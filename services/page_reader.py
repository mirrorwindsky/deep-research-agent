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
import re
from typing import Any, Dict

import requests

from config import PAGE_CONTENT_MAX_CHARS, PAGE_READ_TIMEOUT


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
    """
    cleaned = html_text

    noise_patterns = [
        r"<script\b[^>]*>.*?</script>",
        r"<style\b[^>]*>.*?</style>",
        r"<noscript\b[^>]*>.*?</noscript>",
        r"<svg\b[^>]*>.*?</svg>",
        r"<iframe\b[^>]*>.*?</iframe>",
        r"<form\b[^>]*>.*?</form>",
    ]

    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

    return cleaned


def _extract_best_html_block(html_text: str) -> str:
    """
    从 HTML 中优先提取更像正文的区块。

    优先级：
    1. <article>
    2. <main>
    3. <body>
    4. 整页 HTML

    设计原因：
    - 技术文档页和博客页通常会把主内容放在 article/main/body 中
    - 相比直接清洗整页 HTML，该策略能减少导航栏、侧边栏等噪音
    """
    block_patterns = [
        r"<article\b[^>]*>(.*?)</article>",
        r"<main\b[^>]*>(.*?)</main>",
        r"<body\b[^>]*>(.*?)</body>",
    ]

    candidates = []

    for pattern in block_patterns:
        matches = re.findall(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(matches)

    if not candidates:
        return html_text

    # 取最长块，通常更接近正文区域
    return max(candidates, key=len)


def _strip_html_tags(html_text: str) -> str:
    """
    去除 HTML 标签，仅保留可读文本。
    """
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text, flags=re.DOTALL)
    return text


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
    cleaned = _remove_noise_blocks(html_text)
    main_block = _extract_best_html_block(cleaned)
    text = _strip_html_tags(main_block)
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