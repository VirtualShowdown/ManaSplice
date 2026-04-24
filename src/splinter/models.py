from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileChange:
    path: Path
    existed_before: bool
    before_text: str
    after_text: str


@dataclass(slots=True)
class SplitOptions:
    preview: bool = False
    output_package: str = "modules"
    validate: bool = False
    force: bool = False


@dataclass(slots=True)
class SplitResult:
    module_file: Path
    new_module_file: Path
    function_name: str
    import_statement: str
    module_text: str
    new_module_text: str
    init_file: Path
    init_text: str
    preview: bool
    file_changes: list[FileChange]
    output_package: str
    preview_diffs: list[str]


@dataclass(slots=True)
class GroupSplitResult:
    module_file: Path
    new_module_file: Path
    function_names: list[str]
    import_statement: str
    module_text: str
    new_module_text: str
    init_file: Path
    init_text: str
    preview: bool
    file_changes: list[FileChange]
    output_package: str
    preview_diffs: list[str]


@dataclass(slots=True)
class FunctionNodeInfo:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    start_lineno: int
    end_lineno: int


@dataclass(slots=True)
class ModuleAnalysis:
    tree: ast.Module
    imports: list[ast.stmt]
    import_bindings: dict[str, ast.stmt]
    definitions: dict[str, ast.stmt]
    target: FunctionNodeInfo
    source_text: str


@dataclass(slots=True)
class MultiModuleAnalysis:
    tree: ast.Module
    imports: list[ast.stmt]
    import_bindings: dict[str, ast.stmt]
    definitions: dict[str, ast.stmt]
    targets: list[FunctionNodeInfo]
    source_text: str
