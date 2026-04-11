import os
from dotenv import load_dotenv

# 读取 .env 文件中的环境变量
# 这样你就不用把 API Key、模型名等敏感/可变配置写死在代码里
load_dotenv()

# =========================
# 大模型基础配置
# =========================

# 使用的模型名称
# 如果 .env 中没有设置 MODEL_NAME，就默认使用 "deepseek-chat"
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")

# API Key
# 这是最敏感的配置，必须放在 .env 中，绝不能写死到仓库里
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# OpenAI-compatible 接口的基础 URL
BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com")

# =========================
# Research Workflow 配置
# =========================

# 最多生成多少个搜索子问题
# 例如一个研究问题可以拆成 2~3 个搜索 query
MAX_SEARCH_QUERIES = int(os.getenv("MAX_SEARCH_QUERIES", "3"))

# 每个搜索子问题最多返回多少条结果
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "5"))

# 是否启用 mock search
# 当前阶段我们先用 mock 数据打通流程，所以默认设为 true
# 当你以后接入真实搜索 API，再把它改成 false
USE_MOCK_SEARCH = os.getenv("USE_MOCK_SEARCH", "true").lower() == "true"

# mock search 的测试模式
# normal：正常返回
# duplicate：制造重复 URL
# empty：返回空结果
# dirty：返回缺字段/脏数据
MOCK_MODE = os.getenv("MOCK_MODE", "normal")