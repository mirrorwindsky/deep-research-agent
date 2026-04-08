import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# 导入我们刚刚写的本地工具
from tools.weather import get_weather

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def run_agent_with_tools():
    # 1. 编写《工具说明书》告诉大模型有什么工具可以用 (必须是严格的 JSON Schema 格式)
    tools_description =[
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的当前天气情况",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "城市名称，例如：北京、上海、伦敦"
                        }
                    },
                    "required": ["location"] # 告诉大模型这个参数是必填的
                }
            }
        }
    ]

    # 回合 1：用户提问，并附带工具说明书
    messages =[
        {"role": "system", "content": "你是一个有用的AI助手。如果用户问天气，请务必使用工具查询后再回答。"},
        {"role": "user", "content": "帮我看看北京今天天气怎么样？我们要不要带伞？"}
    ]

    print("👤 用户: 帮我看看北京今天天气怎么样？我们要不要带伞？")
    print("🤖 AI 思考中...")

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=tools_description # 把说明书扔给大模型
    )

    # 获取 AI 的回复信息
    ai_message = response.choices[0].message

    # 回合 2：判断 AI 是否要求调用工具
    if ai_message.tool_calls:
        tool_call = ai_message.tool_calls[0]
        function_name = tool_call.function.name # AI 想调用的函数名
        arguments = json.loads(tool_call.function.arguments) # AI 提取出的参数
        
        print(f"🛠️  AI 请求调用工具: {function_name}, 参数: {arguments}")
        
        # 回合 3：我们在本地帮它执行这个 Python 函数
        if function_name == "get_weather":
            # 真正调用我们的 Python 函数
            tool_result = get_weather(location=arguments["location"])
            print(f"✅ 工具执行完毕，结果是: {tool_result}")
            
            # 【核心步骤】：把 AI 的请求和工具的执行结果都加进对话历史中
            messages.append(ai_message) # 必须把 AI 刚才的“调用请求”存入历史
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result # 把“晴天，25度”发给大模型
            })
            
            print("🤖 AI 正在整理最终回答...")
            
            # 回合 4：让大模型结合工具结果，生成最终的自然语言回答
            final_response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages
            )
            
            print("\n🎉 最终回答:")
            print(final_response.choices[0].message.content)
    else:
        print("AI 直接回答了，没有使用工具:", ai_message.content)

if __name__ == "__main__":
    run_agent_with_tools()