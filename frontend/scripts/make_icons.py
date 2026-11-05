"""Generate the app icons as PNGs with no image libraries (run: python scripts/make_icons.py).

The mark is a soft ring around a dot on a warm dark square: "tell the system" as a quiet
record button, matching the calm design language in the UX spec.
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
BACKGROUND = (23, 24, 27)
INK = (246, 245, 242)
ACCENT = (214, 170, 96)


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def pixel(x: float, y: float, size: int) -> tuple[int, int, int]:
    c = size / 2
    r = math.hypot(x - c, y - c) / size
    color = BACKGROUND
    ring_outer, ring_inner, dot = 0.30, 0.255, 0.105
    edge = 1.2 / size
    if r < dot + edge:
        color = mix(ACCENT, color, max(0.0, min(1.0, (r - dot) / edge + 0.5)))
    elif ring_inner - edge < r < ring_outer + edge:
        inside = min((r - ring_inner) / edge + 0.5, (ring_outer - r) / edge + 0.5)
        color = mix(color, INK, max(0.0, min(1.0, inside)))
    return color


def png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row.extend(pixel(x + 0.5, y + 0.5, size))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        (OUT / name).write_bytes(png(size))
        print(f"wrote {name}")
