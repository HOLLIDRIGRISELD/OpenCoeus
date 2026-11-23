"""Repository helpers shared by the read models."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import Category


def category_path_map(session: Session) -> dict[int, str]:
    """Return ``{category_id: "Parent/Child"}`` for the whole category tree.

    The tree is tiny (tens of rows), so loading it once per query is cheaper
    than emitting a recursive self-join for every file.
    """

    rows = session.execute(select(Category.id, Category.name, Category.parent_id)).all()
    nodes = {row.id: (row.name, row.parent_id) for row in rows}
    paths: dict[int, str] = {}

    def build(category_id: int) -> str:
        if category_id in paths:
            return paths[category_id]
        parts: list[str] = []
        seen: set[int] = set()
        current: int | None = category_id
        while current is not None and current in nodes and current not in seen:
            seen.add(current)
            name, parent = nodes[current]
            parts.append(name)
            current = parent
        path = "/".join(reversed(parts))
        paths[category_id] = path
        return path

    for category_id in nodes:
        build(category_id)
    return paths
