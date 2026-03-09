"""
reporting_pdf.py
----------------
Convert a self-contained HTML report to PDF.

Backend priority
~~~~~~~~~~~~~~~~
1. **WeasyPrint** — pure-Python renderer with excellent CSS support.
   Preferred because it handles base64 data-URIs, CSS grid/flexbox, and
   ``@media print`` correctly, and requires no external binaries.

2. **pdfkit** (Python wrapper around ``wkhtmltopdf``) — uses the Qt WebKit
   engine.  Handles embedded images and dark themes well.  Requires the
   ``wkhtmltopdf`` binary on ``PATH``.

3. **wkhtmltopdf subprocess** — direct ``subprocess.run`` call.  Same
   engine as pdfkit but with no Python dependency beyond ``subprocess``.

The module probes backends at import time and selects the best available.
Callers can also force a backend via the *backend* parameter.

Offline guarantee
~~~~~~~~~~~~~~~~~
The HTML files produced by ``reporting_html.py`` embed all assets as
base64 data-URIs.  No network requests are made during conversion.  The
``--disable-javascript`` and ``--enable-local-file-access`` flags are
set on wkhtmltopdf to ensure clean offline rendering.

Functions
~~~~~~~~~
``generate_pdf_from_html(html_path, output_pdf_path, **options)``
    Convert an HTML file to PDF.

``get_available_backends()``
    Return a list of usable backend names.

``get_default_backend()``
    Return the name of the highest-priority available backend.

Design principles
~~~~~~~~~~~~~~~~~
- Zero global state.  Every conversion is a standalone call.
- All options are keyword-only with physically motivated defaults
  (A4 landscape for widescreen plots, 10 mm margins).
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical PDF bytes (to the extent
  the underlying renderer is deterministic).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional

logger = logging.getLogger(__name__)


# ============================================================================

# Backend detection

# ============================================================================


_HAS_WEASYPRINT: bool = False
_HAS_PDFKIT:     bool = False
_HAS_WKHTMLTOPDF: bool = False

try:
    import weasyprint as _weasyprint  # type: ignore[import-untyped]
    _HAS_WEASYPRINT = True
except (ImportError, OSError):
    # OSError is raised when the Python package is installed but required

    # native libraries (pango, gobject, harfbuzz) are missing.  This is

    # common on Windows where WeasyPrint needs GTK runtime DLLs.

    _weasyprint = None  # type: ignore[assignment]

try:
    import pdfkit as _pdfkit  # type: ignore[import-untyped]
    _HAS_PDFKIT = True
except (ImportError, OSError):
    _pdfkit = None  # type: ignore[assignment]

_WKHTMLTOPDF_BIN: Optional[str] = shutil.which("wkhtmltopdf")
_HAS_WKHTMLTOPDF = _WKHTMLTOPDF_BIN is not None

# Priority order

BACKEND_WEASYPRINT:  Final[str] = "weasyprint"
BACKEND_PDFKIT:      Final[str] = "pdfkit"
BACKEND_WKHTMLTOPDF: Final[str] = "wkhtmltopdf"

_BACKEND_PRIORITY: Final[list[str]] = [
    BACKEND_WEASYPRINT,
    BACKEND_PDFKIT,
    BACKEND_WKHTMLTOPDF,
]

_BACKEND_AVAILABLE: Final[dict[str, bool]] = {
    BACKEND_WEASYPRINT:  _HAS_WEASYPRINT,
    BACKEND_PDFKIT:      _HAS_PDFKIT,
    BACKEND_WKHTMLTOPDF: _HAS_WKHTMLTOPDF,
}


# ============================================================================

# Default conversion options

# ============================================================================


@dataclass(frozen=True)
class PdfOptions:
    """Conversion settings with sensible motorsport-report defaults."""
    page_size:      str   = "A4"
    orientation:    str   = "Landscape"
    margin_top:     str   = "10mm"
    margin_bottom:  str   = "10mm"
    margin_left:    str   = "10mm"
    margin_right:   str   = "10mm"
    print_media:    bool  = True
    no_javascript:  bool  = True
    image_quality:  int   = 100
    encoding:       str   = "UTF-8"


_DEFAULT_OPTIONS: Final[PdfOptions] = PdfOptions()


# ============================================================================

# Exceptions

# ============================================================================


class PdfConversionError(Exception):
    """Raised when HTML → PDF conversion fails."""


class NoBackendError(PdfConversionError):
    """No usable PDF backend is available."""


# ============================================================================

# Backend implementations

# ============================================================================


def _convert_weasyprint(
    html_path: Path,
    output_path: Path,
    opts: PdfOptions,
) -> None:
    """Convert using WeasyPrint."""
    if _weasyprint is None:
        raise PdfConversionError("WeasyPrint is not installed.")

    html_doc = _weasyprint.HTML(filename=str(html_path), encoding=opts.encoding)

    # WeasyPrint uses CSS @page for page layout

    css_page = f"""
    @page {{
        size: {opts.page_size} {opts.orientation.lower()};
        margin: {opts.margin_top} {opts.margin_right} {opts.margin_bottom} {opts.margin_left};
    }}
    @media print {{
        body {{ background: #0f1117; color: #e0e0e0; }}
    }}
    """
    stylesheet = _weasyprint.CSS(string=css_page)
    html_doc.write_pdf(str(output_path), stylesheets=[stylesheet])

    logger.info("WeasyPrint conversion complete: %s", output_path)


def _convert_pdfkit(
    html_path: Path,
    output_path: Path,
    opts: PdfOptions,
) -> None:
    """Convert using pdfkit (wkhtmltopdf wrapper)."""
    if _pdfkit is None:
        raise PdfConversionError("pdfkit is not installed.")

    wk_options: dict[str, str] = {
        "page-size":            opts.page_size,
        "orientation":          opts.orientation,
        "margin-top":           opts.margin_top,
        "margin-bottom":        opts.margin_bottom,
        "margin-left":          opts.margin_left,
        "margin-right":         opts.margin_right,
        "encoding":             opts.encoding,
        "image-quality":        str(opts.image_quality),
        "enable-local-file-access": "",
        "quiet":                "",
    }
    if opts.print_media:
        wk_options["print-media-type"] = ""
    if opts.no_javascript:
        wk_options["disable-javascript"] = ""

    _pdfkit.from_file(str(html_path), str(output_path), options=wk_options)
    logger.info("pdfkit conversion complete: %s", output_path)


def _convert_wkhtmltopdf_subprocess(
    html_path: Path,
    output_path: Path,
    opts: PdfOptions,
) -> None:
    """Convert using a direct wkhtmltopdf subprocess call."""
    if _WKHTMLTOPDF_BIN is None:
        raise PdfConversionError(
            "wkhtmltopdf binary not found on PATH."
        )

    cmd: list[str] = [
        _WKHTMLTOPDF_BIN,
        "--quiet",
        "--page-size",    opts.page_size,
        "--orientation",  opts.orientation,
        "--margin-top",   opts.margin_top,
        "--margin-bottom", opts.margin_bottom,
        "--margin-left",  opts.margin_left,
        "--margin-right", opts.margin_right,
        "--encoding",     opts.encoding,
        "--image-quality", str(opts.image_quality),
        "--enable-local-file-access",
    ]
    if opts.print_media:
        cmd.append("--print-media-type")
    if opts.no_javascript:
        cmd.append("--disable-javascript")

    cmd.extend([str(html_path), str(output_path)])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise PdfConversionError(
            f"wkhtmltopdf exited with code {result.returncode}: {stderr}"
        )

    logger.info("wkhtmltopdf subprocess conversion complete: %s", output_path)


# Backend dispatch table

_CONVERTERS: Final[dict[str, Any]] = {
    BACKEND_WEASYPRINT:  _convert_weasyprint,
    BACKEND_PDFKIT:      _convert_pdfkit,
    BACKEND_WKHTMLTOPDF: _convert_wkhtmltopdf_subprocess,
}


# ============================================================================

# Public API

# ============================================================================


def get_available_backends() -> list[str]:
    """Return the names of all usable PDF conversion backends."""
    return [name for name in _BACKEND_PRIORITY if _BACKEND_AVAILABLE[name]]


def get_default_backend() -> Optional[str]:
    """Return the highest-priority available backend, or ``None``."""
    for name in _BACKEND_PRIORITY:
        if _BACKEND_AVAILABLE[name]:
            return name
    return None


def generate_pdf_from_html(
    html_path: str | Path,
    output_pdf_path: str | Path,
    *,
    backend: Optional[str] = None,
    page_size: str     = _DEFAULT_OPTIONS.page_size,
    orientation: str   = _DEFAULT_OPTIONS.orientation,
    margin_top: str    = _DEFAULT_OPTIONS.margin_top,
    margin_bottom: str = _DEFAULT_OPTIONS.margin_bottom,
    margin_left: str   = _DEFAULT_OPTIONS.margin_left,
    margin_right: str  = _DEFAULT_OPTIONS.margin_right,
    print_media: bool  = _DEFAULT_OPTIONS.print_media,
    no_javascript: bool = _DEFAULT_OPTIONS.no_javascript,
    image_quality: int = _DEFAULT_OPTIONS.image_quality,
    encoding: str      = _DEFAULT_OPTIONS.encoding,
) -> Optional[Path]:
    """
    Convert a self-contained HTML file to PDF.

    Parameters
    ----------
    html_path:
        Path to the source HTML file.
    output_pdf_path:
        Where to write the PDF.
    backend:
        Force a specific backend (``"weasyprint"``, ``"pdfkit"``, or
        ``"wkhtmltopdf"``).  ``None`` (default) auto-selects the
        highest-priority available backend.
    page_size:
        Paper size (e.g. ``"A4"``, ``"Letter"``).  Default: ``"A4"``.
    orientation:
        ``"Landscape"`` or ``"Portrait"``.  Default: ``"Landscape"``
        (optimised for wide-format telemetry plots).
    margin_top / margin_bottom / margin_left / margin_right:
        Page margins with units (e.g. ``"10mm"``).
    print_media:
        Apply ``@media print`` CSS rules.  Default: ``True``.
    no_javascript:
        Disable JavaScript during rendering.  Default: ``True``.
    image_quality:
        JPEG image quality (0–100).  Default: ``100`` (lossless for
        embedded PNGs).
    encoding:
        Character encoding.  Default: ``"UTF-8"``.

    Returns
    -------
    Path | None
        Absolute path to the generated PDF file, or ``None`` if no
        conversion backend is available (graceful degradation).

    Raises
    ------
    FileNotFoundError
        If *html_path* does not exist.
    PdfConversionError
        If the conversion fails.
    """
    html_path      = Path(html_path)
    output_pdf_path = Path(output_pdf_path)

    # --- Validate input -- -

    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found: {html_path}")
    if not html_path.is_file():
        raise FileNotFoundError(f"Path is not a file: {html_path}")

    # --- Resolve backend
    if backend is not None:
        if backend not in _CONVERTERS:
            raise ValueError(
                f"Unknown backend {backend!r}.  "
                f"Available: {list(_CONVERTERS.keys())}"
            )
        if not _BACKEND_AVAILABLE.get(backend, False):
            logger.warning(
                "Requested PDF backend %r is not installed.  "
                "Skipping PDF generation.  Installed backends: %s",
                backend, get_available_backends() or "(none)",
            )
            return None
        chosen = backend
    else:
        chosen = get_default_backend()
        if chosen is None:
            logger.warning(
                "PDF generation skipped — no backend available.  "
                "Install one of: weasyprint (pip), "
                "pdfkit (pip) + wkhtmltopdf (system), "
                "or wkhtmltopdf (system)."
            )
            return None

    # --- Build options
    opts = PdfOptions(
        page_size=page_size,
        orientation=orientation,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        margin_left=margin_left,
        margin_right=margin_right,
        print_media=print_media,
        no_javascript=no_javascript,
        image_quality=image_quality,
        encoding=encoding,
    )

    # --- Create output directory if needed
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Convert
    logger.info(
        "Converting %s → %s  (backend=%s, page=%s %s)",
        html_path.name, output_pdf_path.name, chosen,
        opts.page_size, opts.orientation,
    )

    converter = _CONVERTERS[chosen]
    converter(html_path, output_pdf_path, opts)

    # --- Validate output
    if not output_pdf_path.exists():
        raise PdfConversionError(
            f"Backend {chosen!r} returned successfully but output file "
            f"was not created: {output_pdf_path}"
        )

    file_kb = output_pdf_path.stat().st_size / 1024
    if file_kb < 1:
        raise PdfConversionError(
            f"Output PDF is suspiciously small ({file_kb:.1f} KB).  "
            f"Conversion may have failed silently."
        )

    logger.info(
        "PDF generated: %s (%.0f KB, backend=%s)",
        output_pdf_path, file_kb, chosen,
    )
    return output_pdf_path.resolve()


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite — run with ``python reporting_pdf.py``."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Helper: create a minimal self-contained HTML file -- -


    def _make_html(tmpdir: str, *, with_image: bool = False) -> Path:
        """Create a minimal HTML file that mimics reporting_html.py output."""
        import base64
        import struct
        import zlib

        img_tag = ""
        if with_image:
            # 2×2 blue PNG

            raw = b"\x00\x00\x00\xff\x00\x00\xff" + b"\x00\x00\x00\xff\x00\x00\xff"
            compressed = zlib.compress(raw)
            def chunk(ctype: bytes, data: bytes) -> bytes:
                c = ctype + data
                crc = zlib.crc32(c) & 0xFFFFFFFF
                return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

            png = (
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", compressed)
                + chunk(b"IEND", b"")
            )
            b64 = base64.b64encode(png).decode()
            img_tag = f'<img src="data:image/png;base64,{b64}" width="100" height="100">'

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Test Report</title>
<style>
  body {{ background: #0f1117; color: #e0e0e0;
         font-family: sans-serif; padding: 24px; }}
  h1 {{ color: #00d4ff; }}
  .card {{ background: #181b24; border-radius: 10px;
           padding: 20px; margin: 16px 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 8px; border: 1px solid #333;
            text-align: left; }}
  th {{ background: #1d2028; color: #00d4ff; }}
</style></head>
<body>
<h1>Session Report — Spa 2024</h1>
<p style="color:#9a9a9a;">Track: Spa · Condition: Dry · Driver: Alice</p>
<div class="card">
  <h2>Session Score</h2>
  <p style="font-size:2rem; font-weight:700;">78.5 <span style="color:#9a9a9a;">/ 100</span></p>
  <p>Grade: <b style="color:#ffd600;">B</b></p>
</div>
{img_tag}
<div class="card">
  <h2>Driver Comparison</h2>
  <table>
    <tr><th>Driver</th><th>Pace Δ</th><th>Consistency</th><th>Score</th></tr>
    <tr><td>Alice</td><td>+1.200</td><td>0.84</td><td>78.5</td></tr>
    <tr><td>Bob</td><td>+2.100</td><td>0.71</td><td>65.2</td></tr>
    <tr><td>Charlie</td><td>+0.800</td><td>0.91</td><td>85.7</td></tr>
  </table>
</div>
<p style="text-align:center;color:#666;font-size:0.7rem;margin-top:32px;">
  Generated by reporting_pdf.py test suite
</p>
</body></html>"""

        path = Path(tmpdir) / "test_report.html"
        path.write_text(html, encoding="utf-8")
        return path

    # ==================================================================

    # Test 1 — available backends detection

    # ==================================================================

    def t_available_backends() -> None:
        backends = get_available_backends()
        assert isinstance(backends, list)
        # At least one must be available for tests to be meaningful

        assert len(backends) >= 1, f"No backends available: {backends}"
        for b in backends:
            assert b in _BACKEND_PRIORITY

    _test("available_backends", t_available_backends)

    # ==================================================================

    # Test 2 — default backend selection

    # ==================================================================

    def t_default_backend() -> None:
        default = get_default_backend()
        assert default is not None, "No default backend available"
        assert default in _BACKEND_PRIORITY
        assert _BACKEND_AVAILABLE[default]

    _test("default_backend", t_default_backend)

    # ==================================================================

    # Test 3 — basic conversion produces a valid PDF

    # ==================================================================

    def t_basic_conversion() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "output.pdf"
            result = generate_pdf_from_html(html, pdf)

            assert result.exists()
            assert pdf.stat().st_size > 1024  # at least 1 KB
            # Check PDF magic bytes

            with open(pdf, "rb") as f:
                magic = f.read(5)
            assert magic == b"%PDF-", f"Not a valid PDF: {magic!r}"

    _test("basic_conversion", t_basic_conversion)

    # ==================================================================

    # Test 4 — conversion with embedded image

    # ==================================================================

    def t_embedded_image() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir, with_image=True)
            pdf  = Path(tmpdir) / "with_image.pdf"
            result = generate_pdf_from_html(html, pdf)
            assert result.exists()
            assert pdf.stat().st_size > 1024

    _test("embedded_image", t_embedded_image)

    # ==================================================================

    # Test 5 — portrait orientation

    # ==================================================================

    def t_portrait() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "portrait.pdf"
            generate_pdf_from_html(html, pdf, orientation="Portrait")
            assert pdf.exists()

    _test("portrait", t_portrait)

    # ==================================================================

    # Test 6 — letter page size

    # ==================================================================

    def t_letter_size() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "letter.pdf"
            generate_pdf_from_html(html, pdf, page_size="Letter")
            assert pdf.exists()

    _test("letter_size", t_letter_size)

    # ==================================================================

    # Test 7 — custom margins

    # ==================================================================

    def t_custom_margins() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "margins.pdf"
            generate_pdf_from_html(
                html, pdf,
                margin_top="20mm", margin_bottom="20mm",
                margin_left="15mm", margin_right="15mm",
            )
            assert pdf.exists()

    _test("custom_margins", t_custom_margins)

    # ==================================================================

    # Test 8 — missing HTML file raises FileNotFoundError

    # ==================================================================

    def t_missing_html() -> None:
        try:
            generate_pdf_from_html("/nonexistent/file.html", "/tmp/out.pdf")
            raise AssertionError("Expected FileNotFoundError")
        except FileNotFoundError:
            pass

    _test("missing_html", t_missing_html)

    # ==================================================================

    # Test 9 — invalid backend raises ValueError

    # ==================================================================

    def t_invalid_backend() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            try:
                generate_pdf_from_html(html, Path(tmpdir) / "x.pdf", backend="fake")
                raise AssertionError("Expected ValueError")
            except ValueError as exc:
                assert "Unknown backend" in str(exc)

    _test("invalid_backend", t_invalid_backend)

    # ==================================================================

    # Test 10 — output directory auto-creation

    # ==================================================================

    def t_auto_create_dirs() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            deep = Path(tmpdir) / "a" / "b" / "c" / "report.pdf"
            result = generate_pdf_from_html(html, deep)
            assert result.exists()

    _test("auto_create_dirs", t_auto_create_dirs)

    # ==================================================================

    # Test 11 — PdfOptions defaults

    # ==================================================================

    def t_pdf_options_defaults() -> None:
        opts = PdfOptions()
        assert opts.page_size == "A4"
        assert opts.orientation == "Landscape"
        assert opts.margin_top == "10mm"
        assert opts.print_media is True
        assert opts.no_javascript is True
        assert opts.image_quality == 100
        assert opts.encoding == "UTF-8"

    _test("pdf_options_defaults", t_pdf_options_defaults)

    # ==================================================================

    # Test 12 — PdfOptions custom values

    # ==================================================================

    def t_pdf_options_custom() -> None:
        opts = PdfOptions(
            page_size="Letter",
            orientation="Portrait",
            margin_top="25mm",
        )
        assert opts.page_size == "Letter"
        assert opts.orientation == "Portrait"
        assert opts.margin_top == "25mm"
        # Other fields retain defaults

        assert opts.margin_bottom == "10mm"

    _test("pdf_options_custom", t_pdf_options_custom)

    # ==================================================================

    # Test 13 — PdfOptions is immutable (frozen dataclass)

    # ==================================================================

    def t_pdf_options_frozen() -> None:
        opts = PdfOptions()
        try:
            opts.page_size = "B5"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass

    _test("pdf_options_frozen", t_pdf_options_frozen)

    # ==================================================================

    # Test 14 — return path is absolute

    # ==================================================================

    def t_return_absolute() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "abs_test.pdf"
            result = generate_pdf_from_html(html, pdf)
            assert result.is_absolute()

    _test("return_absolute", t_return_absolute)

    # ==================================================================

    # Test 15 — explicit pdfkit backend (if available)

    # ==================================================================

    def t_explicit_pdfkit() -> None:
        if not _HAS_PDFKIT:
            return  # skip
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "pdfkit.pdf"
            generate_pdf_from_html(html, pdf, backend=BACKEND_PDFKIT)
            assert pdf.exists()
            assert pdf.stat().st_size > 1024

    _test("explicit_pdfkit", t_explicit_pdfkit)

    # ==================================================================

    # Test 16 — explicit wkhtmltopdf subprocess backend (if available)

    # ==================================================================

    def t_explicit_wkhtmltopdf() -> None:
        if not _HAS_WKHTMLTOPDF:
            return  # skip
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            pdf  = Path(tmpdir) / "wkhtml.pdf"
            generate_pdf_from_html(html, pdf, backend=BACKEND_WKHTMLTOPDF)
            assert pdf.exists()
            assert pdf.stat().st_size > 1024

    _test("explicit_wkhtmltopdf", t_explicit_wkhtmltopdf)

    # ==================================================================

    # Test 17 — unavailable backend returns None (graceful degradation)

    # ==================================================================

    def t_unavailable_backend() -> None:
        # Find a backend that is NOT available

        unavailable = [
            b for b in _BACKEND_PRIORITY
            if not _BACKEND_AVAILABLE[b]
        ]
        if not unavailable:
            return  # all backends available, skip
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir)
            result = generate_pdf_from_html(
                html, Path(tmpdir) / "x.pdf",
                backend=unavailable[0],
            )
            assert result is None, (
                f"Expected None for unavailable backend {unavailable[0]!r}, "
                f"got {result!r}"
            )

    _test("unavailable_backend", t_unavailable_backend)

    # ==================================================================

    # Test 18 — conversion with actual reporting_html output

    # ==================================================================

    def t_real_report() -> None:
        real_html = Path("/mnt/user-data/outputs/index.html")
        if not real_html.exists():
            return  # skip if not present
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = Path(tmpdir) / "real_report.pdf"
            result = generate_pdf_from_html(real_html, pdf)
            assert result.exists()
            size_kb = pdf.stat().st_size / 1024
            assert size_kb > 50, f"Real report PDF too small: {size_kb:.0f} KB"

    _test("real_report", t_real_report)

    # ==================================================================

    # Test 19 — PDF magic bytes validation

    # ==================================================================

    def t_pdf_magic_bytes() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html = _make_html(tmpdir, with_image=True)
            pdf  = Path(tmpdir) / "magic.pdf"
            generate_pdf_from_html(html, pdf)

            with open(pdf, "rb") as f:
                header = f.read(8)
            assert header[:5] == b"%PDF-"
            # Version should be 1.x or 2.x

            assert header[5:6] in (b"1", b"2"), f"Unexpected PDF version: {header!r}"

    _test("pdf_magic_bytes", t_pdf_magic_bytes)

    # ==================================================================

    # Test 20 — large HTML conversion (stress test)

    # ==================================================================

    def t_large_html() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate a large HTML file (~100 KB of content)

            rows = "".join(
                f"<tr><td>Lap {i}</td><td>{90+i*0.1:.1f}</td>"
                f"<td>+{i*0.05:.2f}</td><td>{80+i*0.2:.1f}</td></tr>"
                for i in range(500)
            )
            html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Large</title>
<style>body{{background:#111;color:#eee;font-family:sans-serif}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:6px;border:1px solid #333;text-align:left}}
th{{background:#1d2028;color:#00d4ff}}</style></head>
<body><h1>Large Report</h1>
<table><tr><th>Lap</th><th>Time</th><th>Delta</th><th>Score</th></tr>
{rows}</table></body></html>"""

            path = Path(tmpdir) / "large.html"
            path.write_text(html_content, encoding="utf-8")

            pdf = Path(tmpdir) / "large.pdf"
            generate_pdf_from_html(path, pdf)
            assert pdf.exists()
            assert pdf.stat().st_size > 5000

    _test("large_html", t_large_html)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nReporting PDF Tests: {len(passed)}/{total} passed [{status}]")
    print(f"  Backends detected: {get_available_backends()}")
    print(f"  Default backend:   {get_default_backend()}")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# ============================================================================

# Entry point

# ============================================================================


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()