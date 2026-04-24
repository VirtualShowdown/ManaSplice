from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exceptions import TargetResolutionError


@dataclass(slots=True)
class TargetSpec:
    module_path: str
    function_name: str


@dataclass(slots=True)
class ResolvedTarget:
    spec: TargetSpec
    module_file: Path
    package_mode: bool


def parse_target(target: str) -> TargetSpec:
    if "." not in target:
        raise TargetResolutionError("Target must look like 'module.function' or 'package.module.function'.")

    *module_parts, function_name = target.split(".")
    if not module_parts or not function_name:
        raise TargetResolutionError("Target must include both a module path and a function name.")

    return TargetSpec(module_path=".".join(module_parts), function_name=function_name)


def resolve_target(spec: TargetSpec, cwd: Path | None = None) -> ResolvedTarget:
    base = (cwd or Path.cwd()).resolve()
    module_parts = spec.module_path.split(".")

    candidate_py = base.joinpath(*module_parts).with_suffix(".py")
    candidate_pkg = base.joinpath(*module_parts, "__init__.py")

    if candidate_py.exists():
        package_mode = _is_package_context(candidate_py)
        return ResolvedTarget(spec=spec, module_file=candidate_py, package_mode=package_mode)

    if candidate_pkg.exists():
        package_mode = True
        return ResolvedTarget(spec=spec, module_file=candidate_pkg, package_mode=package_mode)

    raise TargetResolutionError(
        f"Could not find module '{spec.module_path}' from '{base}'. Expected '{candidate_py}' or '{candidate_pkg}'."
    )


def _is_package_context(module_file: Path) -> bool:
    return (module_file.parent / "__init__.py").exists()
