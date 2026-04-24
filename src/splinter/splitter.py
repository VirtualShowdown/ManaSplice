from __future__ import annotations

from pathlib import Path

from .analysis import analyze_module, analyze_module_for_group
from .dependencies import (
    build_function_call_groups,
    collect_dependency_names,
    collect_required_import_names,
    detect_local_dependency_cycle,
    detect_mutable_global_dependencies,
    render_dependency_blocks,
)
from .exceptions import FunctionExtractionError
from .models import FileChange, GroupSplitResult, SplitOptions, SplitResult
from .resolver import ResolvedTarget
from .rewrite import (
    build_import_block,
    build_preview_diffs,
    compose_new_module_text,
    compute_group_import_statement,
    compute_replacement_import,
    extract_lines,
    insert_import,
    remove_function_block,
    remove_function_blocks,
    updated_package_exports,
    updated_package_exports_for_group,
    validate_output_package,
    validate_split_outputs,
)
from .utils import read_python_source, write_text_preserving_newlines

_insert_import = insert_import

__all__ = [
    "FileChange",
    "GroupSplitResult",
    "SplitOptions",
    "SplitResult",
    "build_function_call_groups",
    "split_function",
    "split_group",
]


def split_function(
    resolved: ResolvedTarget,
    *,
    options: SplitOptions | None = None,
    preview: bool | None = None,
) -> SplitResult:
    if options is None:
        options = SplitOptions()
    if preview is not None:
        options = SplitOptions(
            preview=preview,
            output_package=options.output_package,
            validate=options.validate,
            force=options.force,
        )
    validate_output_package(options.output_package)

    source_text = read_python_source(resolved.module_file)
    analysis = analyze_module(source_text, resolved.spec.function_name, resolved.module_file)

    dependency_names = collect_dependency_names(analysis.target.node, analysis.definitions)
    dependency_names.discard(resolved.spec.function_name)
    detect_local_dependency_cycle(
        resolved.spec.function_name,
        dependency_names,
        analysis.definitions,
        resolved.module_file,
    )
    detect_mutable_global_dependencies(dependency_names, analysis.definitions, resolved.module_file)

    new_module_file = _build_new_module_file_path(resolved, options)
    _ensure_can_write_new_module(new_module_file, options)
    init_file = new_module_file.parent / "__init__.py"
    new_module_existed_before = new_module_file.exists()
    init_file_existed_before = init_file.exists()
    existing_new_module_text = new_module_file.read_text(encoding="utf-8") if new_module_existed_before else ""
    existing_init_text = init_file.read_text(encoding="utf-8") if init_file_existed_before else ""
    init_text = updated_package_exports(existing_init_text, resolved.spec.function_name)

    dependency_nodes = [stmt for name, stmt in analysis.definitions.items() if name in dependency_names]
    required_imports = collect_required_import_names(
        [analysis.target.node],
        dependency_nodes,
        set(analysis.import_bindings),
    )
    function_block = extract_lines(
        analysis.source_text,
        analysis.target.start_lineno,
        analysis.target.end_lineno,
    )
    import_block = build_import_block(
        analysis.imports,
        analysis.source_text,
        resolved.package_mode,
        options.output_package,
        required_imports,
    )
    dependency_block = render_dependency_blocks(analysis.definitions, analysis.source_text, dependency_names)
    new_module_text = compose_new_module_text(
        source_path=resolved.module_file,
        import_block=import_block,
        dependency_block=dependency_block,
        function_block=function_block,
    )

    updated_source = remove_function_block(
        analysis.source_text,
        analysis.target.start_lineno,
        analysis.target.end_lineno,
    )
    import_statement = compute_replacement_import(
        resolved.package_mode,
        options.output_package,
        resolved.spec.function_name,
    )
    updated_source = _insert_import(updated_source, import_statement)

    file_changes = _build_file_changes(
        resolved.module_file,
        source_text,
        updated_source,
        new_module_file,
        new_module_existed_before,
        existing_new_module_text,
        new_module_text,
        init_file,
        init_file_existed_before,
        existing_init_text,
        init_text,
    )
    _validate_and_write(file_changes, new_module_file.parent, options)

    return SplitResult(
        module_file=resolved.module_file,
        new_module_file=new_module_file,
        function_name=resolved.spec.function_name,
        import_statement=import_statement,
        module_text=updated_source,
        new_module_text=new_module_text,
        init_file=init_file,
        init_text=init_text,
        preview=options.preview,
        file_changes=file_changes,
        output_package=options.output_package,
        preview_diffs=build_preview_diffs(file_changes),
    )


def split_group(
    resolved: ResolvedTarget,
    function_names: list[str],
    *,
    options: SplitOptions | None = None,
) -> GroupSplitResult:
    if options is None:
        options = SplitOptions()
    validate_output_package(options.output_package)

    source_text = read_python_source(resolved.module_file)
    analysis = analyze_module_for_group(source_text, function_names, resolved.module_file)

    func_set = set(function_names)
    all_dep_names: set[str] = set()
    for target_info in analysis.targets:
        all_dep_names.update(collect_dependency_names(target_info.node, analysis.definitions))
    all_dep_names -= func_set
    detect_mutable_global_dependencies(all_dep_names, analysis.definitions, resolved.module_file)

    group_module_name = resolved.spec.function_name
    package_parts = options.output_package.split(".")
    new_module_file = resolved.module_file.parent.joinpath(*package_parts) / f"{group_module_name}.py"
    _ensure_can_write_new_module(new_module_file, options)
    init_file = new_module_file.parent / "__init__.py"
    new_module_existed_before = new_module_file.exists()
    init_file_existed_before = init_file.exists()
    existing_new_module_text = new_module_file.read_text(encoding="utf-8") if new_module_existed_before else ""
    existing_init_text = init_file.read_text(encoding="utf-8") if init_file_existed_before else ""
    init_text = updated_package_exports_for_group(existing_init_text, group_module_name, function_names)

    dependency_nodes = [stmt for name, stmt in analysis.definitions.items() if name in all_dep_names]
    required_imports = collect_required_import_names(
        [target.node for target in analysis.targets],
        dependency_nodes,
        set(analysis.import_bindings),
    )
    import_block = build_import_block(
        analysis.imports,
        source_text,
        resolved.package_mode,
        options.output_package,
        required_imports,
    )
    dependency_block = render_dependency_blocks(analysis.definitions, source_text, all_dep_names)
    function_block = (
        "\n\n".join(
            extract_lines(source_text, target.start_lineno, target.end_lineno).strip() for target in analysis.targets
        )
        + "\n"
    )
    new_module_text = compose_new_module_text(
        source_path=resolved.module_file,
        import_block=import_block,
        dependency_block=dependency_block,
        function_block=function_block,
    )

    ranges = [(target.start_lineno, target.end_lineno) for target in analysis.targets]
    updated_source = remove_function_blocks(source_text, ranges)
    import_statement = compute_group_import_statement(
        resolved.package_mode,
        options.output_package,
        sorted(function_names),
    )
    for function_name in sorted(function_names):
        single = compute_replacement_import(resolved.package_mode, options.output_package, function_name)
        updated_source = _insert_import(updated_source, single)

    file_changes = _build_file_changes(
        resolved.module_file,
        source_text,
        updated_source,
        new_module_file,
        new_module_existed_before,
        existing_new_module_text,
        new_module_text,
        init_file,
        init_file_existed_before,
        existing_init_text,
        init_text,
    )
    _validate_and_write(file_changes, new_module_file.parent, options)

    return GroupSplitResult(
        module_file=resolved.module_file,
        new_module_file=new_module_file,
        function_names=function_names,
        import_statement=import_statement,
        module_text=updated_source,
        new_module_text=new_module_text,
        init_file=init_file,
        init_text=init_text,
        preview=options.preview,
        file_changes=file_changes,
        output_package=options.output_package,
        preview_diffs=build_preview_diffs(file_changes),
    )


def _build_new_module_file_path(resolved: ResolvedTarget, options: SplitOptions) -> Path:
    package_parts = options.output_package.split(".")
    return resolved.module_file.parent.joinpath(*package_parts) / f"{resolved.spec.function_name}.py"


def _ensure_can_write_new_module(new_module_file: Path, options: SplitOptions) -> None:
    if new_module_file.exists() and not options.force:
        raise FunctionExtractionError(
            f"Refusing to overwrite existing generated module '{new_module_file}'. Pass --force to replace it."
        )


def _build_file_changes(
    module_file: Path,
    source_text: str,
    updated_source: str,
    new_module_file: Path,
    new_module_existed_before: bool,
    existing_new_module_text: str,
    new_module_text: str,
    init_file: Path,
    init_file_existed_before: bool,
    existing_init_text: str,
    init_text: str,
) -> list[FileChange]:
    return [
        FileChange(
            path=module_file,
            existed_before=True,
            before_text=source_text,
            after_text=updated_source,
        ),
        FileChange(
            path=new_module_file,
            existed_before=new_module_existed_before,
            before_text=existing_new_module_text,
            after_text=new_module_text,
        ),
        FileChange(
            path=init_file,
            existed_before=init_file_existed_before,
            before_text=existing_init_text,
            after_text=init_text,
        ),
    ]


def _validate_and_write(file_changes: list[FileChange], output_dir: Path, options: SplitOptions) -> None:
    if options.validate:
        validate_split_outputs(file_changes)

    if options.preview:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for change in file_changes:
        if change.after_text or change.existed_before:
            write_text_preserving_newlines(change.path, change.after_text)
