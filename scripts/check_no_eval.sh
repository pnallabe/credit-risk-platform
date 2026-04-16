#!/usr/bin/env bash
# scripts/check_no_eval.sh
# ---------------------------------------------------------------------------
# Fail if eval() appears as an actual Python AST Call node in any production
# policy/agent/engine path.  Comments, docstrings, and string literals that
# merely *mention* eval are not flagged.
# Add "# noqa: eval-allowed" to a line to suppress it (checked via grep).
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

python3 - <<'PYEOF'
import ast
import sys
from pathlib import Path

SEARCH_DIRS = [
    "agents", "decision_engine", "credit_core", "feature_pipeline", "orchestration"
]
NOQA_MARKER = "# noqa: eval-allowed"

root = Path(".")
violations = []

for search_dir in SEARCH_DIRS:
    for py_file in (root / search_dir).rglob("*.py"):
        # Skip test files
        if "tests" in py_file.parts:
            continue
        source = py_file.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "eval"
            ):
                lineno = node.lineno
                line_text = lines[lineno - 1] if lineno <= len(lines) else ""
                if NOQA_MARKER in line_text:
                    continue
                violations.append(f"{py_file}:{lineno}: {line_text.strip()}")

if violations:
    print("ERROR: eval() call found in production policy paths:")
    for v in violations:
        print(v)
    sys.exit(1)

print("eval() check passed.")
PYEOF
