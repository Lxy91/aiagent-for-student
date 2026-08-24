import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError


class DeepSeekProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_chat(self, messages: Sequence[dict[str, Any]]) -> AsyncIterator[str]:
        if not self.settings.deepseek_enabled:
            async for chunk in self._demo_stream(messages):
                yield chunk
            return

        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.deepseek_model,
            "messages": list(messages),
            "thinking": {"type": "disabled"},
            "stream": True,
        }
        timeout = httpx.Timeout(self.settings.deepseek_timeout_seconds, connect=10.0)
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                if response.status_code >= 400:
                    error_text = (await response.aread()).decode(errors="replace")[:500]
                    raise AppError(
                        "MODEL_PROVIDER_ERROR",
                        "模型服务暂时不可用",
                        status_code=502,
                        details=[{"provider_status": response.status_code, "body": error_text}],
                        retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                    )
                async for line in response.aiter_lines():
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if content:
                        yield content
        except AppError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise AppError(
                "MODEL_PROVIDER_ERROR",
                "连接模型服务失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc

    async def select_tool_calls(
        self,
        messages: Sequence[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        force_tool_name: str | None = None,
        allow_tool_calls: bool = True,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Ask DeepSeek to select tools before the final streamed response."""
        if not self.settings.deepseek_enabled or (not tools and allow_tool_calls):
            return None, []

        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.deepseek_model,
            "messages": list(messages),
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = (
                "none"
                if not allow_tool_calls
                else (
                    {"type": "function", "function": {"name": force_tool_name}}
                    if force_tool_name
                    else "auto"
                )
            )
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.deepseek_timeout_seconds, connect=10.0)
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise AppError(
                    "MODEL_PROVIDER_ERROR",
                    "模型工具规划暂时不可用",
                    status_code=502,
                    details=[{"provider_status": response.status_code}],
                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                )
            body = response.json()
            message = body.get("choices", [{}])[0].get("message") or {}
            calls = message.get("tool_calls") or []
            return message or None, calls
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError(
                "MODEL_PROVIDER_ERROR",
                "连接模型工具规划服务失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc

    async def complete_json(
        self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 2400
    ) -> dict[str, Any]:
        if not self.settings.deepseek_enabled:
            raise AppError("MODEL_PROVIDER_DISABLED", "模型服务未启用", status_code=503)
        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.deepseek_model,
            "messages": list(messages),
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.deepseek_timeout_seconds, connect=10.0)
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise AppError(
                    "MODEL_PROVIDER_ERROR",
                    "模型结构化生成暂时不可用",
                    status_code=502,
                    details=[{"provider_status": response.status_code}],
                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                )
            content = response.json().get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                raise AppError(
                    "MODEL_EMPTY_RESPONSE", "模型未返回计划内容", status_code=502, retryable=True
                )
            return json.loads(content)
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AppError(
                "MODEL_PROVIDER_ERROR",
                "模型结构化结果解析失败",
                status_code=502,
                retryable=True,
            ) from exc

    async def _demo_stream(self, messages: Sequence[dict[str, Any]]) -> AsyncIterator[str]:
        question = next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "这个问题",
        )
        response = (
            f"你提到“{question[:30]}”。建议先明确目标、交付物和截止时间，再把最关键的"
            "不确定点整理成一个具体问题。\n\n你可以这样表达：‘我先复述一下目前的理解，"
            "也准备了一个初步方案，想请您确认优先级是否正确。’\n\n当前为演示模式；配置 DeepSeek "
            "API Key 后会返回实时模型结果。"
        )
        for start in range(0, len(response), 18):
            yield response[start : start + 18]
