"""Draw the Extractor app icon (a vinyl record with the lime label) and write ui/extractor.ico.

Pure standard library: each size is rasterised with 4x4 supersampling, encoded as PNG,
and packed into a multi-size .ico. Small sizes drop detail so they stay crisp.

    python tools/make_icon.py
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 4

DISC = (20, 20, 23)
RIM = (44, 44, 51)
GROOVE = (36, 36, 42)
LABEL = (212, 243, 74)
LABEL_LINE = (170, 196, 58)
HOLE = (10, 10, 12)


def colour_at(d: float, size: int) -> tuple[int, int, int] | None:
    """Colour at distance d from the centre, d in units of the disc radius (1.0 = edge)."""
    if d > 1.0:
        return None
    label = 0.46 if size <= 24 else 0.40
    if size >= 24 and d < 0.08:
        return HOLE
    if d < label:
        if size >= 64 and abs(d - label * 0.82) < 0.012:
            return LABEL_LINE
        return LABEL
    if d > 0.95:
        return RIM
    if size >= 40:
        for ring in (0.86, 0.74, 0.62):
            if abs(d - ring) < (0.012 if size >= 128 else 0.02):
                return GROOVE
    return DISC


def render(size: int) -> bytes:
    """RGBA pixels, row-major."""
    radius = size * 0.47
    centre = size / 2
    step = 1 / SUPERSAMPLE
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    px = x + (sx + 0.5) * step - centre
                    py = y + (sy + 0.5) * step - centre
                    colour = colour_at(math.hypot(px, py) / radius, size)
                    if colour:
                        r += colour[0]
                        g += colour[1]
                        b += colour[2]
                        a += 1
            if a:
                pixels += bytes((r // a, g // a, b // a, round(255 * a / SUPERSAMPLE**2)))
            else:
                pixels += b"\0\0\0\0"
    return bytes(pixels)


def png(size: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    stride = size * 4
    raw = b"".join(b"\0" + rgba[row * stride:(row + 1) * stride] for row in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(images: list[tuple[int, bytes]]) -> bytes:
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + entries + b"".join(data for _, data in images)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "ui" / "extractor.ico"
    images = [(size, png(size, render(size))) for size in SIZES]
    target.write_bytes(ico(images))
    print(f"wrote {target} ({target.stat().st_size // 1024} KB, sizes {', '.join(map(str, SIZES))})")


if __name__ == "__main__":
    main()
