from __future__ import annotations

import json
import logging

from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from ..config import database_url
from .models import (
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
from .schema import ensure_columns

logger = logging.getLogger(__name__)


class AuditStore:

    def __init__(self, database_connection_url: str | None = None) -> None:
        self.engine = create_engine(
            database_connection_url or database_url(),
            poolclass=NullPool,
        )

        event.listen(
            self.engine, "connect",
            lambda dbapi_conn, _connection_record: dbapi_conn.execute("PRAGMA foreign_keys=ON"),
        )

        from .models import Base
        Base.metadata.create_all(self.engine)
        ensure_columns(self.engine)
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
                audit_record.relative_path = relative_path or audit_record.relative_path
                audit_record.extension = extension or audit_record.extension
                audit_record.folder_path = folder_path or audit_record.folder_path
                if modified_at:
                    audit_record.modified_at = modified_at
            session.commit()

    def record_files_batch(self, records: list[tuple]) -> None:
        logger.debug("Recording %d files to database", len(records))
        if not records:
            return
        all_paths = [r[0] for r in records]
        with self.session_factory() as session:
            existing_rows = session.scalars(
                select(FileAudit).where(FileAudit.path.in_(all_paths))
            ).all()
            existing_map = {row.path: row for row in existing_rows}
            for record in records:
                file_path, file_size, file_hash, file_status = record[0], record[1], record[2], record[3]
                relative_path = record[4] if len(record) > 4 else ""
                extension = record[5] if len(record) > 5 else ""
                modified_at = record[6] if len(record) > 6 else None
                folder_path = record[7] if len(record) > 7 else ""
                audit_record = existing_map.get(file_path)
                if audit_record is None:
                    audit_record = FileAudit(
                        path=file_path, size=file_size, sha256=file_hash, status=file_status,
                        relative_path=relative_path, extension=extension, modified_at=modified_at,
                        folder_path=folder_path,
                    )
                    session.add(audit_record)
                else:
                    audit_record.size, audit_record.sha256, audit_record.status = file_size, file_hash, file_status
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

    def create_profile(self, name: str, root_path: str = "", included_folders: list[str] | None = None,
                       excluded_folders: list[str] | None = None, custom_protected_patterns: list[str] | None = None,
                       document_extraction: bool = True,
                       llm_enabled: bool = False, llm_model: str = "phi3",
                       llm_temperature: float = 0.3,
                       naming_strategy: str = "nlp_enhanced") -> ScanProfile:
        with self.session_factory() as session:
            profile = ScanProfile(
                name=name,
                root_path=root_path,
                included_folders=json.dumps(included_folders or []),
                excluded_folders=json.dumps(excluded_folders or []),
                custom_protected_patterns=json.dumps(custom_protected_patterns or []),
                document_extraction=document_extraction,
                llm_enabled=llm_enabled,
                llm_model=llm_model,
                llm_temperature=llm_temperature,
                naming_strategy=naming_strategy,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def list_profiles(self) -> list[ScanProfile]:
        with self.session_factory() as session:
            return list(session.scalars(select(ScanProfile).order_by(ScanProfile.name)).all())

    def get_profile(self, profile_id: int) -> ScanProfile | None:
        with self.session_factory() as session:
            return session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))

    def get_profile_by_name(self, profile_name: str) -> ScanProfile | None:
        with self.session_factory() as session:
            return session.scalar(select(ScanProfile).where(ScanProfile.name == profile_name))

    def update_profile(self, profile_id: int, **kwargs) -> ScanProfile | None:
        serializable_fields = {"included_folders", "excluded_folders", "custom_protected_patterns"}
        with self.session_factory() as session:
            profile = session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))
            if profile is None:
                return None
            for field_name, field_value in kwargs.items():
                if field_name in serializable_fields and isinstance(field_value, list):
                    field_value = json.dumps(field_value)
                setattr(profile, field_name, field_value)
            session.commit()
            session.refresh(profile)
            return profile

    def delete_profile(self, profile_id: int) -> bool:
        with self.session_factory() as session:
            profile = session.scalar(select(ScanProfile).where(ScanProfile.id == profile_id))
            if profile is None:
                return False
            classifications = session.scalars(
                select(FolderClassification).where(FolderClassification.scan_profile_id == profile_id)
            ).all()
            for classification in classifications:
                session.delete(classification)
            rules = session.scalars(
                select(OrganizationRule).where(OrganizationRule.scan_profile_id == profile_id)
            ).all()
            for rule in rules:
                session.delete(rule)
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all()
            for action in actions:
                session.delete(action)
            batch_ids = [
                b.id for b in session.scalars(
                    select(TransactionBatch).where(TransactionBatch.scan_profile_id == profile_id)
                ).all()
            ]
            if batch_ids:
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
            naming = session.scalars(
                select(NamingHistory).where(NamingHistory.scan_profile_id == profile_id)
            ).all()
            for n in naming:
                session.delete(n)
            session.delete(profile)
            session.commit()
            return True

    def save_classifications(self, profile_id: int, classifications: list[dict]) -> None:
        with self.session_factory() as session:
            if not session.get(ScanProfile, profile_id):
                return
            session.query(FolderClassification).filter(
                FolderClassification.scan_profile_id == profile_id
            ).delete(synchronize_session="fetch")
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
        with self.session_factory() as session:
            return list(session.scalars(
                select(FolderClassification).where(FolderClassification.scan_profile_id == profile_id)
            ).all())

    def update_classification_override(self, classification_id: int, user_override: str | None) -> bool:
        with self.session_factory() as session:
            classification = session.scalar(
                select(FolderClassification).where(FolderClassification.id == classification_id)
            )
            if classification is None:
                return False
            classification.user_override = user_override
            session.commit()
            return True

    def create_rule(self, profile_id: int, name: str, rule_type: str, rule_config: dict | str,
                    destination_template: str, priority: int = 0, enabled: bool = True,
                    action_type: str = "move", rename_template: str = "") -> OrganizationRule:
        if isinstance(rule_config, str):
            try:
                rule_config = json.loads(rule_config)
            except (json.JSONDecodeError, TypeError):
                rule_config = {}
        with self.session_factory() as session:
            rule = OrganizationRule(
                scan_profile_id=profile_id,
                name=name,
                rule_type=rule_type,
                rule_config=json.dumps(rule_config),
                destination_template=destination_template,
                priority=priority,
                enabled=enabled,
                action_type=action_type,
                rename_template=rename_template,
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            return rule

    def get_rules(self, profile_id: int) -> list[OrganizationRule]:
        with self.session_factory() as session:
            return list(session.scalars(
                select(OrganizationRule)
                .where(OrganizationRule.scan_profile_id == profile_id)
                .order_by(OrganizationRule.priority)
            ).all())

    def get_enabled_rules(self, profile_id: int) -> list[OrganizationRule]:
        with self.session_factory() as session:
            return list(session.scalars(
                select(OrganizationRule)
                .where(OrganizationRule.scan_profile_id == profile_id, OrganizationRule.enabled == True)
                .order_by(OrganizationRule.priority)
            ).all())

    def update_rule(self, rule_id: int, **kwargs) -> OrganizationRule | None:
        if "rule_config" in kwargs and isinstance(kwargs["rule_config"], dict):
            kwargs["rule_config"] = json.dumps(kwargs["rule_config"])
        with self.session_factory() as session:
            rule = session.scalar(select(OrganizationRule).where(OrganizationRule.id == rule_id))
            if rule is None:
                return None
            for field_name, field_value in kwargs.items():
                setattr(rule, field_name, field_value)
            session.commit()
            session.refresh(rule)
            return rule

    def delete_rule(self, rule_id: int) -> bool:
        with self.session_factory() as session:
            rule = session.scalar(select(OrganizationRule).where(OrganizationRule.id == rule_id))
            if rule is None:
                return False
            actions = session.scalars(
                select(ProposedAction).where(ProposedAction.rule_id == rule_id)
            ).all()
            for action in actions:
                action.rule_id = None
            session.delete(rule)
            session.commit()
            return True

    def toggle_rule(self, rule_id: int, enabled: bool | None = None) -> bool:
        with self.session_factory() as session:
            rule = session.scalar(select(OrganizationRule).where(OrganizationRule.id == rule_id))
            if rule is None:
                return False
            rule.enabled = not rule.enabled if enabled is None else enabled
            session.commit()
            return True

    def add_rule(self, profile_id: int, rule: dict) -> OrganizationRule:
        return self.create_rule(
            profile_id=profile_id,
            name=rule.get("name", "Unnamed"),
            rule_type=rule.get("rule_type", "always"),
            rule_config=rule.get("rule_config", {}),
            destination_template=rule.get("destination_template", ""),
            priority=rule.get("priority", 0),
            enabled=rule.get("enabled", True),
            action_type=rule.get("action_type", "move"),
            rename_template=rule.get("rename_template", ""),
        )

    def save_proposed_actions(self, profile_id: int, actions: list[dict]) -> None:
        with self.session_factory() as session:
            existing_ids = list(session.scalars(
                select(ProposedAction.id).where(ProposedAction.scan_profile_id == profile_id)
            ).all())
            if existing_ids:
                session.execute(
                    update(TransactionEntry)
                    .where(TransactionEntry.action_id.in_(existing_ids))
                    .values(action_id=None)
                )
                session.execute(
                    delete(ProposedAction).where(ProposedAction.id.in_(existing_ids))
                )
            rule_ids = {a.get("rule_id") for a in actions if a.get("rule_id") is not None}
            valid_rule_ids = set()
            if rule_ids:
                valid_rule_ids = set(session.scalars(
                    select(OrganizationRule.id).where(OrganizationRule.id.in_(rule_ids))
                ).all())
            for action_data in actions:
                raw_rule_id = action_data.get("rule_id")
                session.add(ProposedAction(
                    scan_profile_id=profile_id,
                    original_path=action_data["original_path"],
                    proposed_path=action_data["proposed_path"],
                    action_type=action_data["action_type"],
                    rule_id=raw_rule_id if raw_rule_id in valid_rule_ids else None,
                    reason=action_data.get("reason", ""),
                    original_filename=action_data.get("original_filename", ""),
                    new_filename=action_data.get("new_filename", ""),
                ))
            session.commit()

    def get_proposed_actions(self, profile_id: int) -> list[ProposedAction]:
        with self.session_factory() as session:
            return list(session.scalars(
                select(ProposedAction).where(ProposedAction.scan_profile_id == profile_id)
            ).all())

    def approve_action(self, action_id: int) -> bool:
        with self.session_factory() as session:
            action = session.scalar(select(ProposedAction).where(ProposedAction.id == action_id))
            if action is None:
                return False
            action.approved = True
            session.commit()
            return True

    def reject_action(self, action_id: int) -> bool:
        with self.session_factory() as session:
            action = session.scalar(select(ProposedAction).where(ProposedAction.id == action_id))
            if action is None:
                return False
            session.delete(action)
            session.commit()
            return True

    def approve_actions(self, action_ids: list[int]) -> int:
        if not action_ids:
            return 0
        with self.session_factory() as session:
            count = session.execute(
                update(ProposedAction)
                .where(ProposedAction.id.in_(action_ids))
                .values(approved=True)
            ).rowcount
            session.commit()
            return count

    def reject_actions(self, action_ids: list[int]) -> int:
        if not action_ids:
            return 0
        with self.session_factory() as session:
            count = session.execute(
                delete(ProposedAction)
                .where(ProposedAction.id.in_(action_ids))
            ).rowcount
            session.commit()
            return count

    def get_actions_by_ids(self, action_ids: list[int]) -> list[ProposedAction]:
        if not action_ids:
            return []
        with self.session_factory() as session:
            return list(session.scalars(
                select(ProposedAction).where(ProposedAction.id.in_(action_ids))
            ).all())

    def approve_all_actions(self, profile_id: int) -> int:
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

    def create_batch(self, profile_id: int, description: str = "") -> TransactionBatch:
        with self.session_factory() as session:
            batch = TransactionBatch(
                scan_profile_id=profile_id,
                description=description,
                status=BatchStatus.PENDING,
            )
            session.add(batch)
            session.commit()
            session.refresh(batch)
            return batch

    def add_entry(self, batch_id: int, action_id: int | None, action_type: str,
                  source_path: str, destination_path: str,
                  source_hash: str = "", source_size: int = 0) -> TransactionEntry:
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
        with self.session_factory() as session:
            stmt = select(TransactionEntry).where(TransactionEntry.batch_id == batch_id)
            if status is not None:
                stmt = stmt.where(TransactionEntry.status == status)
            return list(session.scalars(stmt).all())

    def update_entry(self, entry_id: int, **kwargs) -> bool:
        _allowed_update = {"status", "error_message", "destination_path", "source_hash",
                           "source_size", "destination_hash", "holding_path", "executed_at"}
        with self.session_factory() as session:
            entry = session.scalar(select(TransactionEntry).where(TransactionEntry.id == entry_id))
            if entry is None:
                return False
            for field_name, field_value in kwargs.items():
                if field_name in _allowed_update:
                    setattr(entry, field_name, field_value)
            if entry.error_message == "SHA-256: 0" and entry.status == EntryStatus.COMPLETED:
                entry.status = EntryStatus.PENDING
            session.commit()
            return True

    def mark_batch(self, batch_id: int, status: str, **kwargs) -> bool:
        _allowed_batch_fields = {"status", "completed_at", "undone_at"}
        with self.session_factory() as session:
            batch = session.scalar(select(TransactionBatch).where(TransactionBatch.id == batch_id))
            if batch is None:
                return False
            batch.status = status
            for field_name, field_value in kwargs.items():
                if field_name in _allowed_batch_fields:
                    setattr(batch, field_name, field_value)
            session.commit()
            return True

    def get_undoable_batches(self, profile_id: int | None = None) -> list[TransactionBatch]:
        with self.session_factory() as session:
            stmt = select(TransactionBatch).where(TransactionBatch.status == BatchStatus.COMPLETED)
            if profile_id is not None:
                stmt = stmt.where(TransactionBatch.scan_profile_id == profile_id)
            return list(session.scalars(stmt.order_by(TransactionBatch.id.desc())).all())

    def get_all_batches(self, profile_id: int | None = None, limit: int = 20) -> list[TransactionBatch]:
        with self.session_factory() as session:
            stmt = select(TransactionBatch)
            if profile_id is not None:
                stmt = stmt.where(TransactionBatch.scan_profile_id == profile_id)
            return list(session.scalars(stmt.order_by(TransactionBatch.id.desc()).limit(limit)).all())

    def get_latest_completed_batch(self, profile_id: int) -> TransactionBatch | None:
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
        with self.session_factory() as session:
            return session.get(TransactionBatch, batch_id)

    def delete_proposed_actions_by_ids(self, action_ids: list[int]) -> int:
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
        self.engine.dispose()
