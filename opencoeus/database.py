from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .config import database_url
from .models import (
    Base,
    BatchStatus,
    EntryStatus,
    FileAudit,
    FolderClassification,
    NamingHistory,
    OrganizationRule,
    ProposedAction,
    ScanProfile,
    TransactionBatch,
    TransactionEntry,
)


# EXPECTED COLUMNS PER TABLE THAT MAY BE MISSING FROM OLDER DATABASES.
# FORMAT: {table_name: [(column_name, sqlite_ddl), ...]}
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
    ],
}


def _ensure_columns(engine) -> None:
    # INSPECTS EXISTING TABLES AND ADDS ANY COLUMNS DEFINED IN THE MODEL BUT MISSING FROM THE DB.
    # THIS HANDLES SCHEMA DRIFT FOR OLDER DATABASES WITHOUT A FULL MIGRATION FRAMEWORK.
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table_name, expected_columns in _EXPECTED_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col_name, col_ddl in expected_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}"))


class AuditStore:
    def __init__(self, database_connection_url: str | None = None) -> None:
        self.engine = create_engine(
            database_connection_url or database_url(),
            poolclass=NullPool,
        )
        # ENABLE FOREIGN KEY ENFORCEMENT FOR SQLITE ON EVERY NEW CONNECTION.
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        Base.metadata.create_all(self.engine)
        _ensure_columns(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def record_file(self, file_path: str, file_size: int, file_hash: str | None, file_status: str,
                    relative_path: str = "", extension: str = "", modified_at=None,
                    folder_path: str = "") -> None:
        with self.session_factory() as session:
            audit_record = session.scalar(select(FileAudit).where(FileAudit.path == file_path))
            if audit_record is None:
                audit_record = FileAudit(
                    path=file_path, size=file_size, sha256=file_hash, status=file_status,
                    relative_path=relative_path, extension=extension, modified_at=modified_at,
                    folder_path=folder_path,
                )
                session.add(audit_record)
            else:
                audit_record.size, audit_record.sha256, audit_record.status = file_size, file_hash, file_status
                audit_record.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
                audit_record.relative_path = relative_path or audit_record.relative_path
                audit_record.extension = extension or audit_record.extension
                audit_record.folder_path = folder_path or audit_record.folder_path
                if modified_at:
                    audit_record.modified_at = modified_at
            session.commit()

    def record_files_batch(self, records: list[tuple]) -> None:
        # BULK INSERTS OR UPDATES MULTIPLE FILE RECORDS IN A SINGLE SESSION FOR PERFORMANCE.
        with self.session_factory() as session:
            for record in records:
                file_path, file_size, file_hash, file_status = record[0], record[1], record[2], record[3]
                relative_path = record[4] if len(record) > 4 else ""
                extension = record[5] if len(record) > 5 else ""
                modified_at = record[6] if len(record) > 6 else None
                folder_path = record[7] if len(record) > 7 else ""
                audit_record = session.scalar(select(FileAudit).where(FileAudit.path == file_path))
                if audit_record is None:
                    audit_record = FileAudit(
                        path=file_path, size=file_size, sha256=file_hash, status=file_status,
                        relative_path=relative_path, extension=extension, modified_at=modified_at,
                        folder_path=folder_path,
                    )
                    session.add(audit_record)
                else:
                    audit_record.size, audit_record.sha256, audit_record.status = file_size, file_hash, file_status
                    audit_record.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
                    audit_record.relative_path = relative_path or audit_record.relative_path
                    audit_record.extension = extension or audit_record.extension
                    audit_record.folder_path = folder_path or audit_record.folder_path
                    if modified_at:
                        audit_record.modified_at = modified_at
            session.commit()

    def reserve_title(self, proposed_title: str, source_file_path: str) -> str:
        with self.session_factory() as session:
            existing_source_title = session.scalar(
                select(NamingHistory).where(NamingHistory.source_path == source_file_path)
            )
            if existing_source_title:
                return existing_source_title.suggested_title
            available_title, duplicate_number = proposed_title, 2
            while session.scalar(select(NamingHistory).where(NamingHistory.suggested_title == available_title)):
                available_title = f"{proposed_title} ({duplicate_number})"
                duplicate_number += 1
            session.add(NamingHistory(suggested_title=available_title, source_path=source_file_path))
            session.commit()
            return available_title

    # STAGE 2: PROFILE MANAGEMENT METHODS.

    def create_profile(self, name: str, root_path: str = "", included_folders: list[str] | None = None,
                       excluded_folders: list[str] | None = None, custom_protected_patterns: list[str] | None = None,
                       document_extraction: bool = True) -> ScanProfile:
        # CREATES AND PERSISTS A NEW SCAN PROFILE WITH DEFAULT EMPTY FOLDER LISTS.
        with self.session_factory() as session:
            profile = ScanProfile(
                name=name,
                root_path=root_path,
                included_folders=json.dumps(included_folders or []),
                excluded_folders=json.dumps(excluded_folders or []),
                custom_protected_patterns=json.dumps(custom_protected_patterns or []),
                document_extraction=document_extraction,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def list_profiles(self) -> list[ScanProfile]:
        # RETURNS ALL SAVED SCAN PROFILES ORDERED BY NAME.
        with self.session_factory() as session:
            return list(session.scalars(select(ScanProfile).order_by(ScanProfile.name)).all())

    def get_profile(self, profile_id: int) -> ScanProfile | None:
        # RETRIEVES A SINGLE SCAN PROFILE BY ITS ID.
        with self.session_factory() as session:
            return session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))

    def get_profile_by_name(self, profile_name: str) -> ScanProfile | None:
        # RETRIEVES A SINGLE SCAN PROFILE BY ITS UNIQUE NAME.
        with self.session_factory() as session:
            return session.scalar(select(ScanProfile).where(ScanProfile.name == profile_name))

    def update_profile(self, profile_id: int, **kwargs) -> ScanProfile | None:
        # UPDATES SPECIFIED FIELDS ON A SCAN PROFILE AND RECORDS THE UPDATE TIME.
        serializable_fields = {"included_folders", "excluded_folders", "custom_protected_patterns"}
        with self.session_factory() as session:
            profile = session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))
            if profile is None:
                return None
            for field_name, field_value in kwargs.items():
                if field_name in serializable_fields and isinstance(field_value, list):
                    field_value = json.dumps(field_value)
                setattr(profile, field_name, field_value)
            profile.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
            session.refresh(profile)
            return profile

    def delete_profile(self, profile_id: int) -> bool:
        # REMOVES A SCAN PROFILE AND ALL ITS ASSOCIATED CLASSIFICATIONS AND RULES.
        with self.session_factory() as session:
            profile = session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))
            if profile is None:
                return False
            # DELETE ASSOCIATED CLASSIFICATIONS.
            classifications = session.scalars(
                select(FolderClassification).where(FolderClassification.scan_profile_id == profile_id)
            ).all()
            for classification in classifications:
                session.delete(classification)
            # DELETE ASSOCIATED RULES.
            rules = session.scalars(
                select(OrganizationRule).where(OrganizationRule.scan_profile_id == profile_id)
            ).all()
            for rule in rules:
                session.delete(rule)
            # DELETE ASSOCIATED PROPOSED ACTIONS.
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all()
            for action in actions:
                session.delete(action)
            # DELETE ASSOCIATED TRANSACTION BATCHES AND ENTRIES.
            batch_ids = [
                b.id for b in session.scalars(
                    select(TransactionBatch).where(TransactionBatch.scan_profile_id == profile_id)
                ).all()
            ]
            if batch_ids:
                # CLEAR BATCH_ID REFERENCES FROM PROPOSED ACTIONS FIRST (FK).
                actions_with_batch = session.scalars(
                    select(ProposedAction).where(ProposedAction.batch_id.in_(batch_ids))
                ).all()
                for action in actions_with_batch:
                    action.batch_id = None
                entries = session.scalars(
                    select(TransactionEntry).where(TransactionEntry.batch_id.in_(batch_ids))
                ).all()
                for entry in entries:
                    session.delete(entry)
                for bid in batch_ids:
                    batch = session.get(TransactionBatch, bid)
                    if batch:
                        session.delete(batch)
            # DELETE ASSOCIATED NAMING HISTORY.
            naming = session.scalars(
                select(NamingHistory).where(NamingHistory.scan_profile_id == profile_id)
            ).all()
            for n in naming:
                session.delete(n)
            session.delete(profile)
            session.commit()
            return True

    # STAGE 2: FOLDER CLASSIFICATION METHODS.

    def save_classifications(self, profile_id: int, classifications: list[dict]) -> None:
        # SAVES A LIST OF FOLDER CLASSIFICATIONS FOR A GIVEN PROFILE.
        # SKIPS IF PROFILE DOES NOT EXIST (PREVENTS FK VIOLATIONS FROM ORPHANED DATA).
        with self.session_factory() as session:
            if not session.get(ScanProfile, profile_id):
                return
            # BULK DELETE EXISTING CLASSIFICATIONS FOR THIS PROFILE.
            session.query(FolderClassification).filter(
                FolderClassification.scan_profile_id == profile_id
            ).delete(synchronize_session="fetch")
            # BULK INSERT NEW CLASSIFICATIONS.
            new_objects = [
                FolderClassification(
                    scan_profile_id=profile_id,
                    folder_path=cd["folder_path"],
                    classification=cd["classification"],
                    recommended_action=cd["recommended_action"],
                    reason=cd.get("reason", ""),
                    user_override=cd.get("user_override"),
                )
                for cd in classifications
            ]
            session.add_all(new_objects)
            session.commit()

    def get_classifications(self, profile_id: int) -> list[FolderClassification]:
        # RETURNS ALL FOLDER CLASSIFICATIONS FOR A GIVEN PROFILE.
        with self.session_factory() as session:
            return list(session.scalars(
                select(FolderClassification).where(FolderClassification.scan_profile_id == profile_id)
            ).all())

    def update_classification_override(self, classification_id: int, user_override: str | None) -> bool:
        # UPDATES THE USER OVERRIDE FOR A SPECIFIC FOLDER CLASSIFICATION.
        with self.session_factory() as session:
            classification = session.scalar(
                select(FolderClassification).where(FolderClassification.id == classification_id)
            )
            if classification is None:
                return False
            classification.user_override = user_override
            session.commit()
            return True

    # STAGE 2: ORGANIZATION RULE METHODS.

    def create_rule(self, profile_id: int, name: str, rule_type: str, rule_config: dict,
                    destination_template: str, priority: int = 0, enabled: bool = True) -> OrganizationRule:
        # CREATES AND PERSISTS A NEW ORGANIZATION RULE FOR A PROFILE.
        with self.session_factory() as session:
            rule = OrganizationRule(
                scan_profile_id=profile_id,
                name=name,
                rule_type=rule_type,
                rule_config=json.dumps(rule_config),
                destination_template=destination_template,
                priority=priority,
                enabled=enabled,
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            return rule

    def get_rules(self, profile_id: int) -> list[OrganizationRule]:
        # RETURNS ALL ORGANIZATION RULES FOR A PROFILE ORDERED BY PRIORITY.
        with self.session_factory() as session:
            return list(session.scalars(
                select(OrganizationRule)
                .where(OrganizationRule.scan_profile_id == profile_id)
                .order_by(OrganizationRule.priority)
            ).all())

    def get_enabled_rules(self, profile_id: int) -> list[OrganizationRule]:
        # RETURNS ONLY ENABLED ORGANIZATION RULES FOR A PROFILE.
        with self.session_factory() as session:
            return list(session.scalars(
                select(OrganizationRule)
                .where(OrganizationRule.scan_profile_id == profile_id, OrganizationRule.enabled == True)
                .order_by(OrganizationRule.priority)
            ).all())

    def update_rule(self, rule_id: int, **kwargs) -> OrganizationRule | None:
        # UPDATES SPECIFIED FIELDS ON AN ORGANIZATION RULE.
        if "rule_config" in kwargs and isinstance(kwargs["rule_config"], dict):
            kwargs["rule_config"] = json.dumps(kwargs["rule_config"])
        with self.session_factory() as session:
            rule = session.scalar(select(OrganizationRule).where(OrganizationRule.id == rule_id))
            if rule is None:
                return None
            for field_name, field_value in kwargs.items():
                setattr(rule, field_name, field_value)
            rule.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
            session.refresh(rule)
            return rule

    def delete_rule(self, rule_id: int) -> bool:
        # REMOVES AN ORGANIZATION RULE BY ITS ID AND CLEANS UP ORPHANED PROPOSED ACTIONS.
        with self.session_factory() as session:
            rule = session.scalar(select(OrganizationRule).where(OrganizationRule.id == rule_id))
            if rule is None:
                return False
            # CLEAR RULE_ID FROM PROPOSED ACTIONS REFERENCING THIS RULE.
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.rule_id == rule_id)
            ).all()
            for action in actions:
                action.rule_id = None
            session.delete(rule)
            session.commit()
            return True

    # STAGE 2: PROPOSED ACTION METHODS.

    def save_proposed_actions(self, profile_id: int, actions: list[dict]) -> None:
        # SAVES A LIST OF PROPOSED ACTIONS, CLEARING PREVIOUS ONES FOR THE PROFILE.
        with self.session_factory() as session:
            existing = session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all()
            for item in existing:
                session.delete(item)
            for action_data in actions:
                session.add(ProposedAction(
                    scan_profile_id=profile_id,
                    original_path=action_data["original_path"],
                    proposed_path=action_data["proposed_path"],
                    action_type=action_data["action_type"],
                    rule_id=action_data.get("rule_id"),
                    reason=action_data.get("reason", ""),
                ))
            session.commit()

    def get_proposed_actions(self, profile_id: int) -> list[ProposedAction]:
        # RETURNS ALL PROPOSED ACTIONS FOR A GIVEN PROFILE.
        with self.session_factory() as session:
            return list(session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all())

    def approve_action(self, action_id: int) -> bool:
        # MARKS A PROPOSED ACTION AS APPROVED FOR FUTURE EXECUTION.
        with self.session_factory() as session:
            action = session.scalar(select(ProposedAction).where(ProposedAction.id == action_id))
            if action is None:
                return False
            action.approved = True
            session.commit()
            return True

    def reject_action(self, action_id: int) -> bool:
        # REMOVES A PROPOSED ACTION BY ITS ID (REJECTION).
        with self.session_factory() as session:
            action = session.scalar(select(ProposedAction).where(ProposedAction.id == action_id))
            if action is None:
                return False
            session.delete(action)
            session.commit()
            return True

    def approve_all_actions(self, profile_id: int) -> int:
        # MARKS ALL PROPOSED ACTIONS FOR A PROFILE AS APPROVED AND RETURNS THE COUNT.
        with self.session_factory() as session:
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all()
            count = 0
            for action in actions:
                action.approved = True
                count += 1
            session.commit()
            return count

    # STAGE 3: TRANSACTION BATCH AND ENTRY METHODS.

    def create_batch(self, profile_id: int, description: str = "") -> TransactionBatch:
        # CREATES A NEW TRANSACTION BATCH FOR TRACKING EXECUTION OF APPROVED ACTIONS.
        with self.session_factory() as session:
            batch = TransactionBatch(
                scan_profile_id=profile_id,
                description=description,
                status=EntryStatus.PENDING,
            )
            session.add(batch)
            session.commit()
            session.refresh(batch)
            return batch

    def add_entry(self, batch_id: int, action_id: int | None, action_type: str,
                  source_path: str, destination_path: str,
                  source_hash: str = "", source_size: int = 0) -> TransactionEntry:
        # ADDS A SINGLE TRANSACTION ENTRY TO A BATCH.
        with self.session_factory() as session:
            entry = TransactionEntry(
                batch_id=batch_id,
                action_id=action_id,
                action_type=action_type,
                source_path=source_path,
                destination_path=destination_path,
                source_hash=source_hash,
                source_size=source_size,
                status=EntryStatus.PENDING,
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry

    def get_entries_by_batch(self, batch_id: int, status: str | None = None) -> list[TransactionEntry]:
        # RETURNS ALL ENTRIES FOR A BATCH, OPTIONALLY FILTERED BY STATUS.
        with self.session_factory() as session:
            stmt = select(TransactionEntry).where(TransactionEntry.batch_id == batch_id)
            if status is not None:
                stmt = stmt.where(TransactionEntry.status == status)
            return list(session.scalars(stmt).all())

    def update_entry(self, entry_id: int, **kwargs) -> bool:
        # UPDATES SPECIFIED FIELDS ON A TRANSACTION ENTRY.
        with self.session_factory() as session:
            entry = session.scalar(select(TransactionEntry).where(TransactionEntry.id == entry_id))
            if entry is None:
                return False
            for field_name, field_value in kwargs.items():
                setattr(entry, field_name, field_value)
            session.commit()
            return True

    def mark_batch(self, batch_id: int, status: str, **kwargs) -> bool:
        # UPDATES BATCH STATUS AND OPTIONAL FIELDS LIKE COMPLETED_AT OR UNDONE_AT.
        with self.session_factory() as session:
            batch = session.scalar(select(TransactionBatch).where(TransactionBatch.id == batch_id))
            if batch is None:
                return False
            batch.status = status
            for field_name, field_value in kwargs.items():
                setattr(batch, field_name, field_value)
            session.commit()
            return True

    def get_undoable_batches(self, profile_id: int | None = None) -> list[TransactionBatch]:
        # RETURNS COMPLETED BATCHES IN REVERSE ORDER (MOST RECENT FIRST) FOR UNDO.
        with self.session_factory() as session:
            stmt = select(TransactionBatch).where(TransactionBatch.status == BatchStatus.COMPLETED)
            if profile_id is not None:
                stmt = stmt.where(TransactionBatch.scan_profile_id == profile_id)
            return list(session.scalars(stmt.order_by(TransactionBatch.id.desc())).all())

    def get_all_batches(self, profile_id: int | None = None, limit: int = 20) -> list[TransactionBatch]:
        # RETURNS ALL BATCHES IN REVERSE ORDER FOR THE BATCH HISTORY TABLE.
        with self.session_factory() as session:
            stmt = select(TransactionBatch)
            if profile_id is not None:
                stmt = stmt.where(TransactionBatch.scan_profile_id == profile_id)
            return list(session.scalars(stmt.order_by(TransactionBatch.id.desc()).limit(limit)).all())

    def get_batch_entry_counts(self, batch_ids: list[int]) -> dict[int, int]:
        # RETURNS ENTRY COUNTS FOR MULTIPLE BATCHES IN A SINGLE QUERY (AVOIDS N+1).
        if not batch_ids:
            return {}
        from sqlalchemy import func
        with self.session_factory() as session:
            rows = session.execute(
                select(TransactionEntry.batch_id, func.count(TransactionEntry.id))
                .where(TransactionEntry.batch_id.in_(batch_ids))
                .group_by(TransactionEntry.batch_id)
            ).all()
            return {batch_id: count for batch_id, count in rows}

    def get_latest_completed_batch(self, profile_id: int) -> TransactionBatch | None:
        # RETURNS THE MOST RECENTLY COMPLETED BATCH FOR A PROFILE.
        with self.session_factory() as session:
            return session.scalar(
                select(TransactionBatch)
                .where(
                    TransactionBatch.scan_profile_id == profile_id,
                    TransactionBatch.status == BatchStatus.COMPLETED,
                )
                .order_by(TransactionBatch.id.desc())
            )

    def get_batch(self, batch_id: int) -> TransactionBatch | None:
        # RETURNS A SINGLE BATCH BY ID.
        with self.session_factory() as session:
            return session.get(TransactionBatch, batch_id)

    def delete_proposed_actions_by_ids(self, action_ids: list[int]) -> int:
        # DELETES SPECIFIC PROPOSED ACTIONS BY THEIR IDS (REJECTION). RETURNS COUNT DELETED.
        if not action_ids:
            return 0
        with self.session_factory() as session:
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.id.in_(action_ids))
            ).all()
            count = len(actions)
            for action in actions:
                session.delete(action)
            session.commit()
            return count

    def close(self) -> None:
        """RELEASES SQLITE HANDLES PROMPTLY."""
        self.engine.dispose()
