from __future__ import annotations

import ast
from collections import deque
from collections.abc import Sequence
from pathlib import Path

from .analysis import iter_assigned_names, statement_start_lineno
from .exceptions import FunctionExtractionError


def build_function_call_groups(
    source_text: str,
    function_names: list[str],
    module_file: Path,
) -> list[list[str]]:
    if not function_names:
        return []

    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise FunctionExtractionError(f"Could not parse '{module_file}': {exc}") from exc

    func_set = set(function_names)
    source_order: list[str] = []
    nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in func_set:
            if stmt.name not in nodes:
                nodes[stmt.name] = stmt
                source_order.append(stmt.name)

    adj: dict[str, set[str]] = {name: set() for name in source_order}
    for name, node in nodes.items():
        for ref in find_module_level_references(node):
            if ref in func_set and ref != name:
                adj[name].add(ref)
                adj[ref].add(name)

    visited: set[str] = set()
    components: list[list[str]] = []
    for start in source_order:
        if start in visited:
            continue
        component: list[str] = []
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in sorted(adj.get(current, set())):
                if neighbor not in visited:
                    queue.append(neighbor)
        component_set = set(component)
        components.append([name for name in source_order if name in component_set])

    return components


def collect_dependency_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    definitions: dict[str, ast.stmt],
) -> set[str]:
    pending = [name for name in find_module_level_references(node) if name in definitions]
    collected: set[str] = set()

    while pending:
        name = pending.pop()
        if name in collected:
            continue

        collected.add(name)
        stmt = definitions[name]
        for dependency in find_module_level_references(stmt):
            if dependency in definitions and dependency not in collected:
                pending.append(dependency)

    return collected


def collect_required_import_names(
    nodes: Sequence[ast.AST],
    dependency_nodes: Sequence[ast.AST],
    import_names: set[str],
) -> set[str]:
    required: set[str] = set()
    for node in [*nodes, *dependency_nodes]:
        required.update(find_module_level_references(node) & import_names)
    return required


def detect_local_dependency_cycle(
    function_name: str,
    dependency_names: set[str],
    definitions: dict[str, ast.stmt],
    module_file: Path,
) -> None:
    for dependency_name in sorted(dependency_names):
        path = _find_dependency_path_to_target(dependency_name, function_name, definitions)
        if path is None:
            continue

        cycle_path = " -> ".join([function_name, *path])
        raise FunctionExtractionError(
            f"Cannot split '{function_name}' from '{module_file}' because it participates "
            f"in a local dependency cycle: {cycle_path}."
        )


def detect_mutable_global_dependencies(
    dependency_names: set[str],
    definitions: dict[str, ast.stmt],
    module_file: Path,
) -> None:
    mutable_names = sorted(name for name in dependency_names if _is_mutable_global_assignment(definitions.get(name)))
    if mutable_names:
        names = ", ".join(mutable_names)
        raise FunctionExtractionError(
            f"Cannot safely split from '{module_file}' because the function depends on mutable "
            f"module global(s): {names}. Split related functions together or move the shared state "
            "behind an explicit API first."
        )


def find_module_level_references(node: ast.AST) -> set[str]:
    collector = _ModuleLevelReferenceCollector()
    collector.visit(node)
    return collector.references


def render_dependency_blocks(
    definitions: dict[str, ast.stmt],
    source_text: str,
    dependency_names: set[str],
) -> str:
    lines = source_text.splitlines(keepends=True)
    blocks: list[tuple[int, str]] = []
    seen_nodes: set[int] = set()

    for name in dependency_names:
        stmt = definitions.get(name)
        if stmt is None or stmt.end_lineno is None:
            continue
        stmt_id = id(stmt)
        if stmt_id in seen_nodes:
            continue
        seen_nodes.add(stmt_id)
        start = statement_start_lineno(stmt)
        blocks.append((start, "".join(lines[start - 1 : stmt.end_lineno]).rstrip()))

    if not blocks:
        return ""

    blocks.sort(key=lambda item: item[0])
    return "\n\n".join(block for _, block in blocks) + "\n\n"


def _find_dependency_path_to_target(
    start_name: str,
    target_name: str,
    definitions: dict[str, ast.stmt],
) -> list[str] | None:
    stack: list[tuple[str, list[str]]] = [(start_name, [start_name])]
    visited: set[str] = set()

    while stack:
        current_name, path = stack.pop()
        if current_name in visited:
            continue
        visited.add(current_name)

        stmt = definitions.get(current_name)
        if stmt is None:
            continue

        for dependency in sorted(find_module_level_references(stmt)):
            if dependency == target_name:
                return path + [target_name]
            if dependency in definitions and dependency not in visited:
                stack.append((dependency, path + [dependency]))

    return None


def _is_mutable_global_assignment(stmt: ast.stmt | None) -> bool:
    if isinstance(stmt, ast.Assign):
        return _is_mutable_value(stmt.value)
    if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        return _is_mutable_value(stmt.value)
    return isinstance(stmt, ast.AugAssign)


def _is_mutable_value(value: ast.AST) -> bool:
    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name):
            return value.func.id in {"dict", "list", "set", "defaultdict", "Counter", "deque"}
        if isinstance(value.func, ast.Attribute):
            return value.func.attr in {"dict", "list", "set", "defaultdict", "Counter", "deque"}
    return False


def _collect_bound_names_in_function(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    bound: set[str] = set()

    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        bound.add(arg.arg)
    if args.vararg is not None:
        bound.add(args.vararg.arg)
    if args.kwarg is not None:
        bound.add(args.kwarg.arg)

    collector = _FunctionBoundNameCollector()
    if isinstance(node, ast.Lambda):
        collector.visit(node.body)
    else:
        for stmt in node.body:
            collector.visit(stmt)
    bound.update(collector.names)
    return bound


class _FunctionBoundNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


class _ModuleLevelReferenceCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.references: set[str] = set()
        self._scopes: list[set[str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_function_signature(node)
        self._visit_scoped_body(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_function_signature(node)
        self._visit_scoped_body(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function_signature(node)
        self._visit_scoped_expression(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)

        self._scopes.append({node.name})
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension([node.key, node.value], node.generators)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not self._is_bound(node.id):
            self.references.add(node.id)

    def _visit_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        args = node.args
        defaults = [*args.defaults, *args.kw_defaults]
        for default in defaults:
            if default is not None:
                self.visit(default)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                if arg.annotation is not None:
                    self.visit(arg.annotation)
            if args.vararg is not None and args.vararg.annotation is not None:
                self.visit(args.vararg.annotation)
            if args.kwarg is not None and args.kwarg.annotation is not None:
                self.visit(args.kwarg.annotation)
            if node.returns is not None:
                self.visit(node.returns)

    def _visit_scoped_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scopes.append(_collect_bound_names_in_function(node))
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    def _visit_scoped_expression(self, node: ast.Lambda) -> None:
        self._scopes.append(_collect_bound_names_in_function(node))
        self.visit(node.body)
        self._scopes.pop()

    def _visit_comprehension(self, result_nodes: ast.AST | list[ast.AST], generators: list[ast.comprehension]) -> None:
        bound: set[str] = set()
        for generator in generators:
            bound.update(iter_assigned_names(ast.Assign(targets=[generator.target], value=ast.Constant(None))))

        self._scopes.append(bound)
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        nodes = result_nodes if isinstance(result_nodes, list) else [result_nodes]
        for node in nodes:
            self.visit(node)
        self._scopes.pop()

    def _is_bound(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self._scopes))
