"""A SKILL.md's frontmatter, for ``ctx.register_skill``: Hermes lists a plugin skill in the
system prompt with the description it is given, and reads none from the file itself."""

from __future__ import annotations

import re
from pathlib import Path


def frontmatter(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not m:
        return {}
    try:
        import yaml  # Hermes depends on PyYAML
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"([A-Za-z_][\w-]*):\s*(.*)$", line)
        if kv:
            out[kv.group(1)] = kv.group(2).strip().strip("'\"")
    return out
