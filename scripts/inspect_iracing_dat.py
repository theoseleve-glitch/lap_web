#!/usr/bin/env python3
"""Read-only first-pass inspection for iRacing .dat containers.

This is not a full parser. It is meant to support file-format reconnaissance:
- header bytes
- sampled entropy / printable ratios
- obvious embedded signatures
- readable ASCII strings that match likely track/material keywords
"""

from __future__ import annotations

import argparse
import math
import mmap
import os
import re
from collections import Counter
from pathlib import Path

DEFAULT_KEYWORDS = (
    "asphalt",
    "brush",
    "contact",
    "concrete",
    "damper",
    "grass",
    "dirt",
    "gravel",
    "sand",
    "paint",
    "rumble",
    "astroturf",
    "surface",
    "grip",
    "gripsealer",
    "gripmodifier",
    "friction",
    "coeff",
    "laguna",
    "slip",
    "spring",
    "stiffness",
    "suspension",
    "temperature",
    "tire",
    "tire2descriptor",
)

SIGNATURES = {
    b"PK\x03\x04": "zip",
    b"Rar!": "rar",
    b"7z\xBC\xAF\x27\x1C": "7z",
    b"\x1F\x8B\x08": "gzip",
    b"BZh": "bzip2",
    b"OggS": "ogg",
    b"RIFF": "riff",
    b"DDS ": "dds",
    b"\x89PNG\r\n\x1a\n": "png",
    b"JFIF": "jpeg",
    b"KTX ": "ktx",
    b"UnityFS": "unityfs",
}


def entropy(data: bytes) -> float:
    counts = Counter(data)
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def printable_ratio(data: bytes) -> float:
    return sum(32 <= b <= 126 for b in data) / len(data)


def sample_regions(path: Path, chunk_size: int) -> list[tuple[str, int, bytes]]:
    size = path.stat().st_size
    offsets = [
        ("head", 0),
        ("mid", max(0, size // 2 - chunk_size // 2)),
        ("tail", max(0, size - chunk_size)),
    ]
    regions = []
    with path.open("rb") as handle:
        for label, offset in offsets:
            handle.seek(offset)
            regions.append((label, offset, handle.read(chunk_size)))
    return regions


def header_hex(path: Path, length: int) -> str:
    with path.open("rb") as handle:
        return " ".join(f"{byte:02X}" for byte in handle.read(length))


def scan_signatures(path: Path, limit: int) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for magic, name in SIGNATURES.items():
            pos = mm.find(magic)
            if pos != -1:
                hits.append((name, pos))
    hits.sort(key=lambda item: item[1])
    return hits[:limit]


def extract_keyword_strings(
    path: Path, keywords: tuple[str, ...], min_length: int, limit: int
) -> list[str]:
    pattern = re.compile("|".join(re.escape(keyword) for keyword in keywords), re.IGNORECASE)
    matches: list[str] = []
    buffer = bytearray()

    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            for byte in chunk:
                if 32 <= byte <= 126 or byte == 9:
                    buffer.append(byte)
                    continue

                if len(buffer) >= min_length:
                    text = buffer.decode("ascii", errors="ignore")
                    if pattern.search(text):
                        matches.append(text)
                        if len(matches) >= limit:
                            return matches
                buffer.clear()

    if len(buffer) >= min_length:
        text = buffer.decode("ascii", errors="ignore")
        if pattern.search(text):
            matches.append(text)
    return matches[:limit]


def inspect(
    path: Path,
    chunk_size: int,
    header_len: int,
    string_limit: int,
    min_length: int,
    scan_strings: bool,
) -> None:
    size = path.stat().st_size
    print(f"FILE: {path}")
    print(f"SIZE: {size:,} bytes")
    print(f"HEADER({header_len}): {header_hex(path, header_len)}")

    with path.open("rb") as handle:
        version_bytes = handle.read(2)
    if len(version_bytes) == 2:
        version = int.from_bytes(version_bytes, "little")
        print(f"HEADER_U16_LE: {version}")

    print("SAMPLES:")
    for label, offset, data in sample_regions(path, chunk_size):
        print(
            f"  {label:>4} offset={offset:<10} entropy={entropy(data):.4f} "
            f"printable={printable_ratio(data):.2%} zeros={data.count(0) / len(data):.2%}"
        )

    hits = scan_signatures(path, limit=10)
    print("SIGNATURES:")
    if hits:
        for name, offset in hits:
            print(f"  {name:<8} offset={offset}")
    else:
        print("  none")

    print("KEYWORD_STRINGS:")
    if not scan_strings:
        print("  skipped")
    else:
        strings = extract_keyword_strings(
            path,
            keywords=DEFAULT_KEYWORDS,
            min_length=min_length,
            limit=string_limit,
        )
        if strings:
            for text in strings:
                trimmed = text if len(text) <= 160 else f"{text[:157]}..."
                print(f"  {trimmed}")
        else:
            print("  none")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="One or more .dat files to inspect")
    parser.add_argument("--chunk-size", type=int, default=65536, help="Bytes per entropy sample")
    parser.add_argument("--header-len", type=int, default=32, help="Bytes to print from the file header")
    parser.add_argument("--string-limit", type=int, default=10, help="Max keyword-matching strings to print")
    parser.add_argument("--min-string-length", type=int, default=5, help="Minimum ASCII run length")
    parser.add_argument("--no-strings", action="store_true", help="Skip the full ASCII string scan")
    args = parser.parse_args()

    for path in args.paths:
        inspect(
            path=path,
            chunk_size=args.chunk_size,
            header_len=args.header_len,
            string_limit=args.string_limit,
            min_length=args.min_string_length,
            scan_strings=not args.no_strings,
        )


if __name__ == "__main__":
    main()
