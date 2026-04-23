from __future__ import annotations

from pathlib import Path


def path_to_module_parts(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return [part for part in parts if part]


def detect_project_root(module_file: Path) -> Path:
    current = module_file.parent.resolve()
    while True:
        if (current / "pyproject.toml").exists() or (current / ".git").exists():
            return current
        if current.parent == current:
            return module_file.parent.resolve()
        current = current.parent