"""LLM 客户端，封装 OpenAI 兼容调用，支持 SenseNova。"""

import os
import json
import time
from typing import Optional, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

load_dotenv()

T = TypeVar("T", bound=BaseModel)


class LLMResponse:
    """LLM 调用结果，包含内容、模型名、token 用量与耗时。"""

    def __init__(
        self,
        content: str,
        model: str,
        usage: dict,
        duration_ms: int,
        finish_reason: str = "",
    ):
        self.content = content
        self.model = model
        self.usage = usage  # {"input": int, "output": int}
        self.duration_ms = duration_ms
        self.finish_reason = finish_reason


class LLMClient:
    """OpenAI 兼容客户端，默认从环境变量读取 SenseNova 配置。"""

    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or os.getenv("SENSENOVA_API_KEY")
        self.base_url = base_url or os.getenv("SENSENOVA_BASE_URL")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict = None,
        reasoning_effort: str = None,
    ) -> LLMResponse:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        start = time.time()
        resp = self.client.chat.completions.create(**kwargs)
        duration_ms = int((time.time() - start) * 1000)
        choice = resp.choices[0]
        content = choice.message.content or ""
        finish_reason = choice.finish_reason or ""
        usage = {
            "input": resp.usage.prompt_tokens if resp.usage else 0,
            "output": resp.usage.completion_tokens if resp.usage else 0,
        }
        return LLMResponse(
            content=content,
            model=model,
            usage=usage,
            duration_ms=duration_ms,
            finish_reason=finish_reason,
        )

    def chat_json(
        self,
        model: str,
        messages: list,
        output_schema: Type[T],
        temperature: float = 0.3,
        max_tokens: int = 8192,
        reasoning_effort: str = None,
    ) -> tuple[BaseModel, LLMResponse]:
        """调用 LLM 并解析为 Pydantic 模型。失败时抛出 ValueError。

        降级策略：
        1. 先用 response_format=json_object 模式调用。
        2. 若返回空内容（SenseNova JSON 模式在复杂提示词下可能返回空），
           降级为不带 response_format 重试（靠提示词约束 + markdown 剥离）。
        3. 若 finish_reason=length（被截断），用更大 max_tokens 重试。
        """
        import re

        llm_resp = self.chat(
            model,
            messages,
            temperature,
            max_tokens,
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
        )

        # 空响应：降级为不带 response_format（SenseNova JSON 模式 bug 的 workaround）
        if not llm_resp.content.strip():
            llm_resp = self.chat(
                model,
                messages,
                temperature,
                max_tokens,
                response_format=None,
                reasoning_effort=reasoning_effort,
            )

        # 被截断：用更大 max_tokens 重试（不带 response_format，避免 JSON 模式空响应）
        if llm_resp.finish_reason == "length" and not llm_resp.content.strip():
            llm_resp = self.chat(
                model,
                messages,
                temperature,
                max_tokens * 2,
                response_format=None,
                reasoning_effort=reasoning_effort,
            )

        raw = llm_resp.content.strip()
        # 去除markdown代码块标记 ```json ... ``` 或 ``` ... ```
        if raw.startswith("```"):
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
        try:
            data = json.loads(raw)
            return output_schema.model_validate(data), llm_resp
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(
                f"LLM输出JSON解析失败: {e}\n"
                f"finish_reason: {llm_resp.finish_reason}\n"
                f"原始输出: {llm_resp.content[:500]}"
            )
