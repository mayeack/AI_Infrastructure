#!/usr/bin/env python3
"""Write the app icons (six-bar stack glyph, white on transparent) with a stdlib-only PNG encoder.

Outputs static/appIcon.png (36x36), appIcon_2x.png (72x72), appIconAlt.png, appIconAlt_2x.png.
The six bars narrow upward (the AI stack drawn bottom-up); edges are anti-aliased with a 4x4 coverage mask per pixel.
"""
import argparse
import os
import struct
import sys
import zlib

SUPER = 4
WIDTHS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]  # bottom to top, fraction of the glyph width


def png_chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path, size, pixels):
    """pixels: list of rows, each a list of (r,g,b,a) tuples."""
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0 (None)
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    data = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + png_chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, 0o644)


def draw(size):
    """Render the glyph at `size` px via a SUPER x SUPER coverage mask (anti-aliased edges)."""
    s = size * SUPER
    bar_h = size * 0.09 * SUPER
    gap = size * 0.055 * SUPER
    glyph_w = size * 0.78 * SUPER
    total_h = 6 * bar_h + 5 * gap
    top0 = (s - total_h) / 2.0
    cx = s / 2.0
    bars = []
    for i, frac in enumerate(WIDTHS):
        y1 = top0 + (5 - i) * (bar_h + gap)  # i=0 is the bottom bar
        w = glyph_w * frac
        bars.append((cx - w / 2.0, y1, cx + w / 2.0, y1 + bar_h))
    mask = [[0] * s for _ in range(s)]
    for x0, y0, x1, y1 in bars:
        for y in range(max(0, int(y0)), min(s, int(y1) + 1)):
            if y + 0.5 < y0 or y + 0.5 > y1:
                continue
            for x in range(max(0, int(x0)), min(s, int(x1) + 1)):
                if x0 <= x + 0.5 <= x1:
                    mask[y][x] = 1
    pixels = []
    for py in range(size):
        row = []
        for px in range(size):
            cov = 0
            for sy in range(SUPER):
                for sx in range(SUPER):
                    cov += mask[py * SUPER + sy][px * SUPER + sx]
            a = round(255 * cov / (SUPER * SUPER))
            row.append((255, 255, 255, a))
        pixels.append(row)
    return pixels


def read_ihdr(path):
    with open(path, "rb") as fh:
        head = fh.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError("%s is not a PNG" % path)
    w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
    return w, h, depth, ctype


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the six-bar app icons")
    ap.add_argument("out_dir", nargs="?", default="static")
    ap.add_argument("--check", action="store_true", help="only verify existing icons (dimensions via IHDR)")
    a = ap.parse_args(argv)
    targets = [("appIcon.png", 36), ("appIcon_2x.png", 72), ("appIconAlt.png", 36), ("appIconAlt_2x.png", 72)]
    if not a.check:
        os.makedirs(a.out_dir, exist_ok=True)
        cache = {}
        for name, size in targets:
            if size not in cache:
                cache[size] = draw(size)
            write_png(os.path.join(a.out_dir, name), size, cache[size])
    rc = 0
    for name, size in targets:
        p = os.path.join(a.out_dir, name)
        try:
            w, h, depth, ctype = read_ihdr(p)
            ok = (w, h, depth, ctype) == (size, size, 8, 6)
        except (OSError, ValueError) as e:
            ok, w, h, depth, ctype = False, "-", "-", "-", str(e)
        print("%-20s %sx%s depth=%s colour=%s %s" % (name, w, h, depth, ctype, "OK" if ok else "FAIL"))
        rc |= 0 if ok else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
