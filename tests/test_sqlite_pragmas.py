"""SQLite pragmas tuned for large-library analysis."""

from __future__ import annotations

from app.services.context import AppContext


def test_connections_use_tuned_cache_temp_store_and_checkpoint(context: AppContext) -> None:
    with context.db.engine.connect() as connection:
        cursor = connection.connection.dbapi_connection.cursor()
        values: dict[str, int] = {}
        for name in ("cache_size", "temp_store", "wal_autocheckpoint"):
            cursor.execute(f"PRAGMA {name}")
            values[name] = int(cursor.fetchone()[0])
        cursor.close()

    assert values["cache_size"] <= -32768
    assert values["temp_store"] == 2
    assert values["wal_autocheckpoint"] >= 4096
