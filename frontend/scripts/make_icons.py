"""生成 PWA 图标（纯本地、无外部资源）。

用法（在仓库根目录）：
    ./.venv/bin/python frontend/scripts/make_icons.py

输出：frontend/public/icons/ 下的 192/512 普通图标与 maskable 图标，
以及 180x180 的 apple-touch-icon。图形为纯色圆角方块 + "BC" 字形，
不含任何真实品牌标识。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "icons"
THEME = (47, 93, 98)  # #2f5d62
BG = (246, 247, 245)  # #f6f7f5
FG = (255, 255, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon(size: int, *, maskable: bool) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if maskable:
        # maskable：安全区内绘制，四周留出 20% 出血区域。
        draw.rectangle([0, 0, size, size], fill=THEME)
        inset = int(size * 0.22)
        box = [inset, inset, size - inset, size - inset]
    else:
        radius = int(size * 0.22)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=THEME)
        box = [0, 0, size, size]

    font_size = int((box[2] - box[0]) * 0.52)
    font = load_font(font_size)
    text = "BC"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = box[0] + ((box[2] - box[0]) - text_w) / 2 - bbox[0]
    y = box[1] + ((box[3] - box[1]) - text_h) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=FG)
    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "icon-192.png": draw_icon(192, maskable=False),
        "icon-512.png": draw_icon(512, maskable=False),
        "icon-192-maskable.png": draw_icon(192, maskable=True),
        "icon-512-maskable.png": draw_icon(512, maskable=True),
        "apple-touch-icon.png": draw_icon(180, maskable=False),
    }
    for name, image in outputs.items():
        path = OUT_DIR / name
        image.save(path, format="PNG")
        print(f"wrote {path} ({image.width}x{image.height})")


if __name__ == "__main__":
    main()
