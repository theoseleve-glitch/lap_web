"""
CSS / JS bundle size budget assertions.

Prevents uncontrolled growth of front-end assets by enforcing size limits.
Budgets are set ~10% above current totals to allow modest growth while
catching accidental bloat (e.g. duplicated CSS, bundled node_modules).
"""
import pathlib

import pytest

STATIC_DIR = pathlib.Path(__file__).resolve().parents[2] / "web" / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"

# Budgets in bytes (current: CSS ~370KB, JS ~970KB)
CSS_BUDGET = 420_000   # 420 KB
JS_BUDGET = 1_100_000  # 1.1 MB

# Individual file caps — no single CSS/JS file should exceed these
CSS_FILE_CAP = 300_000   # 300 KB (main.css is ~269KB)
JS_FILE_CAP = 80_000     # 80 KB (analyze_form.js is ~73KB)


def _total_size(directory: pathlib.Path, ext: str) -> int:
    return sum(f.stat().st_size for f in directory.glob(f"*{ext}"))


def _largest_file(directory: pathlib.Path, ext: str) -> tuple[str, int]:
    files = [(f.name, f.stat().st_size) for f in directory.glob(f"*{ext}")]
    return max(files, key=lambda x: x[1]) if files else ("(none)", 0)


class TestCSSBudget:
    def test_css_total_under_budget(self):
        total = _total_size(CSS_DIR, ".css")
        assert total < CSS_BUDGET, (
            f"CSS total {total:,} bytes ({total / 1024:.0f} KB) "
            f"exceeds budget of {CSS_BUDGET:,} bytes ({CSS_BUDGET / 1024:.0f} KB)"
        )

    def test_no_single_css_file_too_large(self):
        name, size = _largest_file(CSS_DIR, ".css")
        assert size < CSS_FILE_CAP, (
            f"CSS file '{name}' is {size:,} bytes ({size / 1024:.0f} KB), "
            f"exceeds cap of {CSS_FILE_CAP:,} bytes ({CSS_FILE_CAP / 1024:.0f} KB)"
        )


class TestJSBudget:
    def test_js_total_under_budget(self):
        total = _total_size(JS_DIR, ".js")
        assert total < JS_BUDGET, (
            f"JS total {total:,} bytes ({total / 1024:.0f} KB) "
            f"exceeds budget of {JS_BUDGET:,} bytes ({JS_BUDGET / 1024:.0f} KB)"
        )

    def test_no_single_js_file_too_large(self):
        name, size = _largest_file(JS_DIR, ".js")
        assert size < JS_FILE_CAP, (
            f"JS file '{name}' is {size:,} bytes ({size / 1024:.0f} KB), "
            f"exceeds cap of {JS_FILE_CAP:,} bytes ({JS_FILE_CAP / 1024:.0f} KB)"
        )


class TestAssetInventory:
    """Sanity checks that expected core assets exist."""

    @pytest.mark.parametrize("css_file", [
        "tokens.css", "main.css", "charts.css", "utilities.css", "motion.css",
    ])
    def test_core_css_exists(self, css_file):
        assert (CSS_DIR / css_file).is_file(), f"Missing core CSS: {css_file}"

    @pytest.mark.parametrize("js_file", [
        "theme.js", "toast.js", "fetch_helper.js", "chart_frame.js",
        "module_manager.js", "modal.js",
    ])
    def test_core_js_exists(self, js_file):
        assert (JS_DIR / js_file).is_file(), f"Missing core JS: {js_file}"
