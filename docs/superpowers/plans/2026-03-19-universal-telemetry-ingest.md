# Universal Telemetry Ingest Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing adapter registry with streaming support, 8 new format parsers (VBOX, RaceBox CSV, Qstarz CSV, iRacing binary, MoTeC binary, AiM, RaceChrono RCZ, Qstarz stub), and distance/lap derivation for GPS-only formats.

**Architecture:** Build on `telemetry_tool/adapters/` — add `stream()` + `EXTENSIONS` to `BaseAdapter`, add `stream_file()` + `detect_format_two_pass()` to registry, then implement new adapters one at a time with TDD. Pipeline integration via `s01_ingest.py` derivation block for `distance_m` / `lap_number`.

**Tech Stack:** Python 3.x, pandas, pyarrow, scipy (cumulative_trapezoid), ibt (PyPI), ldparser (PyPI)

**Spec:** `docs/superpowers/specs/2026-03-19-universal-telemetry-ingest-design.md`

---

## File Map

### Modified Files

| File | Responsibility | Changes |
|------|---------------|---------|
| `telemetry_tool/adapters/base.py` | BaseAdapter ABC | Add `EXTENSIONS`, `MAGIC_BYTES`, `stream()`, `supports_streaming` |
| `telemetry_tool/adapters/registry.py` | Format detection + parsing entry point | Add `supported_extensions()`, `stream_file()`, `detect_format_two_pass()` |
| `telemetry_tool/adapters/__init__.py` | Auto-registration | Import + register new adapters |
| `telemetry_tool/pipeline/stages/s01_ingest.py` | Ingest stage | Add `distance_m` / `lap_number` derivation for formats lacking them |
| `telemetry_tool/web/routes/sessions_v2.py` | Upload route | Use `registry.supported_extensions()` for dynamic ALLOWED set |

### New Files

| File | Responsibility |
|------|---------------|
| `telemetry_tool/adapters/errors.py` | `ParseError`, `UnrecognizedFormat`, `MissingColumns`, `CorruptedFile`, `MissingDependency`, `InsufficientData` |
| `telemetry_tool/adapters/vbox_adapter.py` | VBOX `.vbo` section-based text parser |
| `telemetry_tool/adapters/racebox_adapter.py` | RaceBox CSV variable-header parser |
| `telemetry_tool/adapters/qstarz_csv_adapter.py` | Qstarz CSV export parser |
| `telemetry_tool/adapters/iracing_binary_adapter.py` | iRacing `.ibt` binary via `ibt` library |
| `telemetry_tool/adapters/motec_binary_adapter.py` | MoTeC `.ld`/`.ldx` binary via `ldparser` library |
| `telemetry_tool/adapters/aim_adapter.py` | AiM `.xrk`/`.xrz` SDK-backed or stub |
| `telemetry_tool/adapters/racechrono_rcz_adapter.py` | RaceChrono `.rcz` ZIP container |
| `telemetry_tool/adapters/qstarz_binary_stub.py` | Stub directing user to CSV export |
| `telemetry_tool/tests/adapters/__init__.py` | Test package init |
| `telemetry_tool/tests/adapters/conftest.py` | Shared fixtures + sample file generators |
| `telemetry_tool/tests/adapters/contract.py` | `AdapterContractTests` mixin |
| `telemetry_tool/tests/adapters/test_base_streaming.py` | Tests for BaseAdapter streaming additions |
| `telemetry_tool/tests/adapters/test_registry_enhanced.py` | Tests for registry enhancements |
| `telemetry_tool/tests/adapters/test_vbox.py` | VBOX adapter tests |
| `telemetry_tool/tests/adapters/test_racebox.py` | RaceBox adapter tests |
| `telemetry_tool/tests/adapters/test_qstarz_csv.py` | Qstarz CSV adapter tests |
| `telemetry_tool/tests/adapters/test_derivation.py` | Tests for distance/lap derivation in s01_ingest |
| `telemetry_tool/tests/adapters/fixtures/` | Sample files per format |

---

## Chunk 1: Foundation — BaseAdapter Streaming + Registry Enhancements + Errors

### Task 1: Error Hierarchy

**Files:**
- Create: `telemetry_tool/adapters/errors.py`
- Test: `telemetry_tool/tests/adapters/test_errors.py`

- [ ] **Step 1: Write failing test for error hierarchy**

```python
# telemetry_tool/tests/adapters/test_errors.py
import pytest
from telemetry_tool.adapters.errors import (
    ParseError, UnrecognizedFormat, MissingColumns,
    CorruptedFile, MissingDependency, InsufficientData,
)


def test_all_errors_inherit_parse_error():
    for cls in (UnrecognizedFormat, MissingColumns, CorruptedFile,
                MissingDependency, InsufficientData):
        assert issubclass(cls, ParseError)


def test_unrecognized_format_carries_candidates():
    err = UnrecognizedFormat(
        "No match", format_name="unknown", file_path="/tmp/x.bin",
        candidates=[("racechrono", 0.3), ("iracing", 0.1)],
    )
    assert err.candidates[0] == ("racechrono", 0.3)
    assert "No match" in str(err)


def test_missing_dependency_carries_install_hint():
    err = MissingDependency(
        "Library not found", format_name="motec_ld", file_path="/tmp/x.ld",
        package="ldparser", install_hint="pip install ldparser",
    )
    assert err.package == "ldparser"
    assert "pip install" in err.install_hint


def test_missing_columns_carries_lists():
    err = MissingColumns(
        "Missing cols", format_name="vbox", file_path="/tmp/x.vbo",
        missing=["time_s"], available=["speed_mps"],
    )
    assert err.missing == ["time_s"]
    assert err.available == ["speed_mps"]


def test_insufficient_data_carries_counts():
    err = InsufficientData(
        "Too few rows", format_name="vbox", file_path="/tmp/x.vbo",
        row_count=5, minimum=100,
    )
    assert err.row_count == 5
    assert err.minimum == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/adapters/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'telemetry_tool.adapters.errors'`

- [ ] **Step 3: Implement errors module**

```python
# telemetry_tool/adapters/errors.py
"""Error hierarchy for telemetry format adapters."""
from __future__ import annotations


class ParseError(Exception):
    """Base error for all adapter parse failures."""

    def __init__(self, message: str, *, format_name: str, file_path: str):
        super().__init__(message)
        self.format_name = format_name
        self.file_path = file_path


class UnrecognizedFormat(ParseError):
    """No adapter scored above the confidence threshold."""

    def __init__(
        self, message: str, *, format_name: str, file_path: str,
        candidates: list[tuple[str, float]],
    ):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.candidates = candidates


class MissingColumns(ParseError):
    """Required canonical columns not found after mapping."""

    def __init__(
        self, message: str, *, format_name: str, file_path: str,
        missing: list[str], available: list[str],
    ):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.missing = missing
        self.available = available


class CorruptedFile(ParseError):
    """File matched format but data is unreadable."""

    def __init__(
        self, message: str, *, format_name: str, file_path: str,
        offset: int | None = None,
    ):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.offset = offset


class MissingDependency(ParseError):
    """Adapter library not installed."""

    def __init__(
        self, message: str, *, format_name: str, file_path: str,
        package: str, install_hint: str,
    ):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.package = package
        self.install_hint = install_hint


class InsufficientData(ParseError):
    """File parsed but has fewer rows than minimum for analysis."""

    def __init__(
        self, message: str, *, format_name: str, file_path: str,
        row_count: int, minimum: int,
    ):
        super().__init__(message, format_name=format_name, file_path=file_path)
        self.row_count = row_count
        self.minimum = minimum
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/adapters/test_errors.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/adapters/errors.py telemetry_tool/tests/adapters/
git commit -m "feat(adapters): add error hierarchy for format detection failures"
```

---

### Task 2: BaseAdapter Streaming Additions

**Files:**
- Modify: `telemetry_tool/adapters/base.py`
- Test: `telemetry_tool/tests/adapters/test_base_streaming.py`

- [ ] **Step 1: Write failing tests for new BaseAdapter attributes**

```python
# telemetry_tool/tests/adapters/test_base_streaming.py
import pandas as pd
import pytest
from telemetry_tool.adapters.base import BaseAdapter


class ConcreteAdapter(BaseAdapter):
    """Minimal concrete subclass for testing."""
    FORMAT_NAME = "test"
    EXTENSIONS = [".test"]

    @staticmethod
    def detect(file_path: str) -> float:
        return 0.0

    def parse(self, file_path, progress_cb=None):
        return pd.DataFrame({"time_s": [1.0, 2.0], "speed_mps": [10.0, 20.0]})

    def metadata(self):
        return {}

    def available_channels(self):
        return ["time_s", "speed_mps"]


class StreamingAdapter(ConcreteAdapter):
    """Override stream() to test supports_streaming."""
    FORMAT_NAME = "test_streaming"

    def stream(self, file_path, *, config=None, progress_cb=None):
        df = self.parse(file_path)
        mid = len(df) // 2
        yield df.iloc[:mid]
        yield df.iloc[mid:]


def test_base_has_extensions_default():
    assert BaseAdapter.EXTENSIONS == []


def test_base_has_magic_bytes_default():
    assert BaseAdapter.MAGIC_BYTES is None


def test_concrete_extensions():
    adapter = ConcreteAdapter()
    assert adapter.EXTENSIONS == [".test"]


def test_default_stream_yields_single_dataframe():
    adapter = ConcreteAdapter()
    chunks = list(adapter.stream("/fake/path"))
    assert len(chunks) == 1
    assert list(chunks[0].columns) == ["time_s", "speed_mps"]
    assert len(chunks[0]) == 2


def test_supports_streaming_false_for_default():
    adapter = ConcreteAdapter()
    assert adapter.supports_streaming is False


def test_supports_streaming_true_for_override():
    adapter = StreamingAdapter()
    assert adapter.supports_streaming is True


def test_overridden_stream_yields_multiple_chunks():
    adapter = StreamingAdapter()
    chunks = list(adapter.stream("/fake/path"))
    assert len(chunks) == 2
    total_rows = sum(len(c) for c in chunks)
    assert total_rows == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/adapters/test_base_streaming.py -v`
Expected: FAIL — `AttributeError: type object 'BaseAdapter' has no attribute 'EXTENSIONS'`

- [ ] **Step 3: Add streaming support to BaseAdapter**

Add to `telemetry_tool/adapters/base.py` after the existing `data_tier()` method (around line 103):

```python
    # At class level, after FORMAT_NAME:
    EXTENSIONS: list[str] = []
    MAGIC_BYTES: bytes | None = None

    # After data_tier() method:
    def stream(
        self,
        file_path: str,
        *,
        config: object | None = None,
        progress_cb: object | None = None,
    ) -> "Iterator[pd.DataFrame]":
        """Yield bounded-memory DataFrame chunks in canonical column names.

        Default: calls self.parse() and yields the full DataFrame as one chunk.
        Adapters for large files should override with chunked reading.
        """
        df = self.parse(file_path, progress_cb=progress_cb)
        yield df

    @property
    def supports_streaming(self) -> bool:
        """True if stream() is overridden with native chunked reading."""
        return type(self).stream is not BaseAdapter.stream
```

Also add `from typing import Iterator` to the imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/adapters/test_base_streaming.py -v`
Expected: 7 PASS

- [ ] **Step 5: Run existing adapter tests to ensure nothing broke**

Run: `pytest telemetry_tool/tests/ -k "adapter" -v --tb=short 2>/dev/null || pytest telemetry_tool/tests/ -v --tb=short -x -q`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/adapters/base.py telemetry_tool/tests/adapters/test_base_streaming.py
git commit -m "feat(adapters): add EXTENSIONS, MAGIC_BYTES, stream(), supports_streaming to BaseAdapter"
```

---

### Task 3: Registry Enhancements

**Files:**
- Modify: `telemetry_tool/adapters/registry.py`
- Test: `telemetry_tool/tests/adapters/test_registry_enhanced.py`

- [ ] **Step 1: Write failing tests for registry additions**

```python
# telemetry_tool/tests/adapters/test_registry_enhanced.py
import pandas as pd
import pytest
from unittest.mock import patch

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.registry import (
    register_adapter, supported_extensions, stream_file,
    detect_format_two_pass, _ADAPTERS,
)


class FakeVboxAdapter(BaseAdapter):
    FORMAT_NAME = "fake_vbox"
    EXTENSIONS = [".vbo"]

    @staticmethod
    def detect(file_path: str) -> float:
        if file_path.endswith(".vbo"):
            return 0.9
        return 0.0

    def parse(self, file_path, progress_cb=None):
        return pd.DataFrame({"time_s": [1.0], "speed_mps": [10.0]})

    def metadata(self):
        return {"format": "vbox"}

    def available_channels(self):
        return ["time_s", "speed_mps"]


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Save and restore global registry for test isolation."""
    saved = list(_ADAPTERS)
    yield
    _ADAPTERS.clear()
    _ADAPTERS.extend(saved)


def test_supported_extensions_includes_registered():
    register_adapter(FakeVboxAdapter)
    exts = supported_extensions()
    assert ".vbo" in exts


def test_supported_extensions_empty_when_no_extensions_set():
    # Existing adapters have EXTENSIONS=[] by default
    exts = supported_extensions()
    # Should still return empty set for adapters without EXTENSIONS
    assert isinstance(exts, set)


def test_detect_format_two_pass_matches_by_extension(tmp_path):
    register_adapter(FakeVboxAdapter)
    vbo = tmp_path / "session.vbo"
    vbo.write_text("sats,time,lat,long,velocity\n1,0.0,51.0,-1.0,30.0\n")
    cls, conf = detect_format_two_pass(str(vbo))
    assert cls is FakeVboxAdapter
    assert conf == 0.9


def test_detect_format_two_pass_falls_back_to_all(tmp_path):
    register_adapter(FakeVboxAdapter)
    # .vbo file with wrong content — FakeVboxAdapter still matches on extension
    csv = tmp_path / "session.csv"
    csv.write_text("Time (s),Speed (m/s)\n0.0,10.0\n")
    cls, conf = detect_format_two_pass(str(csv))
    # Should fall through to adapters without EXTENSIONS filter
    assert cls is not None or conf == 0.0  # depends on what's registered


def test_stream_file_yields_dataframes(tmp_path):
    register_adapter(FakeVboxAdapter)
    vbo = tmp_path / "session.vbo"
    vbo.write_text("fake data")
    chunks = list(stream_file(str(vbo)))
    assert len(chunks) >= 1
    assert isinstance(chunks[0], pd.DataFrame)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/adapters/test_registry_enhanced.py -v`
Expected: FAIL — `ImportError: cannot import name 'supported_extensions'`

- [ ] **Step 3: Add new functions to registry.py**

Append to `telemetry_tool/adapters/registry.py` after the existing `parse_file()` function:

```python
def supported_extensions() -> set[str]:
    """Return all file extensions from registered adapters' EXTENSIONS class var."""
    exts: set[str] = set()
    for cls in _ADAPTERS:
        exts.update(getattr(cls, "EXTENSIONS", []))
    return exts


def detect_format_two_pass(
    file_path: str,
) -> tuple[Type[BaseAdapter] | None, float]:
    """Enhanced detection with extension pre-filtering.

    1. Filter adapters whose EXTENSIONS match the file's suffix.
    2. If no EXTENSIONS match, include all adapters (backward compat).
    3. Run detect() on candidates, return highest above _MIN_CONFIDENCE.
    """
    from pathlib import Path
    suffix = Path(file_path).suffix.lower()

    # Pass 1: filter by extension
    ext_matches = [cls for cls in _ADAPTERS if suffix in getattr(cls, "EXTENSIONS", [])]
    candidates = ext_matches if ext_matches else list(_ADAPTERS)

    best_cls: Type[BaseAdapter] | None = None
    best_conf: float = 0.0

    for cls in candidates:
        try:
            conf = cls.detect(file_path)
        except Exception:
            logger.debug(
                "Adapter %s raised during detect() for %s; skipping.",
                cls.FORMAT_NAME, file_path, exc_info=True,
            )
            conf = 0.0
        if conf > best_conf:
            best_conf = conf
            best_cls = cls

    if best_conf < _MIN_CONFIDENCE:
        return None, best_conf

    logger.info(
        "Two-pass detected: %s (confidence=%.2f) for %s",
        best_cls.FORMAT_NAME if best_cls else "unknown", best_conf, file_path,
    )
    return best_cls, best_conf


def stream_file(
    file_path: str,
    *,
    config: object | None = None,
    progress_cb: object | None = None,
) -> "Iterator[pd.DataFrame]":
    """Detect format and stream file as DataFrame chunks.

    Uses detect_format_two_pass() for detection, then calls
    adapter.stream() for chunked reading.

    Raises ValueError if no adapter matches.
    """
    from typing import Iterator
    cls, confidence = detect_format_two_pass(file_path)
    if cls is None:
        raise ValueError(
            f"No adapter matched file '{file_path}'. "
            f"Registered: {[a.FORMAT_NAME for a in _ADAPTERS] or '(none)'}."
        )
    adapter = cls()
    yield from adapter.stream(file_path, config=config, progress_cb=progress_cb)
```

Also add `from typing import Iterator` to the module-level imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/adapters/test_registry_enhanced.py -v`
Expected: 4+ PASS

- [ ] **Step 5: Run all existing tests**

Run: `pytest telemetry_tool/tests/ -v --tb=short -x -q`
Expected: All pass — no regressions.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/adapters/registry.py telemetry_tool/tests/adapters/test_registry_enhanced.py
git commit -m "feat(adapters): add supported_extensions, stream_file, detect_format_two_pass to registry"
```

---

### Task 4: AdapterContractTests Mixin

**Files:**
- Create: `telemetry_tool/tests/adapters/contract.py`
- Create: `telemetry_tool/tests/adapters/conftest.py`

- [ ] **Step 1: Write the contract test mixin**

```python
# telemetry_tool/tests/adapters/contract.py
"""Universal contract tests that every adapter must pass.

Usage: inherit AdapterContractTests in your adapter's test file and set
the class attributes: adapter_cls, sample_file_path, wrong_format_path.
"""
from __future__ import annotations

import pandas as pd
import pytest


class AdapterContractTests:
    """Mixin — set these on your test class before use."""

    adapter_cls = None       # Type[BaseAdapter]
    sample_file_path = None  # str — path to a valid sample file for this format
    wrong_format_path = None # str — path to a file of a DIFFERENT format

    def _make_adapter(self):
        assert self.adapter_cls is not None, "Set adapter_cls on the test class"
        return self.adapter_cls()

    def test_detect_high_confidence_for_own_format(self):
        assert self.sample_file_path is not None
        conf = self.adapter_cls.detect(self.sample_file_path)
        assert conf >= 0.5, f"Expected >=0.5, got {conf}"

    def test_detect_low_confidence_for_wrong_format(self):
        assert self.wrong_format_path is not None
        conf = self.adapter_cls.detect(self.wrong_format_path)
        assert conf < 0.5, f"Expected <0.5, got {conf}"

    def test_parse_returns_dataframe(self):
        adapter = self._make_adapter()
        df = adapter.parse(self.sample_file_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_required_columns_present(self):
        adapter = self._make_adapter()
        df = adapter.parse(self.sample_file_path)
        # Minimum: time_s + speed_mps (distance_m and lap_number are derivable)
        assert "time_s" in df.columns, f"Missing time_s. Columns: {list(df.columns)}"
        assert "speed_mps" in df.columns, f"Missing speed_mps. Columns: {list(df.columns)}"

    def test_units_are_si(self):
        adapter = self._make_adapter()
        df = adapter.parse(self.sample_file_path)
        if "speed_mps" in df.columns:
            max_speed = df["speed_mps"].max()
            # m/s range: karting ~30, F1 ~100, sim ~90. If > 150 → likely km/h
            assert max_speed < 150, f"speed_mps max={max_speed} — likely not m/s"

    def test_time_monotonically_increasing(self):
        adapter = self._make_adapter()
        df = adapter.parse(self.sample_file_path)
        if "time_s" in df.columns:
            diffs = df["time_s"].diff().dropna()
            assert (diffs >= 0).all(), "time_s is not monotonically increasing"

    def test_metadata_returns_dict(self):
        adapter = self._make_adapter()
        adapter.parse(self.sample_file_path)
        meta = adapter.metadata()
        assert isinstance(meta, dict)

    def test_available_channels_returns_list(self):
        adapter = self._make_adapter()
        adapter.parse(self.sample_file_path)
        channels = adapter.available_channels()
        assert isinstance(channels, list)

    def test_stream_yields_dataframes(self):
        adapter = self._make_adapter()
        chunks = list(adapter.stream(self.sample_file_path))
        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk, pd.DataFrame)

    def test_stream_total_rows_match_parse(self):
        adapter = self._make_adapter()
        df_full = adapter.parse(self.sample_file_path)
        # Re-create adapter for clean state
        adapter2 = self._make_adapter()
        chunks = list(adapter2.stream(self.sample_file_path))
        total_rows = sum(len(c) for c in chunks)
        assert total_rows == len(df_full)

    def test_empty_file_returns_zero_confidence(self, tmp_path):
        ext = ""
        if self.adapter_cls.EXTENSIONS:
            ext = self.adapter_cls.EXTENSIONS[0]
        empty = tmp_path / f"empty{ext}"
        empty.write_text("")
        conf = self.adapter_cls.detect(str(empty))
        assert conf == 0.0

    def test_nonexistent_file_returns_zero_confidence(self):
        conf = self.adapter_cls.detect("/nonexistent/path/file.xyz")
        assert conf == 0.0
```

- [ ] **Step 2: Create conftest with fixture helpers**

```python
# telemetry_tool/tests/adapters/conftest.py
"""Shared fixtures for adapter tests."""
from __future__ import annotations

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    """Return path to the fixtures directory."""
    return FIXTURES_DIR


def write_vbox_sample(path: Path) -> Path:
    """Generate a minimal valid VBOX .vbo file."""
    content = """[header]
satellites
time
latitude
longitude
velocity knots
heading
height
vert vel
[column names]
sats time lat long velocity heading height vertvel
[data]
8 120000 3060000 -00060000 58.0 180.0 100.0 0.5
9 120100 3060010 -00060010 59.5 181.0 100.1 0.3
10 120200 3060020 -00060020 60.0 182.0 100.2 0.1
"""
    vbo = path / "sample.vbo"
    vbo.write_text(content)
    return vbo


def write_racebox_csv_sample(path: Path) -> Path:
    """Generate a minimal valid RaceBox CSV file."""
    content = """UTC Time,Latitude,Longitude,Speed(km/h),Altitude(m),Heading
2026-03-19T10:00:00.000Z,51.5074,-0.1278,80.5,30.0,180.0
2026-03-19T10:00:00.100Z,51.5075,-0.1279,82.0,30.1,181.0
2026-03-19T10:00:00.200Z,51.5076,-0.1280,83.5,30.2,182.0
"""
    csv = path / "racebox_sample.csv"
    csv.write_text(content)
    return csv


def write_qstarz_csv_sample(path: Path) -> Path:
    """Generate a minimal valid Qstarz CSV export."""
    content = """INDEX,RCR,DATE,TIME,LATITUDE N/S,LONGITUDE E/W,HEIGHT,SPEED,HEADING
1,T,2026/03/19,10:00:00.000,51.5074000N,000.1278000W,30.0,80.5,180.0
2,T,2026/03/19,10:00:00.100,51.5075000N,000.1279000W,30.1,82.0,181.0
3,T,2026/03/19,10:00:00.200,51.5076000N,000.1280000W,30.2,83.5,182.0
"""
    csv = path / "qstarz_sample.csv"
    csv.write_text(content)
    return csv


def write_racechrono_csv_sample(path: Path) -> Path:
    """Generate a minimal valid RaceChrono CSV file (for cross-format tests)."""
    content = """Logged at 10 Hz
Time (s),Speed (m/s),Distance (m),Lap #,Latitude (deg),Longitude (deg)
0.0,10.0,0.0,1,51.5074,-0.1278
0.1,10.5,1.0,1,51.5075,-0.1279
0.2,11.0,2.1,1,51.5076,-0.1280
"""
    csv = path / "racechrono_sample.csv"
    csv.write_text(content)
    return csv
```

- [ ] **Step 3: Create __init__.py + fixtures dir**

```bash
mkdir -p telemetry_tool/tests/adapters/fixtures
touch telemetry_tool/tests/adapters/__init__.py
touch telemetry_tool/tests/adapters/fixtures/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/adapters/
git commit -m "feat(adapters): add AdapterContractTests mixin and shared test fixtures"
```

---

### Task 5: Distance / Lap Derivation in s01_ingest

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s01_ingest.py`
- Test: `telemetry_tool/tests/adapters/test_derivation.py`

- [ ] **Step 1: Write failing tests for derivation**

```python
# telemetry_tool/tests/adapters/test_derivation.py
"""Test distance_m and lap_number derivation for GPS-only formats."""
import numpy as np
import pandas as pd
import pytest


def _derive_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Import the derivation function we'll add to s01_ingest."""
    from telemetry_tool.pipeline.stages.s01_ingest import derive_missing_columns
    return derive_missing_columns(df)


def test_distance_derived_from_speed_and_time():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0, 2.0, 3.0],
        "Speed (m/s)": [0.0, 10.0, 10.0, 10.0],
    })
    result = _derive_distance(df)
    assert "Distance (m)" in result.columns
    # cumulative_trapezoid: [5.0, 15.0, 25.0] with initial=0
    np.testing.assert_allclose(result["Distance (m)"].values, [0.0, 5.0, 15.0, 25.0])


def test_distance_not_overwritten_if_present():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
        "Distance (m)": [0.0, 999.0],
    })
    result = _derive_distance(df)
    assert result["Distance (m)"].iloc[1] == 999.0  # untouched


def test_lap_number_sentinel_if_missing():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
    })
    result = _derive_distance(df)
    assert "Lap #" in result.columns
    assert (result["Lap #"] == 0).all()


def test_lap_number_not_overwritten_if_present():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
        "Lap #": [1, 2],
    })
    result = _derive_distance(df)
    assert result["Lap #"].iloc[1] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/adapters/test_derivation.py -v`
Expected: FAIL — `ImportError: cannot import name 'derive_missing_columns'`

- [ ] **Step 3: Add derive_missing_columns to s01_ingest.py**

Add this function to `telemetry_tool/pipeline/stages/s01_ingest.py` (before `run_ingest`):

```python
def derive_missing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Derive distance_m and lap_number when the source format lacks them.

    Called after canonical->RaceChrono reverse mapping, so column names are
    RaceChrono-style ("Distance (m)", "Lap #", etc.).
    """
    # Derive distance from speed integration
    if "Distance (m)" not in df.columns and "Speed (m/s)" in df.columns and "Time (s)" in df.columns:
        try:
            from scipy.integrate import cumulative_trapezoid
            speed = pd.to_numeric(df["Speed (m/s)"], errors="coerce").fillna(0).values
            time = pd.to_numeric(df["Time (s)"], errors="coerce").values
            dist = cumulative_trapezoid(speed, time, initial=0)
            df["Distance (m)"] = dist
            logger.info("Derived Distance (m) from speed integration")
        except ImportError:
            logger.warning("scipy not available; cannot derive Distance (m)")

    # Sentinel lap number if not present (pipeline stages 3-5 derive real laps)
    if "Lap #" not in df.columns:
        df["Lap #"] = 0
        logger.info("Set sentinel Lap # = 0 (will be derived by track detection)")

    return df
```

Then call it in `run_ingest()` after the reverse-mapping block (after line 119), before column discovery:

```python
    # ── 3b. Derive missing columns (distance, lap) ────────────
    raw_df = derive_missing_columns(raw_df)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/adapters/test_derivation.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v --tb=short -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/pipeline/stages/s01_ingest.py telemetry_tool/tests/adapters/test_derivation.py
git commit -m "feat(ingest): derive distance_m and lap_number for GPS-only formats"
```

---

## Chunk 2: Tier 1 Adapters — VBOX, RaceBox CSV, Qstarz CSV

### Task 6: VboxAdapter

**Files:**
- Create: `telemetry_tool/adapters/vbox_adapter.py`
- Test: `telemetry_tool/tests/adapters/test_vbox.py`
- Fixture: `telemetry_tool/tests/adapters/fixtures/sample.vbo` (generated by conftest helper)

- [ ] **Step 1: Write failing contract + format-specific tests**

```python
# telemetry_tool/tests/adapters/test_vbox.py
import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_vbox_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.vbox_adapter import VboxAdapter


class TestVboxContract(AdapterContractTests):
    adapter_cls = VboxAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_vbox_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestVboxSpecific:
    def test_velocity_knots_converted_to_mps(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        # 58 knots = 58 * 0.514444 ≈ 29.84 m/s
        assert 29.0 < df["speed_mps"].iloc[0] < 31.0

    def test_lat_long_converted_to_degrees(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        # 3060000 minutes*1e-5 = 3060000 / 60000 = 51.0 degrees
        assert 50.0 < df["lat_deg"].iloc[0] < 52.0

    def test_sections_parsed_correctly(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        assert len(df) == 3
        assert "time_s" in df.columns

    def test_detect_returns_high_for_vbo(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        assert VboxAdapter.detect(str(vbo)) >= 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/adapters/test_vbox.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement VboxAdapter**

```python
# telemetry_tool/adapters/vbox_adapter.py
"""VBOX .vbo telemetry adapter.

Parses section-based text format with [header], [column names], [data].
Converts velocity from knots to m/s, lat/long from minutes*1e-5 to degrees.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Iterator, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_KNOTS_TO_MPS: Final[float] = 0.514444
_LATLONG_DIVISOR: Final[float] = 60000.0
_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# Canonical column mapping: vbox column index -> (canonical_name, converter)
# Standard VBOX order: sats, time, lat, long, velocity, heading, height, vertvel, event1
_COLUMN_ORDER: Final[list[tuple[str, str]]] = [
    ("sats", "satellites"),
    ("time", "time_s"),
    ("lat", "lat_deg"),
    ("long", "lon_deg"),
    ("velocity", "speed_mps"),
    ("heading", "heading_deg"),
    ("height", "altitude_m"),
    ("vertvel", "raw_vert_vel"),
]


class VboxAdapter(BaseAdapter):
    """Adapter for RaceLogic VBOX .vbo files."""

    FORMAT_NAME: str = "vbox"
    EXTENSIONS: list[str] = [".vbo"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() != ".vbo":
                return 0.0

            for enc in _ENCODINGS:
                try:
                    with path.open(encoding=enc) as fh:
                        for i, line in enumerate(fh):
                            if i > 50:
                                break
                            stripped = line.strip().lower()
                            if stripped in ("[header]", "[column names]"):
                                return 0.9
                    return 0.0
                except UnicodeDecodeError:
                    continue
            return 0.0
        except Exception:
            return 0.0

    def parse(self, file_path: str, progress_cb: Optional[object] = None) -> pd.DataFrame:
        path = Path(file_path)
        lines = _read_all_lines(path)
        header_info, col_names, data_lines = _parse_sections(lines)

        self._metadata = header_info

        df = _build_dataframe(col_names, data_lines)

        # Unit conversions
        if "speed_mps" in df.columns:
            df["speed_mps"] = pd.to_numeric(df["speed_mps"], errors="coerce") * _KNOTS_TO_MPS
        if "lat_deg" in df.columns:
            df["lat_deg"] = pd.to_numeric(df["lat_deg"], errors="coerce") / _LATLONG_DIVISOR
        if "lon_deg" in df.columns:
            df["lon_deg"] = pd.to_numeric(df["lon_deg"], errors="coerce") / _LATLONG_DIVISOR
        if "time_s" in df.columns:
            # VBOX time is HHMMSS.SS * 100 — convert to seconds from start
            raw_time = pd.to_numeric(df["time_s"], errors="coerce")
            df["time_s"] = _vbox_time_to_seconds(raw_time)

        # Coerce remaining columns to numeric
        for col in df.columns:
            if col not in ("time_s", "speed_mps", "lat_deg", "lon_deg"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self._channels = [c for c in df.columns if not c.startswith("raw_")]
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)


def _read_all_lines(path: Path) -> list[str]:
    for enc in _ENCODINGS:
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _parse_sections(lines: list[str]) -> tuple[dict, list[str], list[str]]:
    """Parse VBOX sections: [header], [column names], [data]."""
    section = None
    header_info: dict = {}
    col_names: list[str] = []
    data_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if lower.startswith("[") and lower.endswith("]"):
            section = lower[1:-1]
            continue

        if not stripped:
            continue

        if section == "header":
            header_info[stripped] = stripped
        elif section == "column names" or section == "satellites":
            # Column names are space-separated on one line
            if not col_names:
                col_names = stripped.split()
        elif section == "data":
            data_lines.append(stripped)

    return header_info, col_names, data_lines


def _build_dataframe(col_names: list[str], data_lines: list[str]) -> pd.DataFrame:
    """Build DataFrame from parsed VBOX data."""
    canonical_names = []
    for i, name in enumerate(col_names):
        lower = name.lower()
        # Map to canonical using _COLUMN_ORDER
        matched = False
        for vbox_name, canonical in _COLUMN_ORDER:
            if lower == vbox_name or lower.startswith(vbox_name):
                canonical_names.append(canonical)
                matched = True
                break
        if not matched:
            canonical_names.append(f"raw_{lower}")

    rows = []
    for line in data_lines:
        cells = line.split()
        if len(cells) >= len(canonical_names):
            rows.append(cells[:len(canonical_names)])
        elif cells:
            # Pad with NaN
            padded = cells + [None] * (len(canonical_names) - len(cells))
            rows.append(padded)

    if not rows:
        return pd.DataFrame(columns=canonical_names)

    return pd.DataFrame(rows, columns=canonical_names)


def _vbox_time_to_seconds(raw_time: pd.Series) -> pd.Series:
    """Convert VBOX time (HHMMSS.SS * 100 format) to seconds from session start."""
    # VBOX time format: HHMMSSCC where CC = centiseconds
    # e.g., 120000 = 12:00:00.00
    time_val = raw_time.values.copy()
    hours = (time_val // 10000).astype(float)
    remainder = time_val % 10000
    minutes = (remainder // 100).astype(float)
    seconds = (remainder % 100).astype(float)
    abs_seconds = hours * 3600 + minutes * 60 + seconds
    # Relative to session start
    return pd.Series(abs_seconds - abs_seconds[0] if len(abs_seconds) > 0 else abs_seconds)
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/adapters/test_vbox.py -v`
Expected: All PASS (contract + specific)

- [ ] **Step 5: Register adapter**

Add to `telemetry_tool/adapters/__init__.py`:

```python
from telemetry_tool.adapters.vbox_adapter import VboxAdapter
register_adapter(VboxAdapter)
```

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/adapters/vbox_adapter.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_vbox.py
git commit -m "feat(adapters): add VboxAdapter for .vbo files with knots/minutes conversion"
```

---

### Task 7: RaceBoxCSVAdapter

**Files:**
- Create: `telemetry_tool/adapters/racebox_adapter.py`
- Test: `telemetry_tool/tests/adapters/test_racebox.py`

- [ ] **Step 1: Write failing contract + specific tests**

```python
# telemetry_tool/tests/adapters/test_racebox.py
import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_racebox_csv_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.racebox_adapter import RaceBoxCSVAdapter


class TestRaceBoxContract(AdapterContractTests):
    adapter_cls = RaceBoxCSVAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_racebox_csv_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestRaceBoxSpecific:
    def test_speed_kmh_converted_to_mps(self, tmp_path):
        csv = write_racebox_csv_sample(tmp_path)
        adapter = RaceBoxCSVAdapter()
        df = adapter.parse(str(csv))
        # 80.5 km/h = ~22.36 m/s
        assert 22.0 < df["speed_mps"].iloc[0] < 23.0

    def test_utc_time_parsed_to_seconds(self, tmp_path):
        csv = write_racebox_csv_sample(tmp_path)
        adapter = RaceBoxCSVAdapter()
        df = adapter.parse(str(csv))
        assert df["time_s"].iloc[0] == 0.0
        assert df["time_s"].iloc[1] == pytest.approx(0.1, abs=0.01)

    def test_detect_rejects_racechrono(self, tmp_path):
        csv = write_racechrono_csv_sample(tmp_path)
        assert RaceBoxCSVAdapter.detect(str(csv)) < 0.5
```

- [ ] **Step 2: Run to verify failure, then implement**

The adapter follows the same pattern as VboxAdapter but for RaceBox CSV:
- Detect: look for `"UTC Time"` or `"Speed(km/h)"` in header
- Parse: read CSV, rename columns, convert km/h → m/s, parse UTC timestamps to relative seconds
- Confidence capped at 0.75 (below RaceChrono's 0.9)

- [ ] **Step 3: Implement RaceBoxCSVAdapter**

Implementation pattern: ~120 lines. Key mappings:
```
"UTC Time" → time_s (parse ISO → relative seconds)
"Speed(km/h)" or "Speed (km/h)" → speed_mps (÷ 3.6)
"Latitude" → lat_deg
"Longitude" → lon_deg
"Altitude(m)" or "Altitude (m)" → altitude_m
"Heading" → heading_deg
```

- [ ] **Step 4: Run tests, register, commit**

```bash
git add telemetry_tool/adapters/racebox_adapter.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_racebox.py
git commit -m "feat(adapters): add RaceBoxCSVAdapter for RaceBox CSV exports"
```

---

### Task 8: QstarzCSVAdapter

**Files:**
- Create: `telemetry_tool/adapters/qstarz_csv_adapter.py`
- Test: `telemetry_tool/tests/adapters/test_qstarz_csv.py`

- [ ] **Step 1: Write failing contract + specific tests**

```python
# telemetry_tool/tests/adapters/test_qstarz_csv.py
import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_qstarz_csv_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.qstarz_csv_adapter import QstarzCSVAdapter


class TestQstarzContract(AdapterContractTests):
    adapter_cls = QstarzCSVAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_qstarz_csv_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestQstarzSpecific:
    def test_speed_converted_to_mps(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        adapter = QstarzCSVAdapter()
        df = adapter.parse(str(csv))
        # 80.5 km/h ≈ 22.36 m/s
        assert 22.0 < df["speed_mps"].iloc[0] < 23.0

    def test_lat_ns_parsed_correctly(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        adapter = QstarzCSVAdapter()
        df = adapter.parse(str(csv))
        assert df["lat_deg"].iloc[0] > 0  # N hemisphere

    def test_detect_score_high_for_qstarz(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        assert QstarzCSVAdapter.detect(str(csv)) >= 0.7
```

- [ ] **Step 2: Implement QstarzCSVAdapter**

Key mappings:
```
"DATE" + "TIME" → time_s (parse date+time → relative seconds)
"SPEED" → speed_mps (km/h ÷ 3.6)
"LATITUDE N/S" → lat_deg (strip N/S suffix, negate for S)
"LONGITUDE E/W" → lon_deg (strip E/W suffix, negate for W)
"HEIGHT" → altitude_m
"HEADING" → heading_deg
```
Detection: presence of `"INDEX"` + `"RCR"` + `"DATE"` + `"TIME"` → confidence 0.8.

- [ ] **Step 3: Run tests, register, commit**

```bash
git add telemetry_tool/adapters/qstarz_csv_adapter.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_qstarz_csv.py
git commit -m "feat(adapters): add QstarzCSVAdapter for Qstarz CSV exports"
```

---

## Chunk 3: Tier 2 — Binary Format Adapters (iRacing .ibt, MoTeC .ld)

### Task 9: IRacingBinaryAdapter

**Files:**
- Create: `telemetry_tool/adapters/iracing_binary_adapter.py`
- Test: `telemetry_tool/tests/adapters/test_iracing_binary.py`

- [ ] **Step 1: Write failing tests with library skip**

```python
# telemetry_tool/tests/adapters/test_iracing_binary.py
import pytest

ibt = pytest.importorskip("ibt", reason="ibt library not installed")

from telemetry_tool.adapters.iracing_binary_adapter import IRacingBinaryAdapter


def test_detect_returns_zero_for_csv(tmp_path):
    csv = tmp_path / "session.csv"
    csv.write_text("Time,Speed\n0.0,10.0\n")
    assert IRacingBinaryAdapter.detect(str(csv)) == 0.0


def test_detect_returns_zero_for_nonexistent():
    assert IRacingBinaryAdapter.detect("/nonexistent/file.ibt") == 0.0


def test_extensions_set():
    assert ".ibt" in IRacingBinaryAdapter.EXTENSIONS


def test_format_name():
    assert IRacingBinaryAdapter.FORMAT_NAME == "iracing_ibt"
```

- [ ] **Step 2: Implement IRacingBinaryAdapter**

Structure:
- `detect()`: check file extension `.ibt`, read first 4 bytes for magic, return 0.95 if matches
- `parse()`: use `ibt` library to open file, extract channels, map to canonical names (reuse `_COLUMN_MAP` pattern from existing `iracing_adapter.py`)
- `stream()`: override with chunked reading — read header, then iterate data records in chunks of `config.chunk_size` rows
- If `ibt` not installed: raise `MissingDependency` with `install_hint="pip install ibt"`

Key difference from existing `IRacingAdapter`: this reads native `.ibt` binary, not CSV exports.

- [ ] **Step 3: Run tests, register, commit**

```bash
git add telemetry_tool/adapters/iracing_binary_adapter.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_iracing_binary.py
git commit -m "feat(adapters): add IRacingBinaryAdapter for native .ibt files"
```

---

### Task 10: MoTeCBinaryAdapter

**Files:**
- Create: `telemetry_tool/adapters/motec_binary_adapter.py`
- Test: `telemetry_tool/tests/adapters/test_motec_binary.py`

- [ ] **Step 1: Write failing tests with library skip**

```python
# telemetry_tool/tests/adapters/test_motec_binary.py
import pytest

ldparser = pytest.importorskip("ldparser", reason="ldparser library not installed")

from telemetry_tool.adapters.motec_binary_adapter import MoTeCBinaryAdapter


def test_detect_returns_zero_for_csv(tmp_path):
    csv = tmp_path / "session.csv"
    csv.write_text("Time,Speed\n0.0,10.0\n")
    assert MoTeCBinaryAdapter.detect(str(csv)) == 0.0


def test_extensions_set():
    assert ".ld" in MoTeCBinaryAdapter.EXTENSIONS
    assert ".ldx" in MoTeCBinaryAdapter.EXTENSIONS


def test_format_name():
    assert MoTeCBinaryAdapter.FORMAT_NAME == "motec_ld"
```

- [ ] **Step 2: Implement MoTeCBinaryAdapter**

Structure:
- `detect()`: check `.ld`/`.ldx` extension, read first byte for MoTeC signature, return 0.95
- `parse()`: use `ldparser` to open `.ld`, iterate channels, build DataFrame with canonical names
- Channel mapping: regex-based like existing `motec_adapter.py` `_COLUMN_RULES`
- Beacon column → lap markers if present
- If `ldparser` not installed: raise `MissingDependency`

- [ ] **Step 3: Run tests, register, commit**

```bash
git add telemetry_tool/adapters/motec_binary_adapter.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_motec_binary.py
git commit -m "feat(adapters): add MoTeCBinaryAdapter for native .ld/.ldx files"
```

---

## Chunk 4: Tier 3/4 Stubs + Upload Route + Final Integration

### Task 11: AiM, RaceChrono RCZ, and Qstarz Binary Stubs

**Files:**
- Create: `telemetry_tool/adapters/aim_adapter.py`
- Create: `telemetry_tool/adapters/racechrono_rcz_adapter.py`
- Create: `telemetry_tool/adapters/qstarz_binary_stub.py`

- [ ] **Step 1: Write tests for stub behavior**

```python
# telemetry_tool/tests/adapters/test_stubs.py
import pytest
from telemetry_tool.adapters.errors import MissingDependency
from telemetry_tool.adapters.aim_adapter import AiMAdapter
from telemetry_tool.adapters.racechrono_rcz_adapter import RaceChronoRCZAdapter
from telemetry_tool.adapters.qstarz_binary_stub import QstarzBinaryStub


class TestAiMStub:
    def test_extensions(self):
        assert ".xrk" in AiMAdapter.EXTENSIONS
        assert ".xrz" in AiMAdapter.EXTENSIONS

    def test_detect_nonexistent(self):
        assert AiMAdapter.detect("/nonexistent.xrk") == 0.0

    def test_parse_raises_missing_dependency(self, tmp_path):
        xrk = tmp_path / "session.xrk"
        xrk.write_bytes(b"\x00" * 100)
        adapter = AiMAdapter()
        with pytest.raises(MissingDependency, match="AiM SDK"):
            adapter.parse(str(xrk))


class TestRCZStub:
    def test_extensions(self):
        assert ".rcz" in RaceChronoRCZAdapter.EXTENSIONS

    def test_detect_nonexistent(self):
        assert RaceChronoRCZAdapter.detect("/nonexistent.rcz") == 0.0


class TestQstarzBinaryStub:
    def test_extensions(self):
        assert ".rcnx" in QstarzBinaryStub.EXTENSIONS
        assert ".rcn" in QstarzBinaryStub.EXTENSIONS

    def test_parse_raises_missing_dependency(self, tmp_path):
        rcnx = tmp_path / "session.rcnx"
        rcnx.write_bytes(b"\x00" * 50)
        stub = QstarzBinaryStub()
        with pytest.raises(MissingDependency, match="QRacing"):
            stub.parse(str(rcnx))
```

- [ ] **Step 2: Implement stubs**

Each stub: ~40 lines. `detect()` returns 0.3 for matching extension, `parse()` raises `MissingDependency` with a helpful message directing user to export to CSV.

- [ ] **Step 3: Register all stubs, run tests, commit**

```bash
git add telemetry_tool/adapters/aim_adapter.py telemetry_tool/adapters/racechrono_rcz_adapter.py telemetry_tool/adapters/qstarz_binary_stub.py telemetry_tool/adapters/__init__.py telemetry_tool/tests/adapters/test_stubs.py
git commit -m "feat(adapters): add AiM, RaceChrono RCZ, and Qstarz binary stubs"
```

---

### Task 12: Dynamic Upload Route

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py`

- [ ] **Step 1: Read current ALLOWED set in sessions_v2.py**

Find the hardcoded `ALLOWED` set and replace with dynamic lookup.

- [ ] **Step 2: Replace hardcoded ALLOWED with registry call**

```python
# In sessions_v2.py upload_session(), replace:
#   ALLOWED = {".csv", ".txt", ".ibt", ".ld", ".ldx", ".vbo", ".xrk", ".drk"}
# With:
from telemetry_tool.adapters.registry import supported_extensions

# Merge static fallback with dynamic registry
_STATIC_ALLOWED = {".csv", ".txt"}  # always accepted (GenericCSVAdapter handles these)
ALLOWED = _STATIC_ALLOWED | supported_extensions()
```

- [ ] **Step 3: Verify upload route still works**

Run: `pytest telemetry_tool/tests/ -k "upload" -v --tb=short`
Expected: existing upload tests pass.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/web/routes/sessions_v2.py
git commit -m "feat(upload): use dynamic adapter registry for allowed file extensions"
```

---

### Task 13: Set EXTENSIONS on Existing Adapters

**Files:**
- Modify: `telemetry_tool/adapters/racechrono_adapter.py`
- Modify: `telemetry_tool/adapters/iracing_adapter.py`
- Modify: `telemetry_tool/adapters/acc_adapter.py`
- Modify: `telemetry_tool/adapters/motec_adapter.py`
- Modify: `telemetry_tool/adapters/generic_csv_adapter.py`

- [ ] **Step 1: Add EXTENSIONS to each existing adapter**

```python
# racechrono_adapter.py — add after FORMAT_NAME line:
EXTENSIONS: list[str] = [".csv"]

# iracing_adapter.py:
EXTENSIONS: list[str] = [".csv", ".txt"]

# acc_adapter.py:
EXTENSIONS: list[str] = [".csv"]

# motec_adapter.py:
EXTENSIONS: list[str] = [".csv"]

# generic_csv_adapter.py:
EXTENSIONS: list[str] = [".csv", ".txt"]
```

- [ ] **Step 2: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v --tb=short -x -q`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/adapters/racechrono_adapter.py telemetry_tool/adapters/iracing_adapter.py telemetry_tool/adapters/acc_adapter.py telemetry_tool/adapters/motec_adapter.py telemetry_tool/adapters/generic_csv_adapter.py
git commit -m "feat(adapters): add EXTENSIONS to all existing adapters for two-pass detection"
```

---

### Task 14: Final Integration Test

**Files:**
- Create: `telemetry_tool/tests/adapters/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# telemetry_tool/tests/adapters/test_integration.py
"""End-to-end: file → detect → parse → canonical DataFrame with derived columns."""
import pytest
from telemetry_tool.adapters.registry import (
    parse_file, stream_file, supported_extensions, detect_format_two_pass,
)
from telemetry_tool.tests.adapters.conftest import (
    write_vbox_sample, write_racebox_csv_sample,
    write_qstarz_csv_sample, write_racechrono_csv_sample,
)


def test_supported_extensions_includes_all():
    exts = supported_extensions()
    assert ".vbo" in exts
    assert ".csv" in exts


def test_vbox_detected_and_parsed(tmp_path):
    vbo = write_vbox_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(vbo))
    assert cls is not None
    assert cls.FORMAT_NAME == "vbox"
    assert conf >= 0.8

    df, adapter = parse_file(str(vbo))
    assert "time_s" in df.columns or "Time (s)" in df.columns
    assert len(df) > 0


def test_racebox_detected_and_parsed(tmp_path):
    csv = write_racebox_csv_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(csv))
    assert cls is not None
    assert conf >= 0.5

    df, adapter = parse_file(str(csv))
    assert len(df) > 0


def test_racechrono_still_detected(tmp_path):
    csv = write_racechrono_csv_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(csv))
    assert cls is not None
    assert cls.FORMAT_NAME == "racechrono"


def test_stream_file_yields_chunks(tmp_path):
    vbo = write_vbox_sample(tmp_path)
    chunks = list(stream_file(str(vbo)))
    assert len(chunks) >= 1
    total_rows = sum(len(c) for c in chunks)
    assert total_rows > 0
```

- [ ] **Step 2: Run integration tests**

Run: `pytest telemetry_tool/tests/adapters/test_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite one final time**

Run: `pytest telemetry_tool/tests/ -v --tb=short -q`
Expected: All pass, no regressions.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/adapters/test_integration.py
git commit -m "test(adapters): add integration tests for universal format detection"
```
