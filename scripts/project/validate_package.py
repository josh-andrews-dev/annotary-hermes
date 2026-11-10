"""Run `hermes plugins validate --install-deps` on the package as installed: the agent half, the
backend and the desktop half (desktop/plugin.js, which the validator's desktop-surface check reads).

Needs Hermes on the PATH; without it, says so and exits 0 (CI has no Hermes)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ["plugin.yaml", "__init__.py", "annotary_hermes", "dashboard", "desktop", "skills",
           "README.md", "LICENSE-MIT", "LICENSE-APACHE"]


def copy_package(dest: Path) -> None:
    for name in PACKAGE:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.exists():
            shutil.copy2(src, dest / name)


def validate(path: Path, label: str) -> int:
    r = subprocess.run(["hermes", "plugins", "validate", "--install-deps", str(path)], capture_output=True, text=True)
    print(f"== {label}\n{r.stdout}{r.stderr}")
    return r.returncode


def main() -> int:
    if not shutil.which("hermes"):
        print("validate: hermes is not installed here; skipped (run it where Hermes is)")
        return 0
    rc = 0
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "annotary"
        pkg.mkdir()
        copy_package(pkg)
        rc |= validate(pkg, "package")
    return rc


if __name__ == "__main__":
    sys.exit(main())
