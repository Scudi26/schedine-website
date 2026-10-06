"""The app icons (installable site): Scudi's mark — a gold shield with a night field and a gold coin — on the night
background, with a soft floodlight glow. The same geometry as the SVG mark in index.html (48-unit grid). Needs Pillow.

    python3 tools/make_icons.py      # writes icons/icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png, favicon-32.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

NIGHT = (6, 9, 19)
NIGHT_2 = (19, 26, 58)
GOLD = [(251, 231, 166), (233, 185, 73), (184, 134, 31)]       # the SVG gradient's stops
FIELD = [(27, 34, 80), (10, 14, 34)]
RING = (20, 26, 56, 255)


def bez(p0, p1, p2, p3, n=28):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * e for a, b, c, e in zip(p0, p1, p2, p3))
            for t in (i / n for i in range(n + 1))]


def shield_pts(top, side_x, side_y, bottom_y, c1, c2):
    """M24 top L side 9.5-ish V side_y C ... 24 bottom C ... Z, mirrored."""
    right = bez((side_x, side_y), c1, c2, (24, bottom_y))
    left = [(48 - x, y) for x, y in reversed(right)]
    return [(24, top), (side_x, 9.5 if side_x > 40 else 12.6), *right, *left[1:], (48 - side_x, 9.5 if side_x > 40 else 12.6)]


OUTER = shield_pts(4, 41, 22, 44.5, (41, 33.5), (33.6, 41.6))
INNER = shield_pts(8.2, 37.4, 22, 40.8, (37.4, 31.6), (31.6, 38.2))


def gradient(size, stops, angle_diag=True):
    """A diagonal (or vertical) linear gradient image of the given stops."""
    w = h = size
    im = Image.new("RGBA", (w, h))
    px = im.load()
    n = len(stops) - 1
    for y in range(h):
        for x in range(w):
            t = ((x + y) / (2 * (w - 1))) if angle_diag else (y / (h - 1))
            k = min(n - 1, int(t * n))
            f = t * n - k
            c = tuple(int(stops[k][i] * (1 - f) + stops[k + 1][i] * f) for i in range(3))
            px[x, y] = (*c, 255)
    return im


def mark(size: int, pad: float, round_bg: bool = False, glow: bool = True) -> Image.Image:
    s = 4 * size   # draw large, then shrink: smooth edges
    bg = Image.new("RGBA", (s, s), (*NIGHT, 255))
    # night vignette + floodlight glow
    g = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    gd.ellipse([s * 0.1, -s * 0.3, s * 0.9, s * 0.55], fill=(*NIGHT_2, 255))
    g = g.filter(ImageFilter.GaussianBlur(s * 0.14))
    bg = Image.alpha_composite(bg, g)
    if glow:
        gl = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(gl).ellipse([s * 0.22, s * 0.26, s * 0.78, s * 0.86], fill=(233, 185, 73, 70))
        gl = gl.filter(ImageFilter.GaussianBlur(s * 0.12))
        bg = Image.alpha_composite(bg, gl)
    m = s * pad
    w = s - 2 * m

    def xy(pt):
        return (m + pt[0] / 48 * w, m + pt[1] / 48 * w)

    def masked(poly, grad):
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).polygon([xy(p) for p in poly], fill=255)
        layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        layer.paste(grad, (0, 0), mask)
        return layer

    gold = gradient(s, GOLD, True)
    field = gradient(s, FIELD, False)
    out = Image.alpha_composite(bg, masked(OUTER, gold))
    out = Image.alpha_composite(out, masked(INNER, field))
    # the coin
    d = ImageDraw.Draw(out)
    cx, cy = xy((24, 23.6))
    r = 7.4 / 48 * w
    coin = Image.new("L", (s, s), 0)
    ImageDraw.Draw(coin).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    layer.paste(gold, (0, 0), coin)
    out = Image.alpha_composite(out, layer)
    d = ImageDraw.Draw(out)
    r2 = 4.7 / 48 * w
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=RING, width=max(2, int(1.7 / 48 * w)))
    # highlight arc on the coin
    d.arc([cx - r * 0.84, cy - r * 0.84, cx + r * 0.84, cy + r * 0.84], start=200, end=250, fill=(255, 255, 255, 150), width=max(2, int(1.1 / 48 * w)))
    if round_bg:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
        out.putalpha(mask)
    return out.resize((size, size), Image.LANCZOS)


def main():
    out = Path("icons")
    out.mkdir(exist_ok=True)
    mark(192, 0.12).save(out / "icon-192.png")
    mark(512, 0.12).save(out / "icon-512.png")
    mark(512, 0.22).save(out / "icon-maskable-512.png")   # the safe zone of a maskable icon is the inner 80%
    mark(180, 0.12).convert("RGB").save(out / "apple-touch-icon.png")
    mark(64, 0.08, glow=False).resize((32, 32), Image.LANCZOS).save(out / "favicon-32.png")
    print("icons written to", out)


if __name__ == "__main__":
    main()
