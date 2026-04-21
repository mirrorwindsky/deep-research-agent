# config.py

"""
项目全局配置模块。

模块职责：
1. 统一管理环境变量读取
2. 提供大模型调用相关配置
3. 提供 research workflow 相关配置
4. 提供 mock / 真实搜索切换配置
5. 提供搜索结果质量控制所需的评分表与识别线索

设计目标：
1. 避免将模型参数、搜索参数、评分规则散落在多个模块中
2. 为后续调参、切换模型、切换搜索后端提供统一入口
3. 将“来源质量控制”中的可调规则集中化管理
4. 保持配置项命名清晰、职责明确、可读性高

说明：
- 当前项目阶段以“可维护、可解释、可渐进扩展”为优先目标
- 若后续配置项继续增多，可再细分为 llm_config / search_config / ranking_config
"""

import os
from dotenv import load_dotenv

# 读取 .env 文件中的环境变量。
#
# 设计原因：
# 1. 将 API Key、模型名称、可变参数从代码中分离
# 2. 避免敏感信息直接写入仓库
# 3. 便于在不同环境下切换配置
load_dotenv()

# =========================
# 大模型基础配置
# =========================

# 使用的模型名称。
#
# 当前默认值为 "deepseek-chat"。
# 若 .env 中显式设置 MODEL_NAME，则以环境变量为准。
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")

# API Key。
#
# 该配置应放在 .env 中，避免直接写入代码仓库。
# 若为空，则说明本地环境尚未正确配置模型密钥。
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# OpenAI-compatible 接口基础 URL。
#
# 当前默认使用 DeepSeek 的兼容接口地址。
# 若后续切换兼容服务商，可通过 .env 覆盖该值。
BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com")

# =========================
# Research Workflow 配置
# =========================

# planner 最多生成多少个搜索子问题。
#
# 当前默认值为 3，对应当前项目的第一阶段设计：
# - 通常覆盖概念 / 官方资料 / 对比或实现 三个方向
MAX_SEARCH_QUERIES = int(os.getenv("MAX_SEARCH_QUERIES", "3"))

# 每个搜索子问题最多拉取多少条原始结果。
#
# 该值决定 search_node 从搜索工具层接收的结果规模。
# 最终真正进入后续节点的结果，还会经过去重、排序和截断。
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "6"))

# search_node 在排序完成后，最终最多保留多少条结果进入后续节点。
#
# 设计原因：
# 1. 减少低质量结果污染 synthesize / report 阶段
# 2. 控制上下文长度，降低 prompt 噪音
# 3. 保持当前阶段系统行为稳定且便于观察
MAX_FILTERED_RESULTS = int(os.getenv("MAX_FILTERED_RESULTS", "12"))

# read_pages_node 最多读取多少条高分页面。
#
# 设计原因：
# 1. 页面读取和页面摘要都会增加时延与模型成本
# 2. 第一版 deep research v2 先聚焦前若干高质量来源
MAX_PAGE_READS = int(os.getenv("MAX_PAGE_READS", "5"))

# 单个页面请求的超时时间（秒）。
#
# 页面读取阶段常见失败原因包括：
# - 网络慢
# - 站点响应慢
# - 站点阻止抓取
# 当前阶段应尽量快速失败，避免整条链被单个页面拖死。
PAGE_READ_TIMEOUT = int(os.getenv("PAGE_READ_TIMEOUT", "10"))

# 单页正文最多保留多少字符。
#
# 设计原因：
# 1. 控制后续摘要 prompt 的长度
# 2. 避免把整页噪音内容全部交给模型
PAGE_CONTENT_MAX_CHARS = int(os.getenv("PAGE_CONTENT_MAX_CHARS", "5000"))

# =========================
# Mock Search 配置
# =========================

# 是否启用 mock search。
#
# True  -> 使用本地 mock 搜索结果
# False -> 使用真实搜索 API
#
# 典型使用场景：
# - 主链初期联通测试
# - 稳定性补丁测试
# - 节点局部调试
USE_MOCK_SEARCH = os.getenv("USE_MOCK_SEARCH", "true").lower() == "true"

# mock search 的测试模式。
#
# 可选值：
# - normal    : 正常返回不同 query 的不同结果
# - duplicate : 故意制造重复 URL，测试 search_node 去重能力
# - empty     : 返回空结果，测试 synthesize/report 的兜底能力
# - dirty     : 返回缺字段或脏数据，测试健壮性
MOCK_MODE = os.getenv("MOCK_MODE", "normal")

# =========================
# 真实搜索 API 配置
# =========================

# Tavily API Key。
#
# 当前项目使用 Tavily 作为第一个真实搜索后端。
# 若为空，则说明真实搜索模式尚未完成本地密钥配置。
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Tavily 搜索接口地址。
#
# 一般无需频繁修改，保留为独立配置项主要是为了环境切换与调试便利。
TAVILY_SEARCH_URL = os.getenv("TAVILY_SEARCH_URL", "https://api.tavily.com/search")

# Tavily 搜索深度配置。
#
# 常见取值：
# - basic
# - advanced
#
# basic 通常更省额度，advanced 通常召回更强但成本更高。
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic")

# =========================
# 搜索结果质量控制：评分表
# =========================

# 来源类型分数。
#
# 设计思想：
# - 不再直接由少量具体域名名单决定最终优先级
# - 先判断“来源属于哪一类”，再统一给分
# - 该方式更适合通用 technical research 场景
#
# 说明：
# - official_docs / official_repo 通常是最强的一手资料
# - community_article 虽为二手资料，但常常更便于理解
# - forum_discussion 适合作为补充证据，而非主证据
# - low_priority 用于明确压制低质量噪音来源
SOURCE_TYPE_SCORES = {
    "official_docs": 5,
    "official_repo": 5,
    "official_blog": 4,
    "community_article": 2,
    "forum_discussion": 1,
    "low_priority": -3,
    "unknown": 0,
}

# 页面形态分数。
#
# 设计思想：
# - 同一来源站点内，不同页面类型的价值差异很大
# - 例如 GitHub README、GitHub issue、官网文档页、官网营销页，技术价值并不相同
#
# 说明：
# - api_reference / docs_page / example_page / readme 通常更适合 research 场景
# - marketing_page / content_farm_page 默认降权
PAGE_KIND_SCORES = {
    "api_reference": 2,
    "docs_page": 2,
    "example_page": 2,
    "readme": 2,
    "comparison_page": 1,
    "tutorial_page": 1,
    "issue_or_discussion": 0,
    "release_note": 1,
    "marketing_page": -1,
    "content_farm_page": -2,
    "unknown": 0,
}

# =========================
# 搜索结果质量控制：query_fit 配置
# =========================

# 标题命中 query 关键词时的加分。
#
# 标题通常比摘要更能直接反映页面主题，因此默认权重更高。
QUERY_FIT_TITLE_HIT = 2

# 摘要命中 query 关键词时的加分。
QUERY_FIT_SNIPPET_HIT = 1

# 当 query 本身是“对比型问题”时，结果也体现对比特征的额外加分。
QUERY_FIT_COMPARISON_BONUS = 1

# 当 query 本身是“实现 / 教程型问题”时，结果也体现实现特征的额外加分。
QUERY_FIT_IMPLEMENTATION_BONUS = 1

# 当 query 明确体现“官方资料意图”时，结果也体现官方特征的额外加分。
QUERY_FIT_OFFICIAL_INTENT_BONUS = 1

# =========================
# 搜索结果质量控制：信息密度配置
# =========================

# 摘要信息量的最低长度阈值。
#
# 小于该值的摘要，通常信息非常有限。
EVIDENCE_SNIPPET_MIN_LEN = 40

# 摘要信息量较高的长度阈值。
#
# 大于等于该值时，可视为摘要较完整。
EVIDENCE_SNIPPET_GOOD_LEN = 100

# =========================
# 搜索结果质量控制：来源识别线索
# =========================

# 明确低优先级来源域名。
#
# 说明：
# - 该列表不是“绝对屏蔽名单”
# - 作用是作为来源类型识别中的辅助线索
# - 当前应保持保守，避免误伤正常技术站点
LOW_PRIORITY_DOMAINS = [
    "csdn.net",
    "cnblogs.com",
    "tutorialspoint.com",
]

# 论坛 / 问答 / 社区讨论域名。
#
# 该类来源通常对真实问题和边界情况有帮助，
# 但一般不适合作为定义性主证据。
FORUM_DOMAINS = [
    "stackoverflow.com",
    "reddit.com",
    "quora.com",
]

# 常见社区技术内容平台域名。
#
# 该类来源通常不是第一手资料，
# 但在教程、经验总结、上手文章中有较高实用价值。
COMMUNITY_DOMAINS = [
    "medium.com",
    "dev.to",
    "hashnode.dev",
]

# =========================
# 搜索结果质量控制：页面识别提示词
# =========================

# 官方文档线索。
#
# 这些提示词主要用于帮助判断页面是否像文档站、参考页或 API 页。
OFFICIAL_DOC_HINTS = [
    "docs.",
    "/docs/",
    "/reference/",
    "/api/",
    "/manual/",
]

# 官方博客 / 发布说明线索。
#
# 这些提示词主要用于帮助识别博客页、发布说明页、changelog 页。
OFFICIAL_BLOG_HINTS = [
    "blog.",
    "/blog/",
    "/changelog/",
    "/release",
    "/releases",
    "/announcements",
]

# 示例页 / 快速开始线索。
#
# 对“如何实现”类问题尤其重要。
EXAMPLE_HINTS = [
    "/examples/",
    "/example/",
    "example",
    "quickstart",
    "getting-started",
]

# README 线索。
README_HINTS = [
    "/readme",
    "readme.md",
]

# issue / discussion / pull request 线索。
#
# 这些页面对排错和边界情况分析常常有帮助，
# 但通常不适合作为主定义来源。
ISSUE_HINTS = [
    "/issues/",
    "/discussions/",
    "/pull/",
]

# 营销页线索。
#
# 该类页面通常以产品展示、销售转化为目的，技术信息密度偏低。
MARKETING_HINTS = [
    "/pricing",
    "/enterprise",
    "/sales",
    "/contact",
]

# =========================
# 搜索结果质量控制：问题意图提示词
# =========================

# 对比型问题提示词。
#
# 用于辅助判断 query 是否属于“比较 / 区别 / 差异”类问题。
COMPARISON_HINTS = [
    "vs",
    "versus",
    "difference",
    "differences",
    "compare",
    "comparison",
    "compared",
    "区别",
    "对比",
    "差异",
]

# 实现 / 教程型问题提示词。
#
# 用于辅助判断 query 是否属于“如何做 / 示例 / 教程 / 实现”类问题。
IMPLEMENTATION_HINTS = [
    "how to",
    "tutorial",
    "guide",
    "example",
    "implementation",
    "getting started",
    "quickstart",
    "教程",
    "示例",
    "实现",
]

# 官方资料意图提示词。
#
# 用于辅助判断 query 是否明确偏向官方文档、API 参考资料或正式说明。
OFFICIAL_INTENT_HINTS = [
    "official",
    "documentation",
    "docs",
    "api",
    "reference",
    "官网",
    "官方文档",
]

# =========================
# 搜索结果质量控制：权威来源与 query_fit 增强配置
# =========================

# 主题权威来源域名。
#
# 用途：
# - 只有命中这些域名时，文档页 / 博客页才更有资格被识别为 official_docs / official_blog
# - 用于避免把普通第三方博客误判为“官方博客”
#
# 说明：
# - 当前列表保持保守
# - 后续可根据项目覆盖主题逐步扩展
AUTHORITATIVE_DOMAINS = [
    "kubernetes.io",
    "cncf.io",
    "langchain.com",
    "python.langchain.com",
]

# query 完整短语命中时的额外加分。
#
# 用于提高“精准落点页”相对于“泛相关页”的优势。
QUERY_FIT_EXACT_PHRASE_BONUS = 2

# 结果页面路径较具体时的额外加分。
#
# 例如：
# - /docs/concepts/extend-kubernetes/operator/
# 通常比：
# - /docs/home/
# 更贴近 query 对应的具体问题。
QUERY_FIT_SPECIFIC_PAGE_BONUS = 1

# 结果为首页或过于泛化入口页时的轻微降权。
#
# 该项不宜过大，只用于区分“具体页”与“首页”。
QUERY_FIT_HOME_PAGE_PENALTY = -1
