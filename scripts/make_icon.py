"""Generate the flat FinBoard app icon (no external design assets needed)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BLUE = (61, 109, 242, 255)
WHITE = (255, 255, 255, 255)
SCALE = 4


def draw(size: int = 256) -> Image.Image:
    canvas = size * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def s(value: float) -> int:
        return round(value * canvas / 256)

    # Rounded blue tile.
    draw.rounded_rectangle(
        (s(12), s(12), s(244), s(244)), radius=s(56), fill=BLUE
    )

    # Wallet body: white outline with a soft rounded silhouette.
    left, top, right, bottom = s(62), s(94), s(194), s(182)
    draw.rounded_rectangle(
        (left, top, right, bottom), radius=s(18), outline=WHITE, width=s(10)
    )
    # Flap across the top third.
    draw.line((left + s(12), s(122), right - s(12), s(122)), fill=WHITE, width=s(8))
    # Card peeking out of the top.
    draw.rounded_rectangle(
        (s(84), s(72), s(164), s(104)), radius=s(10), fill=BLUE
    )
    draw.rounded_rectangle(
        (s(92), s(82), s(156), s(96)), radius=s(7), fill=WHITE
    )
    # Clasp on the right side.
    draw.ellipse((s(162), s(132), s(190), s(160)), fill=WHITE)
    draw.ellipse((s(171), s(141), s(181), s(151)), fill=BLUE)

    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    resources = Path("finboard") / "resources"
    docs = Path("docs") / "assets"
    resources.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    base = draw(256)
    base.save(resources / "finboard.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    base.save(resources / "finboard.png")
    base.save(docs / "logo.png")
    print("wrote", resources / "finboard.ico")


if __name__ == "__main__":
    main()
