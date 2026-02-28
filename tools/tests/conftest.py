"""Conftest for tools tests — adds tools dir and project root to sys.path."""
import sys
from pathlib import Path

# Project root: V2_claude_ai/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Tools dir: V2_claude_ai/tools/
TOOLS_DIR = Path(__file__).resolve().parent.parent

for p in (str(PROJECT_ROOT), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
