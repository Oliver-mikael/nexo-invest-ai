"""Genera los iconos PNG de la PWA sin dependencias externas.

Uso:

    python3 scripts/generate_pwa_icons.py

Escribe `web/public/icons/icon-192.png`, `icon-512.png` y
`icon-maskable-512.png`. El dibujo es geométrico (fondo redondeado oscuro, tres
barras y una línea ascendente) y se calcula píxel a píxel con antialiasing por
supermuestreo 3x3, de modo que el resultado es reproducible y no depende de
herramientas gráficas.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import List, Tuple

INK = (13, 18, 21)
MOSS = (15, 132, 102)
MOSS_LIGHT = (79, 191, 154)
AMBER = (198, 123, 27)
PAPER = (246, 245, 240)

Point = Tuple[float, float]


def _rounded_rect_contains(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _segment_distance(px: float, py: float, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    proj = (ax + t * dx, ay + t * dy)
    return ((px - proj[0]) ** 2 + (py - proj[1]) ** 2) ** 0.5


def render(size: int, *, maskable: bool = False) -> List[List[Tuple[int, int, int, int]]]:
    scale = size / 512.0
    inset = 0.0 if not maskable else 0.0
    radius = 112 * scale if not maskable else 0
    bars = [
        (96, 300, 160, 416, MOSS),
        (192, 228, 256, 416, MOSS_LIGHT),
        (288, 156, 352, 416, AMBER),
    ]
    line = [(112, 190), (400, 64)]
    rows: List[List[Tuple[int, int, int, int]]] = []
    samples = 3
    for py in range(size):
        row: List[Tuple[int, int, int, int]] = []
        for px in range(size):
            acc = [0, 0, 0, 0]
            hits = 0
            for sy in range(samples):
                for sx in range(samples):
                    x = (px + (sx + 0.5) / samples) * (512.0 / size) + inset
                    y = (py + (sy + 0.5) / samples) * (512.0 / size) + inset
                    if not maskable and radius:
                        if not _rounded_rect_contains(x, y, 0, 0, 512, 512, radius):
                            continue
                    hits += 1
                    color = INK
                    for x0, y0, x1, y1, bar_color in bars:
                        if x0 <= x <= x1 and y0 <= y <= y1:
                            color = bar_color
                            break
                    if color == INK and _segment_distance(x, y, *line) <= 7:
                        if abs(y - (190 + (x - 112) * (64 - 190) / (400 - 112))) <= 14:
                            color = PAPER
                    acc[0] += color[0]
                    acc[1] += color[1]
                    acc[2] += color[2]
            if hits == 0:
                row.append((0, 0, 0, 0))
            else:
                row.append(
                    (
                        acc[0] // hits,
                        acc[1] // hits,
                        acc[2] // hits,
                        255,
                    )
                )
        rows.append(row)
    return rows


def write_png(path: Path, rows: List[List[Tuple[int, int, int, int]]]) -> None:
    height = len(rows)
    width = len(rows[0])
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for pixel in row:
            raw.extend(pixel)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    print(f"{path} · {width}x{height} · {len(png)} bytes")


def main() -> None:
    base = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"
    write_png(base / "icon-192.png", render(192))
    write_png(base / "icon-512.png", render(512))
    write_png(base / "icon-maskable-512.png", render(512, maskable=True))


if __name__ == "__main__":
    main()
