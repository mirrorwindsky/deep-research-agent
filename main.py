import os
from dotenv import load_dotenv
from openai import OpenAI

# 1. 加载 .env 文件中的环境变量
load_dotenv()

# 2. 初始化 DeepSeek 客户端
# 重点：因为 DeepSeek 兼容 OpenAI，所以直接使用 OpenAI 客户端
# 只需要把 base_url 指向 DeepSeek 的地址即可
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com" # DeepSeek 的官方 API 地址
)

def test_deepseek_connection():
    """
    测试 DeepSeek API 是否连通的基础函数
    """
    print("正在连接 DeepSeek... 请稍候...")
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat", # 使用 DeepSeek 的通用对话模型
            messages=[
                {"role": "system", "content": "你是一个幽默且专业的资深AI架构师。"},
                {"role": "user", "content": "你好，我刚建好 GitHub 仓库准备从零手搓一个 AI Agent，请用一两句幽默的话鼓励我一下！"}
            ],
            temperature=0.7 # 控制回答的随机性（0.0 最严谨，1.0 最发散）
        )
        
        # 提取并打印回复内容
        reply = response.choices[0].message.content
        print("\n🤖 DeepSeek 架构师回复:")
        print("-" * 30)
        print(reply)
        print("-" * 30)
        
    except Exception as e:
        print(f"❌ 哎呀，连接出错了: {e}")

# Python 程序的标准入口
if __name__ == "__main__":
    test_deepseek_connection()