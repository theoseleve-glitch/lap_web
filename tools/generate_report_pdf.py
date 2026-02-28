"""Generate PDF report from audit/report.md.

Uses markdown + weasyprint. Falls back to HTML if weasyprint unavailable.

Usage:
    python tools/generate_report_pdf.py
    python tools/generate_report_pdf.py --input audit/report.md --output audit/report.pdf
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def md_to_html(md_content: str) -> str:
    """Convert markdown to styled HTML."""
    try:
        import markdown
        html_body = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "toc"],
        )
    except ImportError:
        html_body = f"<pre>{md_content}</pre>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>E2E Certification Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #222; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 10px; }}
  h2 {{ color: #16213e; margin-top: 30px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background-color: #16213e; color: white; }}
  tr:nth-child(even) {{ background-color: #f8f9fa; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #1a1a2e; color: #e0e0e0; padding: 15px; border-radius: 5px; overflow-x: auto; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
{html_body}
<div class="footer">
  <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Branch: recovery/e2e-certification</p>
</div>
</body>
</html>"""


def generate_pdf(input_path: str, output_path: str) -> bool:
    """Convert markdown to PDF. Returns True on success."""
    with open(input_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html = md_to_html(md_content)

    # Try weasyprint
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(output_path)
        logger.info("PDF generated: %s", output_path)
        return True
    except ImportError:
        logger.warning("weasyprint not installed, writing HTML fallback")
    except Exception as e:
        logger.warning("weasyprint failed: %s", e)

    # Fallback: write HTML
    html_path = output_path.replace(".pdf", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report: %s", html_path)
    return False


def main():
    parser = argparse.ArgumentParser(description="Generate PDF from audit report")
    parser.add_argument("--input", default=str(ROOT / "audit" / "report.md"))
    parser.add_argument("--output", default=str(ROOT / "audit" / "report.pdf"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    generate_pdf(args.input, args.output)


if __name__ == "__main__":
    main()
