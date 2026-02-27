"""Static checks to enforce Flask auth context naming conventions."""
from pathlib import Path


def test_web_code_forbids_g_user_id_usage():
    root = Path(__file__).resolve().parent.parent / "web"
    violations = []

    for path in root.rglob("*.py"):
        rel = path.relative_to(root.parent)
        if rel.as_posix() == "web/middleware/auth.py":
            # Transitional alias kept intentionally during migration.
            continue

        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if 'getattr(g, "user_id"' in line or "g.user_id" in line:
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, "Forbidden g.user_id usage found:\n" + "\n".join(violations)
