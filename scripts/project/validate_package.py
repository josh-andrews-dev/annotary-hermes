"""Run `hermes plugins validate --install-deps` on the package, twice:

1. the package as installed (agent half and backend; its page lives in desktop-page/, which
   Hermes does not load as a package half on purpose);
2. a copy with the page at desktop/plugin.js, so the validator's desktop-surface check reads it.

Needs Hermes on the PATH; without it, says so and exits 0 (CI has no Hermes)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ["plugin.yaml", "__init__.py", "annotary_hermes", "dashboard", "desktop-page", "skills",
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
        (pkg / "desktop").mkdir()
        shutil.copy2(pkg / "desktop-page" / "plugin.js", pkg / "desktop" / "plugin.js")
        rc |= validate(pkg, "package with the page as desktop/plugin.js (desktop-surface lint)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
