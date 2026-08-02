from __future__ import annotations

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


_EXPECTED_COLUMNS = {
    "file_audits": [
        ("relative_path", "TEXT"),
        ("extension", "VARCHAR(32)"),
        ("modified_at", "DATETIME"),
        ("folder_path", "TEXT"),
    ],
    "naming_history": [
        ("scan_profile_id", "INTEGER REFERENCES scan_profiles(id)"),
    ],
    "proposed_actions": [
        ("reason", "TEXT DEFAULT ''"),
        ("batch_id", "INTEGER REFERENCES transaction_batches(id)"),
        ("original_filename", "TEXT DEFAULT ''"),
        ("new_filename", "TEXT DEFAULT ''"),
    ],
    "organization_rules": [
        ("action_type", "VARCHAR(32) DEFAULT 'move'"),
        ("rename_template", "TEXT DEFAULT ''"),
    ],
    "transaction_entries": [
        ("original_filename", "TEXT DEFAULT ''"),
        ("new_filename", "TEXT DEFAULT ''"),
    ],
    "scan_profiles": [
        ("nlp_confidence_threshold", "FLOAT DEFAULT 0.0"),
        ("naming_strategy", "VARCHAR(16) DEFAULT 'nlp_enhanced'"),
        ("installer_action", "VARCHAR(16) DEFAULT 'skip'"),
        ("llm_enabled", "BOOLEAN DEFAULT 0"),
        ("llm_model", "VARCHAR(64) DEFAULT 'phi3'"),
        ("llm_temperature", "FLOAT DEFAULT 0.3"),
    ],
}


def ensure_columns(engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    tables_to_check = [t for t in _EXPECTED_COLUMNS if t in existing_tables]
    logger.info("Ensuring schema columns for %d tables", len(tables_to_check))
    with engine.begin() as conn:
        for table_name, expected_columns in _EXPECTED_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col_name, col_ddl in expected_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}"))
                    logger.info("Added missing column %s.%s", table_name, col_name)
