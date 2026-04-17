"""Tests for ImmutableBundleStore."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from bundle_intake.storage import ImmutableBundleStore


class TestContentAddressedPaths:
    def test_path_for_two_level_sharding(self, tmp_path):
        store = ImmutableBundleStore(tmp_path)
        ck = "abcdef" + "0" * 58
        p = store.path_for(ck)
        assert p.name == ck + ".zip"
        assert p.parent.name == "ab"

    def test_exists_false_before_promote(self, tmp_path):
        store = ImmutableBundleStore(tmp_path)
        assert not store.exists("f" * 64)


class TestPromote:
    def test_promote_moves_temp_to_canonical_path(self, tmp_path):
        store = ImmutableBundleStore(tmp_path / "store")
        temp = tmp_path / "temp.zip"
        temp.write_bytes(b"PAYLOAD")
        ck = "0" * 64
        dest = store.promote(temp, ck)
        assert dest.is_file()
        assert dest.read_bytes() == b"PAYLOAD"
        assert not temp.exists()
        assert store.exists(ck)

    def test_promote_is_idempotent_when_dest_exists(self, tmp_path):
        store = ImmutableBundleStore(tmp_path / "store")
        ck = "a" * 64

        first = tmp_path / "first.zip"
        first.write_bytes(b"FIRST")
        p1 = store.promote(first, ck)
        assert p1.read_bytes() == b"FIRST"

        # Second "upload" of the same checksum — shouldn't overwrite.
        second = tmp_path / "second.zip"
        second.write_bytes(b"SECOND")
        p2 = store.promote(second, ck)
        assert p2 == p1
        assert p2.read_bytes() == b"FIRST"
        assert not second.exists()

    @pytest.mark.skipif(os.name == "nt", reason="Windows chmod is best-effort only")
    def test_promoted_file_is_read_only(self, tmp_path):
        store = ImmutableBundleStore(tmp_path / "store")
        temp = tmp_path / "t.zip"
        temp.write_bytes(b"x")
        dest = store.promote(temp, "b" * 64)
        assert store.is_readonly(dest)

    def test_different_checksums_go_to_different_shards(self, tmp_path):
        store = ImmutableBundleStore(tmp_path / "store")
        ck1, ck2 = "ab" + "0" * 62, "cd" + "0" * 62
        (tmp_path / "a.zip").write_bytes(b"A")
        (tmp_path / "c.zip").write_bytes(b"C")
        p1 = store.promote(tmp_path / "a.zip", ck1)
        p2 = store.promote(tmp_path / "c.zip", ck2)
        assert p1.parent != p2.parent
