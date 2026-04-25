from __future__ import annotations

import ast
from pathlib import Path

from .exceptions import FunctionExtractionError
from .models import FunctionNodeInfo, ModuleAnalysis, MultiModuleAnalysis


def analyze_module(source_text: str, function_name: str, module_file: Path) -> ModuleAnalysis:
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise FunctionExtractionError(f"Could not parse '{module_file}': {exc}") from exc

    imports: list[ast.stmt] = []
    import_bindings: dict[str, ast.stmt] = {}
    definitions: dict[str, ast.stmt] = {}
    target_info: FunctionNodeInfo | None = None

    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            imports.append(stmt)
            for name in iter_imported_names(stmt):
                import_bindings.setdefault(name, stmt)
            continue

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_overload_stub(stmt):
                definitions.setdefault(stmt.name, stmt)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for name in iter_assigned_names(stmt):
                definitions.setdefault(name, stmt)

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == function_name:
            if _is_overload_stub(stmt):
                continue
            if target_info is not None:
                raise FunctionExtractionError(
                    f"Found duplicate top-level definitions for function '{function_name}' in '{module_file}'."
                )
            if stmt.end_lineno is None:
                raise FunctionExtractionError(f"Could not determine end line for function '{function_name}'.")
            target_info = FunctionNodeInfo(
                node=stmt,
                start_lineno=statement_start_lineno(stmt),
                end_lineno=stmt.end_lineno,
            )

    if target_info is None:
        raise FunctionExtractionError(
            f"Function '{function_name}' was not found as a top-level definition in '{module_file}'."
        )

    return ModuleAnalysis(
        tree=tree,
        imports=imports,
        import_bindings=import_bindings,
        definitions=definitions,
        target=target_info,
        source_text=source_text,
    )


def analyze_module_for_group(source_text: str, function_names: list[str], module_file: Path) -> MultiModuleAnalysis:
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise FunctionExtractionError(f"Could not parse '{module_file}': {exc}") from exc

    func_set = set(function_names)
    imports: list[ast.stmt] = []
    import_bindings: dict[str, ast.stmt] = {}
    definitions: dict[str, ast.stmt] = {}
    found: dict[str, FunctionNodeInfo] = {}

    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            imports.append(stmt)
            for name in iter_imported_names(stmt):
                import_bindings.setdefault(name, stmt)
            continue

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_overload_stub(stmt):
                definitions.setdefault(stmt.name, stmt)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for name in iter_assigned_names(stmt):
                definitions.setdefault(name, stmt)

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in func_set:
            if _is_overload_stub(stmt):
                continue
            if stmt.name in found:
                raise FunctionExtractionError(
                    f"Found duplicate top-level definitions for '{stmt.name}' in '{module_file}'."
                )
            if stmt.end_lineno is None:
                raise FunctionExtractionError(f"Could not determine end line for '{stmt.name}'.")
            found[stmt.name] = FunctionNodeInfo(
                node=stmt,
                start_lineno=statement_start_lineno(stmt),
                end_lineno=stmt.end_lineno,
            )

    missing = func_set - set(found)
    if missing:
        names_str = ", ".join(sorted(missing))
        raise FunctionExtractionError(
            f"Function(s) {names_str!r} not found as top-level definitions in '{module_file}'."
        )

    return MultiModuleAnalysis(
        tree=tree,
        imports=imports,
        import_bindings=import_bindings,
        definitions=definitions,
        targets=sorted(found.values(), key=lambda target: target.start_lineno),
        source_text=source_text,
    )


def iter_imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    names: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        if alias.asname:
            names.append(alias.asname)
        elif isinstance(node, ast.Import):
            names.append(alias.name.split(".", 1)[0])
        else:
            names.append(alias.name)
    return names


def iter_assigned_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    targets: list[ast.AST] = []

    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]

    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.append(child.id)

    return names


def statement_start_lineno(node: ast.stmt) -> int:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
        return min(decorator.lineno for decorator in node.decorator_list)
    return node.lineno


def _is_overload_stub(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(_decorator_name(decorator) == "overload" for decorator in node.decorator_list)


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""
