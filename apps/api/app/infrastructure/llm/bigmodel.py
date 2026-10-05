import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError


class BigModelProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_vision(
        self,
        messages: Sequence[dict[str, Any]],
        images: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        self._ensure_enabled("图片理解")
        multimodal_messages = [dict(item) for item in messages]
        for index in range(len(multimodal_messages) - 1, -1, -1):
            if multimodal_messages[index].get("role") != "user":
                continue
            text = str(multimodal_messages[index].get("content") or "请描述这些图片")
            multimodal_messages[index]["content"] = [
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": image["base64"]},
                    }
                    for image in images
                ],
                {"type": "text", "text": text},
            ]
            break

        url = f"{self.settings.bigmodel_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.bigmodel_vision_model,
            "messages": multimodal_messages,
            "thinking": {"type": "disabled"},
            "stream": True,
        }
        async for chunk in self._stream(url, payload):
            yield chunk

    async def generate_image(self, prompt: str, size: str = "1280x1280") -> list[str]:
        self._ensure_enabled("图片生成")
        url = f"{self.settings.bigmodel_base_url.rstrip('/')}/images/generations"
        payload = {
            "model": self.settings.bigmodel_image_model,
            "prompt": prompt[:1000],
            "size": size,
            "quality": "hd",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.post(url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                raise self._provider_error(response, "图片生成服务暂时不可用")
            urls = [str(item["url"]) for item in response.json().get("data", []) if item.get("url")]
            if not urls:
                raise AppError(
                    "IMAGE_GENERATION_EMPTY",
                    "图片生成服务未返回图片",
                    status_code=502,
                    retryable=True,
                )
            return urls
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError(
                "BIGMODEL_PROVIDER_ERROR",
                "连接图片生成服务失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc

    async def _stream(self, url: str, payload: dict[str, Any]) -> AsyncIterator[str]:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout()) as client,
                client.stream("POST", url, headers=self._headers(), json=payload) as response,
            ):
                if response.status_code >= 400:
                    error_text = (await response.aread()).decode(errors="replace")[:500]
                    raise AppError(
                        "BIGMODEL_PROVIDER_ERROR",
                        "视觉模型服务暂时不可用",
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
                "BIGMODEL_PROVIDER_ERROR",
                "连接视觉模型失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc

    def _ensure_enabled(self, capability: str) -> None:
        if not self.settings.bigmodel_enabled:
            raise AppError(
                "BIGMODEL_PROVIDER_DISABLED",
                f"{capability}尚未配置，请填写 BIGMODEL_API_KEY 并关闭演示模式",
                status_code=503,
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.bigmodel_api_key}",
            "Content-Type": "application/json",
        }

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.settings.bigmodel_timeout_seconds, connect=10.0)

    @staticmethod
    def _provider_error(response: httpx.Response, message: str) -> AppError:
        return AppError(
            "BIGMODEL_PROVIDER_ERROR",
            message,
            status_code=502,
            details=[{"provider_status": response.status_code}],
            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
        )
