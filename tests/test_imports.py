"""No module imports a name it never uses (the repo's lint has no pyflakes)."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted([*ROOT.glob("annotary_hermes/*.py"), *ROOT.glob("scripts/project/*.py")])


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_top_level_import_is_used(path):
    tree = ast.parse(path.read_text())
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update({(a.asname or a.name).split(".")[0]: node.lineno for a in node.names})
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imported.update({a.asname or a.name: node.lineno for a in node.names})
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            exported = set(ast.literal_eval(node.value))
    assert sorted(set(imported) - used - exported) == []
