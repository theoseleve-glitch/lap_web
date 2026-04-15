"""Decode a BC1/DXT1-backed iRacing ATAD chunk to PNG.

This is a focused helper for the common Laguna DAT bitmap family where:

- BMHD ``type_id`` appears as ``10``
- row stride equals ``width / 2``
- DATA payloads are one or more zstd frames containing BC1 blocks

Example:

```powershell
python scripts/decode_iracing_bc1_atad.py ^
  "C:\\Program Files (x86)\\iRacing\\Tracks\\lagunaseca\\lagunaseca.dat" ^
  20789635 1024 1024 artifacts/iracing_dat_extract/laguna_type10_1024x1024_bc1.png
```
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import zstandard as zstd
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "This script requires the `zstandard` package. Install with: "
        "python -m pip install zstandard"
    ) from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "This script requires Pillow. Install with: python -m pip install pillow"
    ) from exc


ZSTD_MAGIC = bytes.fromhex("28 b5 2f fd")


def rgb565_to_rgba8888(value: int) -> tuple[int, int, int, int]:
    r = ((value >> 11) & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x3F) * 255 // 63
    b = (value & 0x1F) * 255 // 31
    return r, g, b, 255


def decode_bc1(raw: bytes, width: int, height: int) -> bytes:
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    rgba = bytearray(width * height * 4)
    pos = 0

    for by in range(block_h):
        for bx in range(block_w):
            c0 = int.from_bytes(raw[pos : pos + 2], "little")
            c1 = int.from_bytes(raw[pos + 2 : pos + 4], "little")
            codebook = int.from_bytes(raw[pos + 4 : pos + 8], "little")
            pos += 8

            p0 = rgb565_to_rgba8888(c0)
            p1 = rgb565_to_rgba8888(c1)
            if c0 > c1:
                p2 = tuple((2 * p0[i] + p1[i]) // 3 for i in range(4))
                p3 = tuple((p0[i] + 2 * p1[i]) // 3 for i in range(4))
            else:
                p2 = tuple((p0[i] + p1[i]) // 2 for i in range(4))
                p3 = (0, 0, 0, 0)
            palette = (p0, p1, p2, p3)

            for py in range(4):
                for px in range(4):
                    x = bx * 4 + px
                    y = by * 4 + py
                    if x >= width or y >= height:
                        continue
                    selector = (codebook >> (2 * (4 * py + px))) & 0x3
                    pixel = palette[selector]
                    dst = (y * width + x) * 4
                    rgba[dst : dst + 4] = bytes(pixel)

    return bytes(rgba)


def decode_atad_payload(dat_bytes: bytes, atad_offset: int) -> bytes:
    payload_len = int.from_bytes(
        dat_bytes[atad_offset + 8 : atad_offset + 12], "little"
    )
    payload = dat_bytes[atad_offset + 12 : atad_offset + 12 + payload_len]

    if len(payload) < 16:
        raise ValueError("ATAD payload is too small")
    if payload[16:20] != ZSTD_MAGIC:
        raise ValueError("ATAD payload is not zstd-backed at +16")

    frame_starts: list[int] = []
    start = 16
    while True:
        idx = payload.find(ZSTD_MAGIC, start)
        if idx < 0:
            break
        frame_starts.append(idx)
        start = idx + 1

    if not frame_starts:
        raise ValueError("no zstd frames found inside ATAD payload")

    return b"".join(
        zstd.ZstdDecompressor().decompress(payload[frame_off:])
        for frame_off in frame_starts
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat_path", type=Path)
    parser.add_argument("atad_offset", type=int)
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("output_png", type=Path)
    args = parser.parse_args()

    dat_bytes = args.dat_path.read_bytes()
    bc1_bytes = decode_atad_payload(dat_bytes, args.atad_offset)
    rgba = decode_bc1(bc1_bytes, args.width, args.height)

    args.output_png.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGBA", (args.width, args.height), rgba).save(args.output_png)
    print(args.output_png)


if __name__ == "__main__":
    main()
