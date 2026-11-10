"""Lint the desktop page the way Hermes's catalog does, without Hermes: plain ESM that imports only
the three specifiers Hermes resolves, no script-tag text (the validator refuses it), and syntax
checked by Node."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}
PAGE = Path(__file__).resolve().parents[2] / "desktop" / "plugin.js"


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    problems = []
    for spec in re.findall(r"""^\s*import\s[^'"]*['"]([^'"]+)['"]""", text, re.M):
        if spec not in ALLOWED:
            problems.append(f"imports {spec!r}; only {sorted(ALLOWED)} resolve")
    if re.search(r"<\s*script", text, re.I):
        problems.append("contains script-tag text (Hermes's validator refuses it)")
    if re.search(r"\bimport\s*\(", text):
        problems.append("uses a dynamic import()")
    node = shutil.which("node")
    if not node:
        problems.append("node is not installed: the syntax check cannot run")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "plugin.mjs"
            copy.write_text(text, encoding="utf-8")
            r = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("node --check: " + r.stderr.strip()[-500:])
    for p in problems:
        print(f"desktop/plugin.js: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
