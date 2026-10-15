"""Notification channel adapters.

In-app messages are always available (P0). Web Push is a configurable P0 channel
and requires server service-authorization, a live subscription and channel
credentials; without credentials the mode is an explicit mock, never a fake
"delivered". `provider_accepted` never means delivered or read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings, get_settings
from ..services.errors import NotConfiguredError


@dataclass
class DeliveryResult:
    status: str  # provider_accepted | failed | cancelled | expired
    provider_id: str | None = None
    error: str | None = None
    provider_confirmed_receipt: bool = False
    notice: str | None = None


class InAppProvider:
    channel = "in_app"
    mode = "in_app"

    def deliver(self, message: Any, subscription: Any | None = None) -> DeliveryResult:
        return DeliveryResult(
            status="provider_accepted",
            provider_id=f"inapp-{message.id[:8]}",
            notice="已写入应用内 inbox（服务端已接受）。",
        )


class MockWebPushProvider:
    channel = "web_push"
    mode = "mock"

    def deliver(self, message: Any, subscription: Any | None = None) -> DeliveryResult:
        if subscription is None:
            return DeliveryResult(status="failed", error="NO_ACTIVE_SUBSCRIPTION")
        return DeliveryResult(
            status="provider_accepted",
            provider_id=f"mockpush-{message.id[:8]}",
            notice="mock 推送渠道：仅证明编排契约，未接入真实推送服务，也不代表设备已收到。",
        )


class WebPushProvider:
    channel = "web_push"
    mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not (self.settings.vapid_private_key and self.settings.vapid_public_key):
            raise NotConfiguredError(
                "未配置 VAPID 密钥，Web Push 不可用。可切换到 NOTIFICATION_MODE=mock_push 或 in_app。"
            )

    def deliver(self, message: Any, subscription: Any | None = None) -> DeliveryResult:
        if subscription is None:
            return DeliveryResult(status="failed", error="NO_ACTIVE_SUBSCRIPTION")
        try:
            from pywebpush import WebPushException, webpush  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise NotConfiguredError(
                "pywebpush 未安装，真实 Web Push 不可用。"
            ) from exc
        from ..services.crypto import decrypt

        payload = {"title": message.title, "body": message.body, "data": message.payload}
        try:
            response = webpush(
                subscription_info={
                    "endpoint": decrypt(subscription.endpoint_encrypted),
                    "keys": decrypt(subscription.keys_encrypted or "") or {},
                },
                data=__import__("json").dumps(payload, ensure_ascii=False),
                vapid_private_key=self.settings.vapid_private_key,
                vapid_claims={"sub": self.settings.vapid_subject},
                timeout=10,
            )
        except WebPushException as exc:  # pragma: no cover - requires real push service
            return DeliveryResult(status="failed", error=str(exc)[:280])
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            return DeliveryResult(status="failed", error=type(exc).__name__)
        return DeliveryResult(
            status="provider_accepted",
            provider_id=getattr(response, "status_code", None) and str(response.status_code) or "webpush",
            # A 201 from the push service is only "accepted by the push service".
            provider_confirmed_receipt=False,
            notice="推送服务已接受，不代表设备已展示或已读。",
        )


def get_provider(channel: str, settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    if channel == "in_app":
        return InAppProvider()
    if channel == "web_push":
        mode = settings.notification_mode
        if mode == "web_push":
            return WebPushProvider(settings)
        if mode == "mock_push":
            return MockWebPushProvider()
        return MockWebPushProvider()
    raise NotConfiguredError(f"未知通知渠道：{channel}")


def channel_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    mode = settings.notification_mode
    return {
        "mode": mode,
        "in_app": {"available": True, "mode": "in_app"},
        "web_push": {
            "available": mode in {"mock_push", "web_push"},
            "mode": "live" if mode == "web_push" else ("mock" if mode == "mock_push" else "disabled"),
            "has_vapid": bool(settings.vapid_private_key and settings.vapid_public_key),
            "notice": (
                "真实 Web Push 已配置。"
                if mode == "web_push"
                else "未配置 Web Push：当前为明确标注的 mock 渠道或已关闭。"
            ),
        },
        "native_push": {
            "available": False,
            "mode": "not_implemented",
            "notice": "原生 App 推送为 P1，本 MVP 未交付原生客户端。",
        },
    }
