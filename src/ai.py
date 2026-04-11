# -*- coding: utf-8 -*-
"""通用 AI 调用模块。

目标：
    让自动回复场景只需要传入 base_url、api_format、model、api_key 即可使用。

支持格式：
    - completions: OpenAI-compatible /chat/completions
    - responses: OpenAI Responses API
    - anthropic: Anthropic-compatible /messages
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from .features.messaging.listener import MessageEvent

ApiFormat = Literal["completions", "responses", "anthropic"]


DEFAULT_SYSTEM_PROMPT = """你正在微信群聊里回复消息。
要求：
1. 回复自然、简短，像真人聊天。
2. 不要说自己是 AI。
3. 不要每次都解释太多。
4. 如果消息不需要回复，可以只返回空字符串。
"""


@dataclass(frozen=True)
class AIConfig:
    """AI 接口配置。"""

    base_url: str
    model: str
    api_key: str
    api_format: ApiFormat = "completions"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.7
    max_tokens: int = 300
    timeout: float = 60.0
    enable_thinking: Optional[bool] = False


class AIClient:
    """轻量级 AI 客户端。"""

    def __init__(self, config: AIConfig):
        self.config = config
        self.api_format = self._normalize_api_format(config.api_format)
        self.url = self._build_endpoint(config.base_url, self.api_format)

    def chat(self, messages: List[dict], system_prompt: Optional[str] = None) -> str:
        """发送对话并返回文本回复。"""
        request = self._build_request(messages, system_prompt or self.config.system_prompt)
        headers = self._build_headers()

        http_request = urllib.request.Request(
            url=self.url,
            data=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_request, timeout=self.config.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(self._format_http_error(exc.code, body)) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.gaierror):
                raise RuntimeError(
                    f"AI 接口域名解析失败，请检查网络、DNS、代理或 base_url: {self.config.base_url}"
                ) from exc
            raise RuntimeError(f"AI 接口网络请求失败: {reason}") from exc

        result = self._extract_text(data)
        if not result:
            raise RuntimeError(f"AI 接口返回为空: {json.dumps(data, ensure_ascii=False)}")
        return self._sanitize_output(result)

    def _build_request(self, messages: List[dict], system_prompt: str) -> dict:
        if self.api_format == "completions":
            request = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            if self.config.enable_thinking is not None:
                request["enable_thinking"] = self.config.enable_thinking
            return request

        if self.api_format == "responses":
            return {
                "model": self.config.model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    *[
                        {
                            "role": message["role"],
                            "content": [{"type": "input_text", "text": message["content"]}],
                        }
                        for message in messages
                    ],
                ],
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_tokens,
            }

        if self.api_format == "anthropic":
            return {
                "model": self.config.model,
                "system": system_prompt,
                "messages": messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }

        raise ValueError(f"不支持的 api_format: {self.api_format}")

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Authorization": f"Bearer {self.config.api_key}",
        }

        if self.api_format == "anthropic":
            headers.pop("Authorization", None)
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = "2023-06-01"

        return headers

    def _extract_text(self, data: dict) -> str:
        if self.api_format == "completions":
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

        if self.api_format == "responses":
            if data.get("output_text"):
                return data["output_text"]
            for item in data.get("output", []) or []:
                for content in item.get("content", []) or []:
                    if content.get("type") == "output_text" and content.get("text"):
                        return content["text"]
            return ""

        if self.api_format == "anthropic":
            return "\n".join(
                item.get("text", "")
                for item in data.get("content", []) or []
                if item.get("type") == "text" and item.get("text")
            )

        return ""

    def _format_http_error(self, status: int, body: str) -> str:
        lower = body.lower()
        if status in (401, 403) and any(word in lower for word in ("api key", "apikey", "auth", "unauthorized", "permission")):
            return f"AI 认证失败，请检查 api_key。HTTP {status}: {body}"
        if status == 404:
            return f"AI endpoint 不存在，请检查 base_url 或 api_format。URL={self.url} HTTP {status}: {body}"
        if "model" in lower and any(word in lower for word in ("not found", "invalid", "not exist", "unsupported")):
            return f"AI 模型不可用，请检查 model。HTTP {status}: {body}"
        return f"AI HTTP 请求失败。URL={self.url} HTTP {status}: {body}"

    @staticmethod
    def _normalize_api_format(api_format: str) -> ApiFormat:
        if api_format == "response":
            return "responses"
        if api_format not in {"completions", "responses", "anthropic"}:
            raise ValueError("api_format must be one of: completions, responses, anthropic")
        return api_format  # type: ignore[return-value]

    @staticmethod
    def _build_endpoint(base_url: str, api_format: ApiFormat) -> str:
        if not base_url or not base_url.strip():
            raise ValueError("base_url must not be empty")

        normalized = base_url.strip()
        if not normalized.lower().startswith(("http://", "https://")):
            normalized = f"https://{normalized}"
        normalized = normalized.rstrip("/")
        path = AIClient._get_url_path(normalized)

        if api_format == "completions":
            if AIClient._has_path_suffix(path, ["/chat/completions", "/v1/chat/completions", "/completions", "/v1/completions"]):
                return normalized
            if AIClient._has_path_suffix(path, ["/v1"]):
                return f"{normalized}/chat/completions"
            return f"{normalized}/v1/chat/completions"

        if api_format == "responses":
            if AIClient._has_path_suffix(path, ["/responses", "/v1/responses"]):
                return normalized
            if AIClient._has_path_suffix(path, ["/v1"]):
                return f"{normalized}/responses"
            return f"{normalized}/v1/responses"

        if api_format == "anthropic":
            if AIClient._has_path_suffix(path, ["/messages", "/v1/messages"]):
                return normalized
            if AIClient._has_path_suffix(path, ["/v1"]):
                return f"{normalized}/messages"
            return f"{normalized}/v1/messages"

        raise ValueError(f"不支持的 api_format: {api_format}")

    @staticmethod
    def _get_url_path(url: str) -> str:
        marker = "://"
        if marker not in url:
            return ""
        path_start = url.find("/", url.find(marker) + len(marker))
        return url[path_start:] if path_start >= 0 else ""

    @staticmethod
    def _has_path_suffix(path: str, suffixes: List[str]) -> bool:
        return any(path == suffix or path.endswith(suffix) for suffix in suffixes)

    @staticmethod
    def _sanitize_output(text: str) -> str:
        return str(text or "").strip().strip("\"'")


class AIResponder:
    """面向微信群自动回复的 AI 回调封装。"""

    def __init__(
        self,
        client: AIClient,
        *,
        context_size: int = 8,
        reply_on_at: bool = True,
    ):
        self.client = client
        self.context_size = context_size
        self.reply_on_at = reply_on_at
        self.contexts: Dict[str, List[dict]] = {}

    def __call__(self, event: MessageEvent) -> str:
        if self.reply_on_at and not event.is_at_me:
            return ""

        content = self._strip_at(event.content, event.group_nickname)
        if not content:
            return ""

        context = self.contexts.setdefault(event.group, [])
        context.append({"role": "user", "content": content})
        del context[:-self.context_size]

        reply = self.client.chat(context)
        if reply:
            context.append({"role": "assistant", "content": reply})
            del context[:-self.context_size]
        return reply

    @staticmethod
    def _strip_at(content: str, nickname: Optional[str]) -> str:
        if not nickname:
            return content.strip()
        return (
            content
            .replace(f"@{nickname}\u2005", "")
            .replace(f"@{nickname}", "")
            .strip()
        )
