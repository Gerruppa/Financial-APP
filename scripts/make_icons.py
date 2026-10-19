"""Cut the app icons out of the KAPITA logo: .venv/Scripts/python.exe scripts/make_icons.py

Needs Pillow (the ``build`` extra). The outputs are committed, so run it only when the logo changes.
"""

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
LOGO = REPO / "packaging" / "kapita-logo.png"
ASSETS = REPO / "src" / "financial_app" / "ui" / "assets"
# The "K" mark without the KAPITA lettering, which no small icon could show; in the 1254 px logo
MARK_BOX = (255, 120, 1015, 880)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def rounded(image: Image.Image, radius_share: float = 0.18) -> Image.Image:
    """The image as a rounded square, transparent outside the corners."""
    mask = Image.new("L", image.size, 0)
    radius = int(image.width * radius_share)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def main() -> None:
    mark = rounded(Image.open(LOGO).crop(MARK_BOX).resize((256, 256), Image.Resampling.LANCZOS))
    ASSETS.mkdir(parents=True, exist_ok=True)
    mark.save(ASSETS / "kapita.png")
    mark.save(ASSETS / "kapita.ico", sizes=ICO_SIZES)


if __name__ == "__main__":
    main()
