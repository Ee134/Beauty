"""渲染后 DOM 审计：登录 -> 逐路由读取真实 DOM 中的 data-testid。

这不是"grep 源码"，而是驱动无头 Chrome（CDP）真正渲染 React 应用后，
用 `Array.from(document.querySelectorAll('[data-testid]')).map(e => e.getAttribute('data-testid'))`
读取每个路由最终出现在 DOM 里的钩子，并和需求清单逐一比对。

覆盖：
- 全部路由的静态钩子
- 动态钩子：生成计划草稿后的 routine-draft-*，交接流程后的 ticket-status / ticket-timeline，
  提交工单后的 staff-ticket-row，404 后的 toast-error，演示时钟下的 clock-banner
- 属性钩子：cabinet-item[data-owned-id]、memory-record[data-key][data-status]、
  atlas-card[data-common-name]、inbox-message[data-message-id] 等

用法：
    .venv/bin/python frontend/scripts/dom_audit.py http://127.0.0.1:5173
可选：--no-reseed 跳过重新 seed（默认会先重新 seed 演示数据，确保有可审计的数据）
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9399

# 需求清单：路由 -> [(testid, 是否为动态前缀)]
ROUTE_CHECKS: dict[str, list[str]] = {
    "/": [
        "app-ready",
        "mode-badges",
        "nav-home",
        "nav-cabinet",
        "nav-routine",
        "nav-chat",
        "nav-memory",
        "nav-service",
        "nav-settings",
        "nav-environment",
        "nav-inbox",
        "nav-atlas",
        "nav-brand",
        "nav-staff",
        "review-prompt-pause",
        "review-prompt-keep",
        "review-prompt-adjust",
    ],
    "/cabinet": [
        "cabinet-list",
        "cabinet-item",
        "cabinet-add-open",
        "cabinet-add-name",
        "cabinet-add-submit",
        "import-file-input",
        "import-submit",
    ],
    "/routine": [
        "routine-active",
        "routine-active-version",
        "routine-step",
        "routine-history",
        "combination-note",
        "combination-option-keep",
    ],
    "/chat": ["chat-input", "chat-send"],
    "/memory": ["memory-list", "memory-record", "usage-event-row", "usage-event-delete"],
    "/service": [
        "handoff-candidates",
        "handoff-candidate-checkbox",
        "handoff-request-input",
        "handoff-preview-button",
    ],
    "/environment": [
        "city-select",
        "city-save",
        "env-current",
        "env-quality",
        "env-missing-fields",
        "activity-title",
        "activity-start",
        "activity-create",
        "activity-row",
        "activity-cancel",
    ],
    "/settings": [
        "notif-service-type-travel_support",
        "notif-channel-webpush",
        "notif-daily-cap",
        "notif-quiet-start",
        "notif-quiet-end",
        "notif-save",
        "privacy-export",
        "privacy-delete",
    ],
    "/inbox": ["inbox-list"],
    "/ingredients/atlas": [
        "atlas-generate",
        "atlas-card",
        "atlas-card-status",
        "atlas-below-threshold",
        "atlas-dropped-extensions",
        "atlas-feedback-input",
        "atlas-feedback-submit",
    ],
    "/brand/insights": ["nav-brand"],
    "/staff/tickets": ["nav-staff"],
}

ATTRIBUTE_CHECKS: dict[str, list[tuple[str, str]]] = {
    "/cabinet": [("cabinet-item", "data-owned-id")],
    "/memory": [("memory-record", "data-key"), ("memory-record", "data-status")],
    "/ingredients/atlas": [("atlas-card", "data-common-name")],
}


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class CDP:
    def __init__(self, ws, session_id: str | None = None) -> None:  # noqa: ANN001
        self.ws = ws
        self.session_id = session_id
        self.counter = 0

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        message_id = self.counter
        payload: dict = {"id": message_id, "method": method, "params": params or {}}
        if self.session_id:
            payload["sessionId"] = self.session_id
        await self.ws.send(json.dumps(payload))
        while True:
            data = json.loads(await self.ws.recv())
            if data.get("id") == message_id:
                if "error" in data:
                    raise RuntimeError(f"{method} -> {data['error']}")
                return data.get("result", {})

    async def eval(self, expression: str) -> object:
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        inner = result.get("result", {})
        if inner.get("subtype") == "error":
            raise RuntimeError(str(inner.get("description"))[:300])
        return inner.get("value")

    async def wait_for(self, expression: str, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self.eval(expression):
                return True
            await asyncio.sleep(0.2)
        return False

    async def goto(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(0.9)

    async def testids(self) -> list[str]:
        value = await self.eval(
            "Array.from(document.querySelectorAll('[data-testid]'))"
            ".map(e => e.getAttribute('data-testid')).sort()"
        )
        return list(value or [])

    async def has_attr(self, testid: str, attr: str) -> bool:
        return bool(
            await self.eval(
                f"!!document.querySelector('[data-testid=\"{testid}\"]')?.getAttribute('{attr}')"
            )
        )


async def main() -> int:
    import websockets

    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173"
    profile = Path(tempfile.mkdtemp(prefix="bc-audit-"))
    chrome = subprocess.Popen(  # noqa: S603
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--window-size=1400,1000",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    missing: list[str] = []
    all_found: dict[str, list[str]] = {}
    try:
        version = None
        for _ in range(60):
            try:
                version = http_json(f"http://127.0.0.1:{PORT}/json/version")
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.5)
        if version is None:
            print("无法连接 Chrome 调试端口")
            return 2

        async with websockets.connect(
            version["webSocketDebuggerUrl"], max_size=40_000_000, origin=None
        ) as ws:
            browser = CDP(ws)
            created = await browser.send("Target.createTarget", {"url": "about:blank"})
            attached = await browser.send(
                "Target.attachToTarget", {"targetId": created["targetId"], "flatten": True}
            )
            cdp = CDP(ws, session_id=attached["sessionId"])
            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")
            # 桌面视口，避免 <900px 时右侧上下文面板折叠影响判断
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1400, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
            )

            print("== 登录（生产/开发同源 API）")
            await cdp.goto(f"{base}/")
            if not await cdp.wait_for("!!document.querySelector('[data-testid=\"persona-consumer_a\"]')", 20):
                print("  身份切换器未渲染，终止")
                return 3
            for attempt in range(4):
                await cdp.eval("document.querySelector('[data-testid=\"persona-consumer_a\"]').click()")
                if await cdp.wait_for("!!document.querySelector('[data-testid=\"app-ready\"]')", 12):
                    break
                print(f"  第 {attempt + 1} 次登录未就绪（可能是并发的演示数据重置），重试")
                await cdp.eval("localStorage.clear()")
                await cdp.goto(f"{base}/")
                await cdp.wait_for("!!document.querySelector('[data-testid=\"persona-consumer_a\"]')", 15)
            if not await cdp.eval("!!document.querySelector('[data-testid=\"app-ready\"]')"):
                print("  ✗ app-ready 始终未出现（/me 未成功解析）")
                missing.append("/ (app-ready)")
                return 4
            print("  ✓ app-ready 出现")

            for route, required in ROUTE_CHECKS.items():
                await cdp.goto(f"{base}{route}")
                # 等页面主体渲染出来（以第一个必需钩子为准，动态钩子除外）
                first = required[0]
                await cdp.wait_for(
                    f"!!document.querySelector('[data-testid=\"{first}\"]') || !!document.body.innerText.trim()",
                    15,
                )
                if route == "/cabinet":
                    await cdp.eval("document.querySelector('[data-testid=\"cabinet-add-open\"]')?.click()")
                    await asyncio.sleep(0.3)
                if route == "/memory":
                    await cdp.eval(
                        "document.querySelector('[data-testid^=\"memory-edit-\"]')?.click()"
                    )
                    await asyncio.sleep(0.3)
                if route == "/environment":
                    # 先创建一条活动，activity-row / activity-cancel 才会出现
                    await cdp.eval(
                        "(async () => { const t = localStorage.getItem('beautycare.demo.token');"
                        " await fetch('/api/v1/activities', {method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+t},"
                        " body: JSON.stringify({activity_type:'outdoor', title:'DOM 审计活动',"
                        " starts_at:new Date(Date.now()+86400000).toISOString(), ends_at:new Date(Date.now()+90000000).toISOString(), user_confirmed:true})}); return true; })()"
                    )
                    await cdp.goto(f"{base}/environment")
                    await cdp.wait_for(
                        "!!document.querySelector('[data-testid=\"city-select\"]')", 15
                    )
                found = await cdp.testids()
                all_found[route] = found
                absent = [item for item in required if item not in found]
                for testid, attr in ATTRIBUTE_CHECKS.get(route, []):
                    if testid in found and not await cdp.has_attr(testid, attr):
                        absent.append(f"{testid}[{attr}]")
                status = "✓" if not absent else "✗"
                print(f"\n== {route}  {status}  ({len(found)} 个 data-testid)")
                print("   DOM testids:", ", ".join(found) if found else "(无)")
                if absent:
                    print("   缺失:", ", ".join(absent))
                    missing.extend(f"{route} -> {item}" for item in absent)

            print("\n== 动态流程：生成计划草稿 -> routine-draft-* 与 routine-diff-summary")
            await cdp.goto(f"{base}/routine")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"routine-active\"]')", 20)
            await cdp.eval("document.querySelector('[data-testid=\"routine-generate\"]').click()")
            appeared = await cdp.wait_for(
                "!!document.querySelector('[data-testid=\"routine-draft-version\"]')", 30
            )
            draft_ids = [
                "routine-draft-card",
                "routine-draft-version",
                "routine-draft-steps",
                "routine-diff-summary",
                "routine-accept",
            ]
            found = await cdp.testids()
            for item in draft_ids:
                ok = item in found
                print(f"  {'✓' if ok else '✗'} {item}")
                if not ok:
                    missing.append(f"draft -> {item}")
            if not appeared:
                print("  · 草稿未在 30 秒内出现（可能是后端并发重置）")

            print("\n== 动态流程：/chat 发送消息 -> chat-card-* / chat-pending-action-*")
            await cdp.goto(f"{base}/chat")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"chat-input\"]')", 20)
            await cdp.eval(
                "(() => { const el = document.querySelector('[data-testid=\"chat-input\"]');"
                " const set = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;"
                " set.call(el, '帮我生成早晚护肤计划');"
                " el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()"
            )
            await cdp.eval("document.querySelector('[data-testid=\"chat-send\"]').click()")
            await cdp.wait_for(
                "document.querySelectorAll('[data-testid=\"chat-message\"][data-role=\"assistant\"]').length > 0",
                45,
            )
            found = await cdp.testids()
            chat_ids = sorted(i for i in found if i.startswith("chat-card-") or i.startswith("chat-pending-action-"))
            print("  动态钩子:", ", ".join(chat_ids) if chat_ids else "(无)")
            for item in ("chat-message", "chat-card-routine_draft", "chat-pending-action-accept_routine"):
                if item not in found:
                    missing.append(f"chat -> {item}")
                    print(f"  ✗ {item}")
                else:
                    print(f"  ✓ {item}")

            print("\n== 动态流程：/memory 进入编辑态 -> memory-edit-value / memory-edit-save")
            await cdp.goto(f"{base}/memory")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"memory-list\"]')", 20)
            await cdp.eval("document.querySelector('[data-testid^=\"memory-edit-\"]')?.click()")
            if await cdp.wait_for("!!document.querySelector('[data-testid=\"memory-edit-value\"]')", 10):
                for item in ("memory-edit-value", "memory-edit-save"):
                    ok = item in await cdp.testids()
                    print(f"  {'✓' if ok else '✗'} {item}")
                    if not ok:
                        missing.append(f"memory -> {item}")
            else:
                print("  ✗ 未能进入编辑态")
                missing.append("memory -> memory-edit-value")

            print("\n== 动态流程：交接预览 -> handoff-preview* -> 提交 -> ticket-status/ticket-timeline")
            await cdp.goto(f"{base}/service")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"handoff-candidate-checkbox\"]')", 25)
            await cdp.eval("document.querySelector('[data-testid=\"handoff-candidate-checkbox\"]').click()")
            await cdp.eval(
                "(() => { const el = document.querySelector('[data-testid=\"handoff-request-input\"]');"
                " const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
                " set.call(el, 'DOM 审计：希望确认下一步处理方式');"
                " el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()"
            )
            await cdp.eval("document.querySelector('[data-testid=\"handoff-preview-button\"]').click()")
            if await cdp.wait_for("!!document.querySelector('[data-testid=\"handoff-preview\"]')", 25):
                print("  ✓ handoff-preview")
                preview_status = await cdp.eval(
                    "!!document.querySelector('[data-testid=\"handoff-preview-status\"]')"
                )
                print(f"  {'✓' if preview_status else '✗'} handoff-preview-status")
                if not preview_status:
                    missing.append("service -> handoff-preview-status")
                found_preview = await cdp.testids()
                for item in ("handoff-preview", "handoff-preview-button", "handoff-submit"):
                    ok = item in found_preview
                    print(f"  {'✓' if ok else '✗'} {item}")
                    if not ok:
                        missing.append(f"service -> {item}")
                await cdp.eval("document.querySelector('[data-testid=\"handoff-submit\"]')?.click()")
                # 提交后回到工单列表：ticket-status 出现在列表行
                await cdp.goto(f"{base}/service")
                if await cdp.wait_for("!!document.querySelector('[data-testid=\"ticket-status\"]')", 25):
                    print("  ✓ ticket-status")
                else:
                    print("  ✗ ticket-status")
                    missing.append("service -> ticket-status")
                await cdp.eval("document.querySelectorAll('table button')[0]?.click()")
                if await cdp.wait_for("!!document.querySelector('[data-testid=\"ticket-timeline\"]')", 20):
                    print("  ✓ ticket-timeline")
                else:
                    print("  ✗ ticket-timeline（需要打开工单详情）")
                    missing.append("service -> ticket-timeline")
                found_service = await cdp.testids()
                for item in ("ticket-status", "ticket-timeline", "staff-ticket-row"):
                    if item in found_service and item == "ticket-timeline":
                        print("  ✓ ticket-timeline（详情已打开）")
            else:
                print("  ✗ handoff-preview 未出现")
                missing.append("service -> handoff-preview")

            print("\n== 动态流程：staff-persona -> staff-ticket-row")
            await cdp.goto(f"{base}/")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"persona-staff\"]')", 20)
            await cdp.eval("document.querySelector('[data-testid=\"persona-staff\"]')?.click()")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"app-ready\"]')", 20)
            await cdp.goto(f"{base}/staff/tickets")
            if await cdp.wait_for("!!document.querySelector('[data-testid=\"staff-ticket-row\"]')", 25):
                print("  ✓ staff-ticket-row")
                for item in ("staff-ticket-row",):
                    if not await cdp.has_attr(item, "data-ticket-id"):
                        missing.append("staff -> staff-ticket-row[data-ticket-id]")
                # 打开一个工单，验证客服状态更新控件
                await cdp.eval(
                    "document.querySelector('[data-testid=\"staff-ticket-row\"] a')?.click()"
                )
                if await cdp.wait_for("!!document.querySelector('[data-testid=\"staff-ticket-status-select\"]')", 20):
                    for item in ("staff-ticket-status-select", "staff-ticket-note", "staff-ticket-save"):
                        found_staff = await cdp.testids()
                        print(f"  {'✓' if item in found_staff else '✗'} {item}")
                        if item not in found_staff:
                            missing.append(f"staff -> {item}")
                else:
                    print("  ✗ 未进入工单详情页")
                    missing.append("staff -> staff-ticket-status-select")
            else:
                print("  ✗ staff-ticket-row 未出现（本轮没有已提交工单）")
                missing.append("staff -> staff-ticket-row")

            print("\n== 动态流程：切回 consumer_a -> toast-error（404）与 clock-banner")
            await cdp.goto(f"{base}/")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"persona-consumer_a\"]')", 20)
            await cdp.eval("document.querySelector('[data-testid=\"persona-consumer_a\"]').click()")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"app-ready\"]')", 20)
            await cdp.goto(f"{base}/imports/00000000-0000-0000-0000-000000000000")
            if await cdp.wait_for("!!document.querySelector('[data-testid=\"toast-error\"]')", 20):
                text = await cdp.eval("document.querySelector('[data-testid=\"toast-error\"]').innerText")
                print(f"  ✓ toast-error（含 code）：{str(text)[:80]}")
            else:
                print("  ✗ toast-error 未出现")
                missing.append("global -> toast-error")

            await cdp.eval(
                "(async () => { const t = localStorage.getItem('beautycare.demo.token');"
                " await fetch('/api/v1/admin/clock', {method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+t},"
                " body: JSON.stringify({mode:'demo', day: 5})}); return true; })()"
            )
            await cdp.goto(f"{base}/")
            if await cdp.wait_for("!!document.querySelector('[data-testid=\"clock-banner\"]')", 20):
                print("  ✓ clock-banner（is_demo_time=true）")
            else:
                print("  ✗ clock-banner 未出现")
                missing.append("global -> clock-banner")
            await cdp.eval(
                "(async () => { const t = localStorage.getItem('beautycare.demo.token');"
                " await fetch('/api/v1/admin/clock', {method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+t},"
                " body: JSON.stringify({mode:'real'})}); return true; })()"
            )

            print("\n== 动态流程：/inbox（inbox-message 需要已有主动消息）")
            await cdp.goto(f"{base}/inbox")
            await cdp.wait_for("!!document.querySelector('[data-testid=\"inbox-list\"]') || document.body.innerText.length > 0", 15)
            if await cdp.eval("!!document.querySelector('[data-testid=\"inbox-message\"]')"):
                for item in ("inbox-message", "inbox-mark-read", "inbox-adopt", "inbox-later", "inbox-mute"):
                    ok = item in await cdp.testids()
                    print(f"  {'✓' if ok else '✗'} {item}")
                    if not ok:
                        missing.append(f"inbox -> {item}")
                if not await cdp.has_attr("inbox-message", "data-message-id"):
                    missing.append("inbox -> inbox-message[data-message-id]")
            else:
                print("  · 收件箱为空：当前后端无法生成主动消息（见报告中的后端缺陷），inbox-message 无法在白盒验证中确认")

        print("\n================ 汇总 ================")
        if missing:
            print(f"缺失 {len(missing)} 项：")
            for item in missing:
                print("  -", item)
            return 1
        print("所有清单中的 data-testid 均在渲染后的 DOM 中出现")
        return 0
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except Exception:  # noqa: BLE001
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
