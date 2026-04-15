"""Partial extractor for iRacing DAT chunk assets.

This script documents and automates the chunk-format findings confirmed during
reverse-engineering of Laguna Seca's ``lagunaseca.dat``:

- chunks use a 12-byte header: ``tag[4] + zero[4] + payload_len_le[4]``
- payloads are padded to 4-byte boundaries with ``0x20`` bytes
- ``PAMB`` (BMAP) and ``PMTS`` (STMP-like) are container chunks
- ``DHMB`` (BMHD) stores image header metadata
- ``ATAD`` (DATA) stores either inline raw bytes or one/many zstd frames

Confirmed BMHD payload layout (14 bytes):

- byte 0: type id
- bytes 1..4: width (little-endian u32)
- bytes 5..8: height (little-endian u32)
- bytes 9..12: row pitch / stride bytes (little-endian u32)
- byte 13: format/flags id

The script currently focuses on extracting the PMTS assets that were confirmed
to decode cleanly into PNGs for Laguna Seca.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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


@dataclass(frozen=True)
class Chunk:
    offset: int
    tag: str
    payload_len: int
    payload_offset: int
    end_offset: int


@dataclass(frozen=True)
class BitmapHeader:
    type_id: int
    width: int
    height: int
    stride: int
    format_id: int


def read_chunk(data: bytes, offset: int) -> Chunk:
    if offset + 12 > len(data):
        raise ValueError(f"offset {offset} is outside the file")
    tag = data[offset : offset + 4].decode("ascii", "ignore")
    zero = data[offset + 4 : offset + 8]
    if zero != b"\x00\x00\x00\x00":
        raise ValueError(f"offset {offset} does not point to a chunk header")
    payload_len = int.from_bytes(data[offset + 8 : offset + 12], "little")
    pad = (4 - (payload_len % 4)) % 4
    payload_offset = offset + 12
    end_offset = payload_offset + payload_len + pad
    if end_offset > len(data):
        raise ValueError(f"chunk at {offset} overruns the file")
    return Chunk(
        offset=offset,
        tag=tag,
        payload_len=payload_len,
        payload_offset=payload_offset,
        end_offset=end_offset,
    )


def iter_children(data: bytes, parent: Chunk) -> Iterable[Chunk]:
    pos = parent.payload_offset
    limit = parent.payload_offset + parent.payload_len
    while pos + 12 <= limit:
        try:
            child = read_chunk(data, pos)
        except ValueError:
            break
        if child.end_offset > limit:
            break
        yield child
        pos = child.end_offset


def parse_bmhd_payload(payload: bytes) -> BitmapHeader:
    if len(payload) != 14:
        raise ValueError(f"unexpected BMHD payload size: {len(payload)}")
    return BitmapHeader(
        type_id=payload[0],
        width=int.from_bytes(payload[1:5], "little"),
        height=int.from_bytes(payload[5:9], "little"),
        stride=int.from_bytes(payload[9:13], "little"),
        format_id=payload[13],
    )


def find_zstd_frame_starts(payload: bytes, segment_count: int) -> list[int]:
    starts: list[int] = []
    start = 16
    while True:
        idx = payload.find(ZSTD_MAGIC, start)
        if idx < 0:
            break
        starts.append(idx)
        start = idx + 1
    if segment_count and len(starts) != segment_count:
        raise ValueError(
            f"expected {segment_count} zstd frames, found {len(starts)}"
        )
    return starts


def decode_data_payload(payload: bytes) -> tuple[list[int], bytes]:
    if len(payload) < 16:
        return [], payload
    meta = [
        int.from_bytes(payload[i : i + 4], "little")
        for i in range(0, 16, 4)
    ]
    segment_count = meta[0]
    if payload[16:20] == ZSTD_MAGIC:
        frame_starts = find_zstd_frame_starts(payload, segment_count)
        frames = [zstd.ZstdDecompressor().decompress(payload[i:]) for i in frame_starts]
        return meta, b"".join(frames)
    return meta, payload


def decode_leaf_bmap(data: bytes, pamb_chunk: Chunk) -> tuple[BitmapHeader, list[int], bytes]:
    children = list(iter_children(data, pamb_chunk))
    bmhd = next((c for c in children if c.tag == "DHMB"), None)
    atad = next((c for c in children if c.tag == "ATAD"), None)
    if bmhd is None or atad is None:
        raise ValueError(f"PAMB at {pamb_chunk.offset} is missing BMHD/ATAD")
    header = parse_bmhd_payload(data[bmhd.payload_offset : bmhd.payload_offset + bmhd.payload_len])
    meta, raw = decode_data_payload(data[atad.payload_offset : atad.payload_offset + atad.payload_len])
    return header, meta, raw


def extract_pmts_assets(dat_path: Path, outdir: Path) -> list[Path]:
    data = dat_path.read_bytes()
    outdir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    start = 0
    while True:
        off = data.find(b"PMTS\x00\x00\x00\x00", start)
        if off < 0:
            break
        pmts = read_chunk(data, off)
        children = list(iter_children(data, pmts))
        pamb = next((c for c in children if c.tag == "PAMB"), None)
        if pamb is None:
            start = off + 1
            continue

        header, meta, raw = decode_leaf_bmap(data, pamb)
        pixel_bytes = header.stride * header.height
        if len(raw) != pixel_bytes:
            start = off + 1
            continue

        stem = f"{dat_path.stem}_pmts_{header.width}x{header.height}_type{header.type_id}"
        out_path = outdir / f"{stem}.png"

        if header.type_id == 7 and header.stride == header.width * 4:
            Image.frombytes("RGBA", (header.width, header.height), raw).save(out_path)
            outputs.append(out_path)
        elif header.type_id == 6 and header.stride == header.width * 3:
            Image.frombytes("RGB", (header.width, header.height), raw).save(out_path)
            outputs.append(out_path)
        elif header.type_id == 7 and header.width == 2 and header.height == 2:
            Image.frombytes("RGBA", (2, 2), raw).save(out_path)
            outputs.append(out_path)
        else:
            # Keep a sidecar dump for assets we don't fully model yet.
            raw_path = outdir / f"{stem}.bin"
            raw_path.write_bytes(raw)
            outputs.append(raw_path)

        print(
            f"PMTS @{off}: {header.width}x{header.height} "
            f"type={header.type_id} stride={header.stride} meta={meta} -> {outputs[-1]}"
        )
        start = off + 1

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat_path", type=Path, help="Path to an iRacing .dat file")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("artifacts/iracing_dat_extract"),
        help="Directory for extracted assets",
    )
    args = parser.parse_args()

    outputs = extract_pmts_assets(args.dat_path, args.outdir)
    print(f"Extracted {len(outputs)} asset(s)")


if __name__ == "__main__":
    main()
