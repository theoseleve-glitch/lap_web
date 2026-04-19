#!/usr/bin/env python3
"""Heuristics for iRacing track .dat containers.

Goals:
- identify obvious container/version bytes
- compare entropy and repetition
- find common multi-file patterns across track packages
- test for plausible chunk boundaries near candidate compression signatures
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from collections import Counter
from pathlib import Path


def entropy(data: bytes) -> float:
    counts = Counter(data)
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def header_words(data: bytes, limit: int) -> list[str]:
    words: list[str] = []
    count = min(limit, len(data) // 4)
    for index in range(count):
        offset = index * 4
        value = struct.unpack_from("<I", data, offset)[0]
        words.append(f"0x{offset:02X}: 0x{value:08X} ({value})")
    return words


def repeated_block_score(data: bytes, block_size: int) -> tuple[int, int]:
    blocks = [bytes(data[offset : offset + block_size]) for offset in range(0, len(data) - block_size + 1, block_size)]
    counts = Counter(blocks)
    repeated = sum(count for count in counts.values() if count > 1)
    return len(counts), repeated


def try_zlib_windows(path: Path, offset: int, span: int, attempts: int) -> list[str]:
    out: list[str] = []
    with path.open("rb") as handle:
        for delta in range(attempts):
            handle.seek(max(0, offset - delta))
            sample = handle.read(span)
            if len(sample) < 16:
                continue
            for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
                try:
                    decoded = zlib.decompress(sample, wbits=wbits)
                except zlib.error:
                    continue
                out.append(
                    f"offset={offset - delta} wbits={wbits} decoded_len={len(decoded)} head={decoded[:32]!r}"
                )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--head-bytes", type=int, default=128)
    parser.add_argument("--sample-bytes", type=int, default=65536)
    parser.add_argument("--zlib-offset", type=int, action="append", default=[])
    parser.add_argument("--zlib-span", type=int, default=1 << 20)
    parser.add_argument("--zlib-attempts", type=int, default=8)
    args = parser.parse_args()

    for path in args.paths:
        data = path.read_bytes()[: args.head_bytes]
        print(f"FILE: {path}")
        print(f"SIZE: {path.stat().st_size:,} bytes")
        print(f"HEAD_HEX: {' '.join(f'{byte:02X}' for byte in data[:32])}")
        if len(data) >= 2:
            print(f"U16_LE@0: {struct.unpack_from('<H', data, 0)[0]}")
        print("HEAD_U32_LE:")
        for line in header_words(data, limit=8):
            print(f"  {line}")

        with path.open("rb") as handle:
            sample = handle.read(args.sample_bytes)
        print(f"SAMPLE_ENTROPY: {entropy(sample):.4f}")
        for block_size in (8, 16, 32):
            unique, repeated = repeated_block_score(sample, block_size)
            print(f"BLOCKS_{block_size}: unique={unique} repeated_members={repeated}")

        if args.zlib_offset:
            print("ZLIB_PROBES:")
            for offset in args.zlib_offset:
                hits = try_zlib_windows(path, offset=offset, span=args.zlib_span, attempts=args.zlib_attempts)
                if hits:
                    print(f"  candidate@{offset}:")
                    for hit in hits:
                        print(f"    {hit}")
                else:
                    print(f"  candidate@{offset}: none")
        print()


if __name__ == "__main__":
    main()
