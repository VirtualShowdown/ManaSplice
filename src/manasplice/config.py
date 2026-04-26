from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def load_project_config(cwd: Path) -> dict:
    """Load [tool.manasplice] from the nearest pyproject.toml above cwd, or return {}."""
    pyproject = _find_pyproject(cwd.resolve())
    if pyproject is None:
        return {}
    try:
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return {}
    return data.get("tool", {}).get("manasplice", {})


def resolve_project_config_path(cwd: Path) -> Path:
    """Return the pyproject.toml path owned by the requested project root."""
    return cwd.resolve() / "pyproject.toml"


def update_project_config(cwd: Path, updates: dict[str, Any]) -> Path:
    pyproject = resolve_project_config_path(cwd)
    text = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    updated_text = _update_manasplice_section(text, updates)
    pyproject.write_text(updated_text, encoding="utf-8")
    return pyproject


def _update_manasplice_section(text: str, updates: dict[str, Any]) -> str:
    lines = text.splitlines()
    section_start = _find_section_start(lines, "[tool.manasplice]")
    rendered_updates = [f"{key} = {_render_toml_value(value)}" for key, value in updates.items()]
    if section_start is None:
        prefix = text.rstrip()
        block = "\n".join(["[tool.manasplice]", *rendered_updates])
        return (prefix + "\n\n" + block + "\n") if prefix else block + "\n"

    section_end = _find_section_end(lines, section_start)
    existing = lines[section_start + 1 : section_end]
    update_keys = set(updates)
    merged: list[str] = []
    seen: set[str] = set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in update_keys:
            merged.append(f"{key} = {_render_toml_value(updates[key])}")
            seen.add(key)
        else:
            merged.append(line)
    for key, value in updates.items():
        if key not in seen:
            merged.append(f"{key} = {_render_toml_value(value)}")
    output = [*lines[: section_start + 1], *merged, *lines[section_end:]]
    return "\n".join(output).rstrip() + "\n"


def _find_section_start(lines: list[str], section_name: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == section_name:
            return index
    return None


def _find_section_end(lines: list[str], section_start: int) -> int:
    for index in range(section_start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def _render_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json_escape(value)
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    return str(value)


def json_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _find_pyproject(start: Path) -> Path | None:
    current = start
    while True:
        candidate = current / "pyproject.toml"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent
