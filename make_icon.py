"""Creates icon.ico for the .exe (run by build_exe.bat, not needed otherwise)."""
from PIL import Image, ImageDraw

ACCENT = "#4f7cff"


def make_icon(size=256):
    """Blue rounded square with a white download arrow (same logo as the app header)."""
    big = size * 4
    k = big / 36
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(11 * k), fill=ACCENT)
    w = int(3.4 * k)

    def stroke(*pts):
        pts = [(x * k, y * k) for x, y in pts]
        d.line(pts, fill="white", width=w, joint="curve")
        for x, y in (pts[0], pts[-1]):  # round caps
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="white")

    stroke((18, 9), (18, 24))
    stroke((11, 18), (18, 25), (25, 18))
    stroke((11, 28), (25, 28))
    return img.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    make_icon(256).save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.ico created")
