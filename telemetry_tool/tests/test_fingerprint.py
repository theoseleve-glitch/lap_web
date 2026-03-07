"""Tests for provenance fingerprinting (file hash + data fingerprint)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash


class TestFileHash:
    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        h = compute_file_hash(str(f))
        assert isinstance(h, str) and len(h) == 64

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        content = "x,y\n1.0,2.0\n3.0,4.0\n"
        f1.write_text(content)
        f2.write_text(content)
        assert compute_file_hash(str(f1)) == compute_file_hash(str(f2))

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("a,b\n1,2\n")
        f2.write_text("a,b\n1,3\n")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))


class TestDataFingerprint:
    def test_returns_hex_string(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        fp = compute_data_fingerprint(df)
        assert isinstance(fp, str) and len(fp) == 64

    def test_same_data_same_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        df2 = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        assert compute_data_fingerprint(df1) == compute_data_fingerprint(df2)

    def test_column_order_irrelevant(self):
        df1 = pd.DataFrame({"a": [1.0], "b": [2.0]})
        df2 = pd.DataFrame({"b": [2.0], "a": [1.0]})
        assert compute_data_fingerprint(df1) == compute_data_fingerprint(df2)

    def test_different_values_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0]})
        df2 = pd.DataFrame({"a": [1.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_columns_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0]})
        df2 = pd.DataFrame({"b": [1.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_shape_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0]})
        df2 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)
