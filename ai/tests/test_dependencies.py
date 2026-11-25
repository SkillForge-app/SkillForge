"""Every third-party package that core/ imports is declared in pyproject.toml, so an upgrade of
another package can't silently remove it (it would otherwise only arrive transitively)."""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[1]


def _name(requirement: str) -> str:
    """The normalised distribution name of a requirement string (PEP 503)."""
    name = re.split(r"[\s<>=!~;\[@(]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    project = tomllib.loads((AI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        requirements += extra
    return {_name(r) for r in requirements}


def _imported() -> dict[str, set[str]]:
    """Top-level module -> the core/ files that import it (absolute imports only)."""
    found: dict[str, set[str]] = {}
    for path in sorted((AI_ROOT / "core").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top != "core" and top not in sys.stdlib_module_names:
                    found.setdefault(top, set()).add(path.relative_to(AI_ROOT).as_posix())
    return found


def test_core_imports_only_declared_packages() -> None:
    declared = _declared()
    owners = packages_distributions()
    missing = {
        module: sorted(files)
        for module, files in _imported().items()
        if not {_name(d) for d in owners.get(module, [])} & declared
    }
    assert not missing, f"imported by core/ but not in pyproject.toml dependencies: {missing}"
