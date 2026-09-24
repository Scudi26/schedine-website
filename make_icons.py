"""The app icons (installable site): Scudi's gold shield on the night background. Needs Pillow.

    python3 tools/make_icons.py      # writes icons/icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png
"""

from pathlib import Path

from PIL import Image, ImageDraw

NIGHT, GOLD, INK = (11, 14, 31, 255), (233, 185, 73, 255), (36, 26, 0, 255)


def shield(size: int, pad: float) -> Image.Image:
    s = 4 * size   # draw large, then shrink: smooth edges
    im = Image.new("RGBA", (s, s), NIGHT)
    d = ImageDraw.Draw(im)
    m = s * pad
    w = s - 2 * m
    def x(u):   # the wordmark's 24-unit drawing
        return m + u / 24 * w

    def bez(p0, p1, p2, p3, n=24):
        return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * e for a, b, c, e in zip(p0, p1, p2, p3))
                for t in (i / n for i in range(n + 1))]
    right_curve = bez((21, 11), (21, 16.5), (17.2, 20.6), (12, 22))     # M12 2 l9 3 v6 c0 5.5 -3.8 9.6 -9 11
    left_curve = bez((12, 22), (6.8, 20.6), (3, 16.5), (3, 11))         # c-5.2 -1.4 -9 -5.5 -9 -11 V5z
    pts = [(12, 2), (21, 5), *right_curve, *left_curve[1:], (3, 5)]
    d.polygon([(x(a), x(b)) for a, b in pts], fill=GOLD)
    half = [(12, 2), (21, 5), *right_curve]
    d.polygon([(x(a), x(b)) for a, b in half], fill=(200, 158, 60, 255))
    r = w / 24 * 3.4
    c = (x(12), x(11))
    d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=INK, width=int(w / 24 * 1.6))
    return im.resize((size, size), Image.LANCZOS)


def main():
    out = Path("icons")
    out.mkdir(exist_ok=True)
    shield(192, 0.14).save(out / "icon-192.png")
    shield(512, 0.14).save(out / "icon-512.png")
    shield(512, 0.24).save(out / "icon-maskable-512.png")   # the safe zone of a maskable icon is the inner 80%
    shield(180, 0.14).convert("RGB").save(out / "apple-touch-icon.png")
    print("icons written to", out)


if __name__ == "__main__":
    main()
