#!/usr/bin/env python3
"""Map interesting ASCII strings back to PE sections.

This is a light-weight alternative to full disassembly. It helps answer:
- where a given identifier sits in the executable
- which section it belongs to (.rdata, .text, etc.)
- what nearby readable strings suggest about that area of the binary
"""

from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Section:
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int

    def contains(self, file_offset: int) -> bool:
        return self.raw_pointer <= file_offset < self.raw_pointer + self.raw_size


def parse_pe_sections(path: Path) -> tuple[bytes, list[Section]]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("Not an MZ/PE executable")

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("Missing PE signature")

    file_header_offset = pe_offset + 4
    _, number_of_sections, _, _, _, size_of_optional_header, _ = struct.unpack_from(
        "<HHIIIHH", data, file_header_offset
    )
    section_table = file_header_offset + 20 + size_of_optional_header

    sections: list[Section] = []
    for index in range(number_of_sections):
        offset = section_table + index * 40
        raw_name = data[offset : offset + 8]
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, offset + 8)
        sections.append(
            Section(
                name=name,
                virtual_size=virtual_size,
                virtual_address=virtual_address,
                raw_size=raw_size,
                raw_pointer=raw_pointer,
            )
        )
    return data, sections


def find_ascii_runs(data: bytes, min_length: int) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for match in re.finditer(rb"[\x20-\x7e\t]{%d,}" % min_length, data):
        matches.append((match.start(), match.group().decode("ascii", errors="ignore")))
    return matches


def owning_section(sections: list[Section], file_offset: int) -> str:
    for section in sections:
        if section.contains(file_offset):
            return section.name
    return "<none>"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="PE binary to inspect")
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Regex pattern for interesting strings. Repeat as needed.",
    )
    parser.add_argument("--min-string-length", type=int, default=5)
    parser.add_argument("--context", type=int, default=3, help="Nearby strings before/after each match")
    args = parser.parse_args()

    data, sections = parse_pe_sections(args.path)
    strings = find_ascii_runs(data, min_length=args.min_string_length)
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in args.pattern]

    print("SECTIONS:")
    for section in sections:
        print(
            f"  {section.name:<8} file=[0x{section.raw_pointer:08X},0x{section.raw_pointer + section.raw_size:08X}) "
            f"rva=0x{section.virtual_address:08X} raw=0x{section.raw_size:08X}"
        )
    print()

    hit_indices = [
        index for index, (_, text) in enumerate(strings) if any(regex.search(text) for regex in compiled)
    ]
    if not hit_indices:
        print("NO_MATCHES")
        return

    print("MATCHES:")
    for index in hit_indices:
        start = max(0, index - args.context)
        stop = min(len(strings), index + args.context + 1)
        offset, text = strings[index]
        print(
            f"- hit file_offset=0x{offset:08X} section={owning_section(sections, offset)} "
            f"text={text[:160]}"
        )
        for near_index in range(start, stop):
            near_offset, near_text = strings[near_index]
            marker = ">" if near_index == index else " "
            print(f"  {marker} 0x{near_offset:08X} [{owning_section(sections, near_offset):<8}] {near_text[:160]}")
        print()


if __name__ == "__main__":
    main()
