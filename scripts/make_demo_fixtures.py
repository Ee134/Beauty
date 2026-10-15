"""Generate the built-in demo import fixtures (screenshots) and their manifest.

The images are synthetic and clearly labelled DEMO. In mock mode the import
pipeline recognises a file only by matching its sha256 against this manifest, so
it never pretends to read an arbitrary photo.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "fixtures" / "imports"


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def draw_order_screenshot(path: Path, title: str, lines: list[tuple[str, str, str]]) -> str:
    width, height = 900, 140 + 72 * len(lines)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(30)
    small = _font(20)
    body = _font(26)
    draw.rectangle([0, 0, width, 70], fill=(35, 45, 60))
    draw.text((28, 20), "DEMO 演示订单截图（虚构数据）", font=small, fill=(255, 214, 102))
    draw.text((28, 92), title, font=title_font, fill=(20, 20, 20))
    y = 150
    for name, spec, price in lines:
        draw.text((40, y), name, font=body, fill=(30, 30, 30))
        draw.text((560, y), spec, font=small, fill=(90, 90, 90))
        draw.text((800, y), price, font=small, fill=(90, 90, 90))
        draw.line([(40, y + 52), (860, y + 52)], fill=(225, 225, 225), width=1)
        y += 72
    draw.text((40, height - 40), "本图片由 scripts/make_demo_fixtures.py 生成，仅用于演示导入流程。", font=small, fill=(140, 140, 140))
    image.save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = []

    shot1 = OUT_DIR / "demo_order_screenshot_1.png"
    sha1 = draw_order_screenshot(
        shot1,
        "订单确认 · 2026-10-10",
        [
            ("澄泉 DEMO 轻透防晒乳 SPF50+ PA++++", "50ml x 1", "¥129.00"),
            ("澄泉 DEMO 净澈去角质凝胶", "75ml x 1", "¥89.00"),
        ],
    )
    fixtures.append(
        {
            "filename": shot1.name,
            "sha256": sha1,
            "notice": "演示样本：mock 模式按文件哈希匹配，不代表真实 OCR/视觉识别能力。",
            "raw_text": (
                "DEMO 演示订单截图（虚构数据）\n订单确认 · 2026-10-10\n"
                "澄泉 DEMO 轻透防晒乳 SPF50+ PA++++  50ml x 1  ¥129.00\n"
                "澄泉 DEMO 净澈去角质凝胶  75ml x 1  ¥89.00"
            ),
            "candidates": [
                {
                    "raw_name": "澄泉 DEMO 轻透防晒乳 SPF50+ PA++++",
                    "brand": "澄泉 DEMO",
                    "quantity": 1,
                    "size": "50ml",
                    "confidence": 0.93,
                    "evidence_text": "澄泉 DEMO 轻透防晒乳 SPF50+ PA++++ 50ml x 1",
                },
                {
                    "raw_name": "澄泉 DEMO 净澈去角质凝胶",
                    "brand": "澄泉 DEMO",
                    "quantity": 1,
                    "size": "75ml",
                    "confidence": 0.88,
                    "evidence_text": "澄泉 DEMO 净澈去角质凝胶 75ml x 1",
                },
            ],
        }
    )

    shot2 = OUT_DIR / "demo_order_screenshot_2.png"
    sha2 = draw_order_screenshot(
        shot2,
        "订单确认 · 2026-09-28",
        [
            ("澄泉 DEMO 水润保湿乳", "100ml x 2", "¥99.00"),
            ("澄泉 DEMO 深海修护精华", "30ml x 1", "¥169.00"),
        ],
    )
    fixtures.append(
        {
            "filename": shot2.name,
            "sha256": sha2,
            "notice": "演示样本：含一件资料缺失的产品，用于 AC05/AC42 演示。",
            "raw_text": (
                "DEMO 演示订单截图（虚构数据）\n订单确认 · 2026-09-28\n"
                "澄泉 DEMO 水润保湿乳  100ml x 2  ¥99.00\n"
                "澄泉 DEMO 深海修护精华  30ml x 1  ¥169.00"
            ),
            "candidates": [
                {
                    "raw_name": "澄泉 DEMO 水润保湿乳",
                    "brand": "澄泉 DEMO",
                    "quantity": 2,
                    "size": "100ml",
                    "confidence": 0.95,
                    "evidence_text": "澄泉 DEMO 水润保湿乳 100ml x 2",
                },
                {
                    "raw_name": "澄泉 DEMO 深海修护精华",
                    "brand": "澄泉 DEMO",
                    "quantity": 1,
                    "size": "30ml",
                    "confidence": 0.52,
                    "evidence_text": "澄泉 DEMO 深海修护精华 30ml x 1（目录中无批准资料，需人工确认）",
                },
            ],
        }
    )

    manifest = {
        "_meta": {
            "notice": "内置演示截图与识别样本（全部虚构）。mock 模式按 sha256 匹配，不代表真实识别能力。",
            "generated_by": "scripts/make_demo_fixtures.py",
        },
        "fixtures": fixtures,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(fixtures)} fixtures to {OUT_DIR}")
    for fixture in fixtures:
        print(f"  {fixture['filename']}  sha256={fixture['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
