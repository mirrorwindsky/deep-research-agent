# services/llm.py

"""
大模型服务封装模块。

模块职责：
1. 统一封装模型客户端初始化逻辑
2. 提供 research workflow 中使用的大模型调用接口
3. 将底层模型 SDK 细节与节点层逻辑解耦

设计目标：
1. 避免在多个节点函数中重复编写模型调用代码
2. 避免 main.py 直接承担模型初始化职责
3. 为后续扩展 JSON 模式、重试机制、结构化输出等能力保留统一入口

说明：
- 当前版本保持最小实现，只提供基础 chat 接口
- 当前模型调用方式基于 OpenAI 兼容接口
- 若后续切换模型服务商，只需集中修改本模块
"""

from typing import Iterator

from openai import OpenAI

from config import API_KEY, BASE_URL, MODEL_NAME


class LLMService:
    """
    大模型服务封装类。

    当前提供的核心能力：
    - chat(system_prompt, user_prompt) -> str
    - chat_stream(system_prompt, user_prompt) -> Iterator[str]

    设计说明：
    - 节点层只依赖该类的高层接口
    - 模型初始化、接口地址、模型名称等细节集中在本类内部处理
    - 当前实现保持简单，优先服务第一阶段 workflow 主链
    """

    def __init__(self) -> None:
        """
        初始化模型客户端。

        初始化内容：
        - 校验 API_KEY 是否存在
        - 创建 OpenAI 兼容客户端
        - 记录当前使用的模型名称

        异常说明：
        - 若未检测到 API_KEY，则直接抛出错误
        - 该行为有助于在程序启动早期暴露配置问题
        """
        if not API_KEY:
            raise ValueError("未检测到 DEEPSEEK_API_KEY，请先在 .env 中配置。")

        # 使用 OpenAI 官方 SDK 的兼容接口方式调用模型。
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        self.model = MODEL_NAME

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用一次基础聊天接口。

        参数：
        - system_prompt:
            系统提示词，用于定义模型角色、输出规则与行为边界
        - user_prompt:
            当前任务输入，通常由节点函数动态组织

        返回：
        - 模型输出的纯文本字符串
        - 若响应内容为空，则返回空字符串

        当前调用策略：
        - 使用标准 chat completions 接口
        - temperature 固定为较低值，以优先保证输出稳定性

        设计说明：
        - 当前 research workflow 更强调稳定、可重复的行为
        - 因此默认采用较低 temperature，而非追求发散性输出
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # 较低 temperature 通常意味着更稳定的输出。
            # 对 research workflow 而言，当前阶段优先保证稳定性。
            temperature=0.2,
        )

        content = response.choices[0].message.content
        return content.strip() if content else ""

    def chat_stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """
        调用一次流式聊天接口。

        参数：
        - system_prompt:
            系统提示词，用于定义模型角色、输出规则与行为边界。
        - user_prompt:
            当前任务输入，通常由节点函数动态组织。

        返回：
        - 逐段产出的文本 iterator。

        设计说明：
        - 该接口主要服务 CLI 最终报告流式展示。
        - 调用方仍应自行累积完整文本，供后续引用修复、校验和 artifact 保存使用。
        """
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue

            content = chunk.choices[0].delta.content
            if content:
                yield content
