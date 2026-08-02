from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .safety import is_protected


@dataclass
class FolderNode:
    # REPRESENTS A SINGLE FOLDER IN THE DIRECTORY TREE WITH METADATA FOR UI DISPLAY
    name: str
    path: Path
    depth: int
    children: list[FolderNode] = field(default_factory=list)
    file_count: int = 0
    total_size: int = 0
    is_protected: bool = False
    classification: str | None = None
    recommended_action: str | None = None


def build_folder_tree(
    root_path: Path,
    protected_patterns: list[str],
    max_depth: int = 5,
    progress_callback=None,
) -> FolderNode:
    # BUILDS A RECURSIVE FOLDER TREE STARTING AT root_path, STOPPING AT max_depth
    # COMPUTES FILE COUNTS AND SIZES IN A SINGLE PASS DURING POPULATION
    root_node = FolderNode(
        name=root_path.name or str(root_path),
        path=root_path,
        depth=0,
        is_protected=is_protected(root_path, protected_patterns),
    )
    _populate_and_compute(root_node, protected_patterns, max_depth, progress_callback)
    return root_node


def _populate_and_compute(
    parent_node: FolderNode,
    protected_patterns: list[str],
    max_depth: int,
    progress_callback,
    _folder_counter: list[int] | None = None,
) -> None:
    # RECURSIVELY DISCOVERS SUBDIRECTORIES, POPULATES CHILDREN, AND COMPUTES STATS IN ONE PASS.
    # os.scandir gives one directory listing with cached per-entry stats, avoiding a second stat pass.
    if parent_node.depth >= max_depth:
        return
    if _folder_counter is None:
        _folder_counter = [0]
    try:
        with os.scandir(parent_node.path) as directory_entries:
            sorted_entries = sorted(directory_entries, key=lambda entry: entry.name.lower())
    except OSError:
        return
    for entry in sorted_entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            child_path = Path(entry.path)
            child_node = FolderNode(
                name=entry.name,
                path=child_path,
                depth=parent_node.depth + 1,
                is_protected=is_protected(child_path, protected_patterns),
            )
            parent_node.children.append(child_node)
            _folder_counter[0] += 1
            if progress_callback and _folder_counter[0] % 5 == 0:
                progress_callback(child_node.path)
            _populate_and_compute(child_node, protected_patterns, max_depth, progress_callback, _folder_counter)
            # AGGREGATE CHILD STATS UP TO PARENT
            parent_node.file_count += child_node.file_count
            parent_node.total_size += child_node.total_size
        elif entry.is_file():
            parent_node.file_count += 1
            try:
                parent_node.total_size += entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass


def flatten_tree(root: FolderNode) -> list[dict]:
    # CONVERTS THE NESTED TREE INTO A FLAT LIST OF DICTS WITH DEPTH FOR UI RENDERING
    flat_list = []
    _flatten_recursive(root, flat_list)
    return flat_list


def _flatten_recursive(node: FolderNode, accumulator: list[dict]) -> None:
    # APPENDS EACH NODE TO THE FLAT LIST IN PREORDER TRAVERSAL
    accumulator.append({
        "name": node.name,
        "path": node.path.as_posix(),
        "depth": node.depth,
        "file_count": node.file_count,
        "total_size": node.total_size,
        "is_protected": node.is_protected,
        "classification": node.classification,
        "recommended_action": node.recommended_action,
    })
    for child in node.children:
        _flatten_recursive(child, accumulator)
