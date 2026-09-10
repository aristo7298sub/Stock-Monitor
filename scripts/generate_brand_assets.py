from pathlib import Path

from PIL import Image, ImageDraw


def logo(size: int) -> Image.Image:
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale))
    drawing = ImageDraw.Draw(canvas)
    unit = size * scale / 512

    def points(values):
        return [(round(horizontal * unit), round(vertical * unit)) for horizontal, vertical in values]

    drawing.rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=round(104 * unit), fill="#153F38")
    drawing.line(points([(112, 366), (112, 154), (248, 304), (378, 142), (378, 366)]), fill="#F4FAF5", width=round(38 * unit), joint="curve")
    drawing.line(points([(112, 366), (248, 304), (378, 142)]), fill="#89D2AF", width=round(20 * unit), joint="curve")
    center = points([(378, 142)])[0]
    radius = round(31 * unit)
    drawing.ellipse((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), fill="#F1BA64")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "web" / "public"
    destination.mkdir(parents=True, exist_ok=True)
    master = logo(512)
    master.save(destination / "stock-monitor-logo.png")
    for size, name in ((192, "icon-192.png"), (180, "apple-touch-icon.png"), (32, "favicon-32.png")):
        logo(size).save(destination / name)
    master.save(destination / "favicon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
    for name in ("stock-monitor-logo.png", "icon-192.png", "apple-touch-icon.png", "favicon-32.png", "favicon.ico"):
        with Image.open(destination / name) as image:
            assert image.getbbox() is not None
            assert image.convert("RGB").getextrema()[0][0] != image.convert("RGB").getextrema()[0][1]
        print(name)


if __name__ == "__main__":
    main()