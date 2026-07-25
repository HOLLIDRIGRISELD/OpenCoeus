from __future__ import annotations

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
    included: bool = True
    excluded: bool = False


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
    # RECURSIVELY DISCOVERS SUBDIRECTORIES, POPULATES CHILDREN, AND COMPUTES STATS IN ONE PASS
    if parent_node.depth >= max_depth:
        return
    if _folder_counter is None:
        _folder_counter = [0]
    # DISCOVER ALL ENTRIES IN A SINGLE PASS: COUNT FILES, COLLECT SUBDIRECTORIES
    try:
        sorted_entries = sorted(parent_node.path.iterdir(), key=lambda entry: entry.name.lower())
    except PermissionError:
        return
    for entry in sorted_entries:
        if entry.is_symlink():
            continue
        if entry.is_file():
            parent_node.file_count += 1
            try:
                parent_node.total_size += entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    # POPULATE CHILDREN
    for entry in sorted_entries:
        if not entry.is_dir():
            continue
        if entry.is_symlink():
            continue
        child_node = FolderNode(
            name=entry.name,
            path=entry,
            depth=parent_node.depth + 1,
            is_protected=is_protected(entry, protected_patterns),
        )
        parent_node.children.append(child_node)
        _folder_counter[0] += 1
        if progress_callback and _folder_counter[0] % 5 == 0:
            progress_callback(child_node.path)
        _populate_and_compute(child_node, protected_patterns, max_depth, progress_callback, _folder_counter)
        # AGGREGATE CHILD STATS UP TO PARENT
        parent_node.file_count += child_node.file_count
        parent_node.total_size += child_node.total_size


def flatten_tree(root: FolderNode) -> list[dict]:
    # CONVERTS THE NESTED TREE INTO A FLAT LIST OF DICTS WITH DEPTH FOR UI RENDERING
    flat_list = []
    _flatten_recursive(root, flat_list)
    return flat_list


def build_node_index(root: FolderNode) -> dict[str, FolderNode]:
    # BUILDS A PATH STRING TO FOLDER NODE DICTIONARY FOR O(1) LOOKUPS
    index: dict[str, FolderNode] = {}
    _index_recursive(root, index)
    return index


def _index_recursive(node: FolderNode, index: dict[str, FolderNode]) -> None:
    index[node.path.as_posix()] = node
    for child in node.children:
        _index_recursive(child, index)


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
        "included": node.included,
        "excluded": node.excluded,
    })
    for child in node.children:
        _flatten_recursive(child, accumulator)


def find_node(root: FolderNode, target_path: Path) -> FolderNode | None:
    # SEARCHES THE TREE FOR A NODE MATCHING THE GIVEN PATH, RETURNING NONE IF NOT FOUND
    if root.path == target_path:
        return root
    for child in root.children:
        found = find_node(child, target_path)
        if found is not None:
            return found
    return None


def set_folder_exclusion(root: FolderNode, target_path: Path, excluded: bool,
                         node_index: dict[str, FolderNode] | None = None) -> bool:
    # TOGGLES THE EXCLUDED FLAG ON A SPECIFIC FOLDER AND RETURNS WHETHER IT WAS FOUND
    if node_index is not None:
        node = node_index.get(target_path.as_posix())
    else:
        node = find_node(root, target_path)
    if node is None:
        return False
    node.excluded = excluded
    node.included = not excluded
    return True
