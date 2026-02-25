"""Helper script to run pytest and write output to a known file."""
import subprocess
import sys

result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        "tests/test_corner_picker_changes.py",
        "-v", "--tb=short",
    ],
    capture_output=True,
    text=True,
    cwd=r"C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\telemetry_tool",
)

output_path = r"C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\telemetry_tool\test_output.txt"
with open(output_path, "w", encoding="utf-8") as f:
    f.write("=== STDOUT ===\n")
    f.write(result.stdout)
    f.write("\n=== STDERR ===\n")
    f.write(result.stderr)
    f.write(f"\n=== RETURN CODE: {result.returncode} ===\n")
