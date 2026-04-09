from openai import OpenAI
from config import API_KEY, BASE_URL, MODEL_NAME


class LLMService:
    """
    这是一个非常简单的大模型服务封装类。

    当前只提供一个最基础的方法：
    - chat(system_prompt, user_prompt) -> str

    这样做的好处是：
    1. main.py 不需要关心模型初始化细节
    2. 节点函数不需要重复写 API 调用代码
    3. 以后你要换模型、加 JSON 模式、加重试逻辑时，只需要改这里
    """

    def __init__(self) -> None:
        """
        初始化模型客户端。
        """
        if not API_KEY:
            raise ValueError("未检测到 DEEPSEEK_API_KEY，请先在 .env 中配置。")

        # 使用 OpenAI 官方 SDK 的兼容接口方式调用模型
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        self.model = MODEL_NAME

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用一次最基础的聊天接口。

        参数：
        - system_prompt: 系统提示词，定义模型的角色和规则
        - user_prompt: 用户输入，或当前节点要让模型处理的内容

        返回：
        - 模型输出的纯文本字符串
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # temperature 越低，输出通常越稳定
            # 对 research workflow 来说，先优先要稳定而不是发散
            temperature=0.2,
        )

        content = response.choices[0].message.content
        return content.strip() if content else ""