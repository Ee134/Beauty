"""Model provider adapters.

`mock` is a deterministic local implementation, clearly labelled and never
presented as real recognition or a real model call.
`live` calls an OpenAI-compatible chat completions endpoint. Without
credentials it is explicitly unavailable (`MODEL_UNAVAILABLE`) — it never
silently falls back to mock.

Both modes run through the same orchestration, tools and validation code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings
from ..services.errors import InvalidModelOutputError, ModelUnavailableError


@dataclass
class ModelResponse:
    payload: dict[str, Any]
    latency_ms: int
    usage: dict[str, Any]
    raw_text: str = ""


class ModelProvider(Protocol):
    mode: str
    provider: str
    name: str
    available: bool

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        images: list[dict[str, str]] | None = None,
    ) -> ModelResponse: ...


class MockModelProvider:
    """Deterministic local brain. No network. Explicitly labelled as mock."""

    mode = "mock"
    provider = "mock"
    name = "mock-deterministic-v1"
    available = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        images: list[dict[str, str]] | None = None,
    ) -> ModelResponse:
        import time

        from ..agent import mock_brain

        started = time.perf_counter()
        if schema_name == "PlannerOutput":
            payload = mock_brain.plan(user_payload)
        elif schema_name == "ComposeOutput":
            payload = mock_brain.compose(user_payload)
        elif schema_name == "ImportExtraction":
            payload = mock_brain.extract_import(user_payload)
        else:
            raise InvalidModelOutputError(f"mock 模式不支持的输出 schema：{schema_name}")
        latency = int((time.perf_counter() - started) * 1000)
        return ModelResponse(
            payload=payload,
            latency_ms=max(latency, 1),
            usage={"mode": "mock", "tokens": None, "note": "确定性 mock，不产生真实模型调用"},
            raw_text=json.dumps(payload, ensure_ascii=False),
        )


class OpenAICompatibleProvider:
    """Live adapter. Same request/validation path as mock; different transport."""

    mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.model_provider or "openai_compatible"
        self.name = self.settings.model_name or "(未配置)"

    @property
    def available(self) -> bool:
        return self.settings.model_ready

    def _endpoint(self) -> str:
        base = self.settings.api_base.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        images: list[dict[str, str]] | None = None,
    ) -> ModelResponse:
        import time

        if not self.available:
            raise ModelUnavailableError(
                "live 模式未配置可用的模型凭据（需要 API_BASE、API_KEY、MODEL_NAME）。"
                "可显式切换到 MODEL_MODE=mock。",
                details={"provider": self.provider, "model": self.settings.model_name},
            )
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)}
        ]
        for image in images or []:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image['mime']};base64,{image['data']}"},
                }
            )
        body = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content if images else json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": False},
            },
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.settings.model_timeout_seconds) as client:
                response = client.post(
                    self._endpoint(),
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ModelUnavailableError(
                "模型调用超时，未产生任何写入。", details={"timeout_seconds": self.settings.model_timeout_seconds}
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailableError(
                "模型服务返回错误状态。",
                details={"status": exc.response.status_code},
                retryable=exc.response.status_code >= 500,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailableError(
                "模型服务不可用。", details={"error": type(exc).__name__}
            ) from exc
        latency = int((time.perf_counter() - started) * 1000)
        try:
            text = data["choices"][0]["message"]["content"]
            payload = json.loads(text) if isinstance(text, str) else text
        except Exception as exc:  # noqa: BLE001
            raise InvalidModelOutputError("模型返回的内容不是合法的 JSON 对象。") from exc
        if not isinstance(payload, dict):
            raise InvalidModelOutputError("模型返回的 JSON 顶层必须是对象。")
        return ModelResponse(
            payload=payload,
            latency_ms=latency,
            usage=data.get("usage") or {},
            raw_text=text if isinstance(text, str) else json.dumps(payload, ensure_ascii=False),
        )


def get_model_provider(settings: Settings | None = None) -> ModelProvider:
    settings = settings or get_settings()
    if settings.model_mode == "live":
        return OpenAICompatibleProvider(settings)
    return MockModelProvider(settings)


def model_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = get_model_provider(settings)
    return {
        "mode": settings.model_mode,
        "provider": getattr(provider, "provider", "mock"),
        "name": getattr(provider, "name", "mock"),
        "available": bool(getattr(provider, "available", True)),
        "is_mock": settings.model_mode == "mock",
        "notice": (
            "mock 模式：使用确定性 fixtures，不声称真实识别或真实模型能力。"
            if settings.model_mode == "mock"
            else (
                "live 模式已配置。"
                if settings.model_ready
                else "live 模式缺少凭据，当前不可用；可显式切换到 mock。"
            )
        ),
        "vision_mode": settings.vision_mode,
        "ocr_mode": settings.ocr_mode,
        "timeout_seconds": settings.model_timeout_seconds,
        "turn_budget_seconds": settings.turn_budget_seconds,
        "max_tool_calls_per_turn": settings.max_tool_calls_per_turn,
    }
