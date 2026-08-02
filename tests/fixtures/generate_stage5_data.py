"""Stage 5 test data generator.

Generates large-scale test data for the full pipeline:
  - Stress: thousands of files across many directories
  - NLP/AI: rich documents with extractable text
  - Pipeline: scan -> organize -> actions -> execute -> verify
  - Import: copy external files into the test tree

Usage:
    python tests/fixtures/generate_stage5_data.py [--dir D:/test-data-stage5] [--files 2000]
                                                  [--import-from D:/source1 D:/source2 ...]
"""
import sys
from pathlib import Path

# Ensure the project root is on sys.path for standalone execution
_proj_root = Path(__file__).resolve().parent.parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

import argparse
import io
import os
import random
import shutil
import struct
import tarfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DIR_NAMES = [
    "Documents", "Photos", "Music", "Videos", "Code",
    "Spreadsheets", "Presentations", "Archives", "Downloads",
    "Projects", "Reports", "Invoices", "Backups", "Assets",
    "Templates", "Scripts", "Configs", "Data", "Logs", "Temp",
]

_FILE_TYPES: dict[str, tuple[str, int]] = {
    ".txt":   ("text/plain", 200),
    ".md":    ("text/markdown", 150),
    ".csv":   ("text/csv", 180),
    ".json":  ("application/json", 160),
    ".yaml":  ("application/x-yaml", 140),
    ".xml":   ("application/xml", 130),
    ".log":   ("text/plain", 300),
    ".py":    ("text/x-python", 100),
    ".js":    ("application/javascript", 100),
    ".html":  ("text/html", 90),
    ".css":   ("text/css", 80),
    ".jpg":   ("image/jpeg", 50),
    ".png":   ("image/png", 50),
    ".pdf":   ("application/pdf", 40),
    ".docx":  ("application/vnd.openxmlformats", 30),
    ".xlsx":  ("application/vnd.openxmlformats", 25),
}

# NLP-rich topic areas for document content
_TOPICS = [
    ("Invoice", "invoice", [
        "Invoice #INV-{n:05d}  Date: {date}  Amount: ${amt:,.2f}  From: {company}  Description: {paragraph}",
    ]),
    ("Report", "report", [
        "# {title}\n\n**Author**: {author}\n**Date**: {date}\n\n## Executive Summary\n\n{paragraph}",
    ]),
    ("Meeting Notes", "meeting", [
        "Meeting Notes - {date}\nAttendees: {attendees}\n\nAgenda:\n{paragraph}\n\nAction Items:\n- {person}: {task}",
    ]),
    ("Project Spec", "spec", [
        "# {title}\n\n## Overview\n\n{paragraph}\n\n## Requirements\n\n1. {req1}\n2. {req2}\n3. {req3}\n",
    ]),
    ("Research", "research", [
        "Research Note - {date}\nTopic: {topic}\n\n{paragraph}\n\nReferences:\n- {ref1}\n- {ref2}\n",
    ]),
    ("Contract", "contract", [
        "CONTRACT AGREEMENT\n\nBetween {company} and {client}\nDate: {date}\n\n{paragraph}\n\nTerms: {terms}",
    ]),
    ("Budget", "budget", [
        "Category,Q1,Q2,Q3,Q4,Total\n{cat1},{v1},{v2},{v3},{v4},{t1}\n{cat2},{v5},{v6},{v7},{v8},{t2}\n",
    ]),
    ("Technical Doc", "techdoc", [
        "# {title}\n\n## Description\n\n{paragraph}\n\n## API\n\n`{api_sig}`\n\n## Example\n\n```\n{example}\n```\n",
    ]),
]

_COMPANIES = ["Acme Corp", "Globex Inc", "Initech", "Hooli", "Stark Industries",
              "Wayne Enterprises", "Cyberdyne", "Umbrella Corp", "Tyrell Corp",
              "Wonka Industries", "Soylent Corp", "Oceanic Airlines"]

_PEOPLE = ["Alice Johnson", "Bob Smith", "Charlie Brown", "Diana Prince",
           "Eve Wilson", "Frank Castle", "Grace Hopper", "Hank Pym",
           "Ivy League", "Jack Sparrow", "Kate Bishop", "Leo Messi"]

_PARAGRAPHS = [
    "The quick brown fox jumps over the lazy dog. This pangram contains every letter of the English alphabet at least once.",
    "Data lifecycle management involves creating, storing, organizing, archiving, and deleting data in a structured manner.",
    "Machine learning algorithms can automatically classify and organize files based on their content and metadata patterns.",
    "A robust file organization system should handle duplicates, edge cases, and large volumes without performance degradation.",
    "Transaction journals provide a safety net by recording every file operation, enabling reliable undo and recovery.",
    "Natural language processing extracts meaningful metadata from documents, including topics, authors, and key phrases.",
    "Duplicate detection using SHA-256 hashing ensures that identical files are identified regardless of their names or locations.",
    "Cross-platform compatibility is essential for a data management tool that runs on Windows, macOS, and Linux.",
    "The holding area pattern moves files to a staging directory before applying final changes, enabling safe rollback.",
    "Folder classification categorizes directories into types like Documents, Media, Code, and Archives for targeted organization.",
]


# ---------------------------------------------------------------------------
# Minimal file headers
# ---------------------------------------------------------------------------
JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\x27 ',#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\x80"
    b"\xff\xd9"
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

WAV_HEADER = (
    b"RIFF" + struct.pack("<I", 36 + 4) + b"WAVE"
    + b"fmt " + struct.pack("<I", 16) + struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    + b"data" + struct.pack("<I", 4) + b"\x00\x00\x00\x00"
)

MP3_HEADER = (
    b"ID3\x03\x00\x00\x00\x00\x00"
    + b"\xff\xfb\x90\x00" + b"\x00" * 413
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rdate(start_year: int = 2018) -> str:
    d = datetime(random.randint(start_year, 2026), random.randint(1, 12), random.randint(1, 28))
    return d.strftime("%Y-%m-%d")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_stress_files(root: Path, count: int = 2000) -> int:
    """Generate *count* files across many directories for stress testing."""
    created = 0
    batch_size = 500
    for batch_start in range(0, count, batch_size):
        batch_end = min(batch_start + batch_size, count)
        dirs: list[Path] = []
        num_dirs = random.randint(5, 15)
        for _ in range(num_dirs):
            depth = random.randint(1, 4)
            parts = [random.choice(_DIR_NAMES) for _ in range(depth)]
            dirs.append(root.joinpath(*parts))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = []
            for i in range(batch_start, batch_end):
                d = random.choice(dirs)
                ext = random.choice(list(_FILE_TYPES.keys()))
                fname = f"file_{i:06d}{ext}"
                size = random.randint(10, 5000)
                content = os.urandom(size)
                futs.append(pool.submit(_write_bytes, d / fname, content))
            for f in as_completed(futs):
                f.result()
                created += 1
        progress = min(batch_end, count)
        print(f"  [Stress] {progress}/{count} files", end="\r", flush=True)
    print()
    return created


def generate_nlp_corpus(root: Path, count: int = 500) -> int:
    """Generate NLP-rich text/CSV/markdown documents for AI intelligence testing."""
    created = 0
    topic_data = _TOPICS
    for i in range(count):
        topic_label, topic_dir, templates = random.choice(topic_data)
        template = random.choice(templates)
        date_str = _rdate()
        n = random.randint(10000, 99999)
        company = random.choice(_COMPANIES)
        person = random.choice(_PEOPLE)
        client = random.choice(_PEOPLE)
        p1 = random.choice(_PARAGRAPHS)
        p2 = random.choice(_PARAGRAPHS)
        p3 = random.choice(_PARAGRAPHS)

        content = template.format(
            n=n, date=date_str, amt=random.uniform(100, 50000),
            company=company, client=client, author=person,
            title=f"{topic_label} {date_str} #{n:05d}",
            attendees=", ".join(random.sample(_PEOPLE, 4)),
            paragraph=p1, para2=p2, para3=p3,
            person=person, task=f"Complete {topic_label.lower()} review",
            topic=topic_label,
            req1=f"Implement {topic_label.lower()} module",
            req2="Test coverage > 90%",
            req3="Documentation for all public APIs",
            ref1=f"{p1[:60]}...",
            ref2=f"{p2[:60]}...",
            terms=f"Net {random.choice([15, 30, 60, 90])} days",
            cat1=random.choice(["Engineering", "Marketing", "Sales", "R&D"]),
            cat2=random.choice(["Infrastructure", "Personnel", "Training"]),
            v1=random.randint(10000, 99999), v2=random.randint(10000, 99999),
            v3=random.randint(10000, 99999), v4=random.randint(10000, 99999),
            t1=random.randint(40000, 399996),
            v5=random.randint(10000, 99999), v6=random.randint(10000, 99999),
            v7=random.randint(10000, 99999), v8=random.randint(10000, 99999),
            t2=random.randint(40000, 399996),
            api_sig=f"{topic_label.lower().replace(' ', '_')}(input: str) -> dict",
            example=f"result = {topic_label.lower().replace(' ', '_')}(\"{p1[:40]}\")",
        )

        subdir = root / topic_dir.title()
        fname = f"{topic_dir}_{i:04d}.txt"
        _write_text(subdir / fname, content)
        created += 1

        # Also create a companion CSV or JSON for some files
        if i % 3 == 0:
            meta = {
                "file_id": f"STAGE5-{n:05d}",
                "topic": topic_label,
                "date": date_str,
                "author": person,
                "company": company,
                "confidence": round(random.uniform(0.5, 1.0), 2),
            }
            import json
            _write_text(subdir / f"{topic_dir}_{i:04d}.meta.json", json.dumps(meta, indent=2))
            created += 1

        if (i + 1) % 100 == 0:
            print(f"  [NLP] {i + 1}/{count} documents")
    print(f"  [NLP] {count} documents (total {created} files including metadata)")
    return created


def generate_binary_media(root: Path, count: int = 200) -> int:
    """Generate binary media files (JPG, PNG, MP3, WAV) for testing."""
    created = 0
    generators = [
        (".jpg", JPEG_1X1, 50),
        (".png", PNG_1X1, 50),
        (".mp3", MP3_HEADER, 40),
        (".wav", WAV_HEADER, 30),
    ]

    for i in range(count):
        ext, header, _ = random.choices(generators, weights=[g[2] for g in generators])[0]
        padding = os.urandom(random.randint(100, 2000))
        subdir = root / random.choice(["Photos", "Music", "Downloads", "Assets"])
        fname = f"media_{i:04d}{ext}"
        _write_bytes(subdir / fname, header + padding)
        created += 1

        if (i + 1) % 50 == 0:
            print(f"  [Media] {i + 1}/{count} files")
    print(f"  [Media] {count} files")
    return created


def generate_archives(root: Path, count: int = 50) -> int:
    """Generate ZIP and tar.gz archives with internal files."""
    created = 0
    for i in range(count):
        subdir = root / "Archives"
        subdir.mkdir(parents=True, exist_ok=True)
        if random.random() < 0.6:
            path = subdir / f"archive_{i:04d}.zip"
            with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
                for j in range(random.randint(1, 5)):
                    zf.writestr(f"file_{j}.txt", f"Archive #{i} file #{j}\n")
        else:
            path = subdir / f"archive_{i:04d}.tar.gz"
            with tarfile.open(str(path), "w:gz") as tar:
                for j in range(random.randint(1, 5)):
                    info = tarfile.TarInfo(name=f"file_{j}.txt")
                    content = f"Archive #{i} file #{j}\n".encode()
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
        created += 1
    print(f"  [Archives] {count} archives")
    return created


def generate_duplicates(root: Path, count: int = 50) -> int:
    """Generate duplicate file groups for dedup testing."""
    created = 0
    for i in range(count):
        copies = random.randint(2, 4)
        content = (
            f"This is duplicate group #{i}.\n"
            f"Content hash: SHA256-STAGE5-{i:04d}\n"
            f"Created: {_rdate()}\n"
            + "".join(random.choices("abcdefghijklmnopqrstuvwxyz\n", k=100))
        ).encode()
        for c in range(copies):
            subdir = root / random.choice(["Downloads", "Documents", "Temp"])
            fname = f"dup_group{i:04d}_copy{c:02d}.txt"
            _write_bytes(subdir / fname, content)
            created += 1
    print(f"  [Duplicates] {count} groups ({created} files)")
    return created


def generate_edge_cases(root: Path) -> int:
    """Generate edge-case files: empty, unicode, long path, etc."""
    created = 0
    (root / "Edge").mkdir(parents=True, exist_ok=True)

    _write_text(root / "Edge" / "empty.txt", "")
    created += 1

    _write_text(root / "Edge" / "unicode_日本語_测试.txt",
                 "Unicode test: 日本語 测试 русский العربية\n")
    created += 1

    _write_text(root / "Edge" / ("x" * 180 + ".txt"), f"Long name test ({180} chars)\n")
    created += 1

    _write_text(root / "Edge" / "file with spaces and (parens).txt",
                 "Special chars in name\n")
    created += 1

    _write_text(root / "Edge" / "file.with.many.dots.txt",
                 "Multiple extension dots\n")
    created += 1

    _write_text(root / "Edge" / "permission_test.txt", "Permission edge case\n")
    created += 1

    # Hidden files (dot prefix)
    _write_text(root / "Edge" / ".hidden_file", "Hidden file content\n")
    created += 1

    # Symlink if supported (Windows requires admin or developer mode)
    try:
        target = root / "Edge" / "symlink_target.txt"
        if not target.exists():
            _write_text(target, "Symlink target\n")
            created += 1
        link_path = root / "Edge" / "symlink_link.txt"
        if not link_path.exists():
            os.symlink(str(target), str(link_path))
            created += 1
    except (OSError, NotImplementedError):
        pass

    print(f"  [Edge] {created} files")
    return created


# ---------------------------------------------------------------------------
# Import from external sources
# ---------------------------------------------------------------------------

def import_external_files(root: Path, sources: list[str], max_files: int = 0) -> int:
    """Copy files from external directories into the test tree.

    Args:
        root: Target test data root.
        sources: List of directory paths to import from.
        max_files: Maximum number of files to import (0 = unlimited).

    Returns:
        Number of files imported.
    """
    imported = 0
    imported_extensions: dict[str, int] = {}

    for src_path in sources:
        src = Path(src_path)
        if not src.is_dir():
            print(f"  [Import] Skipping {src_path}: not a directory")
            continue

        target_dir = root / "Imported" / src.name
        target_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [Import] Scanning {src}...")
        all_files = [p for p in src.rglob("*") if p.is_file()]

        if max_files > 0 and len(all_files) > max_files:
            all_files = random.sample(all_files, max_files)

        for fpath in all_files:
            try:
                rel = fpath.relative_to(src)
                # Flatten deep nesting: use relative path as name
                flat = "_".join(rel.parts)
                dest = target_dir / flat
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(fpath), str(dest))
                imported += 1
                ext = fpath.suffix.lower()
                imported_extensions[ext] = imported_extensions.get(ext, 0) + 1
            except (OSError, shutil.Error) as e:
                print(f"  [Import] Warning: could not copy {fpath}: {e}")

        print(f"  [Import] Copied {len(all_files)} files from {src.name}")

    if imported_extensions:
        top = sorted(imported_extensions.items(), key=lambda x: -x[1])[:5]
        print(f"  [Import] Top extensions: {', '.join(f'{ext}: {n}' for ext, n in top)}")
    print(f"  [Import] Total imported: {imported}")
    return imported


# ---------------------------------------------------------------------------
# Database population
# ---------------------------------------------------------------------------

def populate_database(db_path: Path, data_root: Path, profile_count: int = 3) -> str:
    """Create a SQLite database pre-populated with pipeline test data.

    Creates scan profiles, organization rules, proposed actions,
    transaction batches, and entries simulating a full pipeline run.

    Returns the SQLite connection URL.
    """
    from opencoeus.db.models import (
        Base, OrganizationRule,
    )
    from opencoeus.db.store import AuditStore
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Collect real files from the generated data tree
    real_files = list(data_root.rglob("*")) if data_root.exists() else []
    real_file_paths = [str(p) for p in real_files if p.is_file()]

    store = AuditStore(db_url)

    profile_ids = []
    total_actions = 0
    for pid in range(1, profile_count + 1):
        profile = store.create_profile(
            name=f"Stage5 Test Profile {pid}",
            root_path=str(data_root),
            document_extraction=True,
            naming_strategy="nlp_enhanced",
            llm_enabled=pid == 1,
            llm_model="phi3" if pid == 1 else "phi3",
            llm_temperature=0.3 if pid == 1 else 0.0,
        )
        # Set additional fields not exposed by create_profile
        store.update_profile(profile.id,
                             nlp_confidence_threshold=0.3,
                             installer_action="skip")
        pid_val = profile.id
        profile_ids.append(pid_val)

        # Create rules per profile
        with Session() as session:
            for ridx, (rname, rtype, rconf) in enumerate([
                ("Documents to Docs", "extension", {"extensions": [".pdf", ".docx", ".txt", ".md"]}),
                ("Images to Photos", "extension", {"extensions": [".jpg", ".png", ".tiff", ".bmp"]}),
                ("Audio to Music", "extension", {"extensions": [".mp3", ".wav", ".flac"]}),
                ("Videos to Media", "extension", {"extensions": [".mp4", ".mkv", ".avi"]}),
                ("Archives to Backup", "extension", {"extensions": [".zip", ".tar", ".gz", ".rar"]}),
                ("Code to Projects", "extension", {"extensions": [".py", ".js", ".ts", ".html", ".css"]}),
                ("Spreadsheets to Data", "extension", {"extensions": [".csv", ".xlsx", ".xls", ".json"]}),
                ("Old Files Archive", "older_than", {"days": 365}),
            ]):
                import json
                session.add(OrganizationRule(
                    scan_profile_id=pid_val,
                    name=rname,
                    rule_type=rtype,
                    rule_config=json.dumps(rconf),
                    destination_template=f"/{rname.split()[-1]}/" + "{filename}",
                    priority=ridx,
                    enabled=True,
                    action_type="move",
                    rename_template="",
                ))
            session.commit()

        # Create proposed actions from real file paths
        rules = store.get_rules(pid_val)
        actions_data: list[dict] = []
        if real_file_paths:
            action_batch = real_file_paths[:min(len(real_file_paths), 300)]
            for fpath in action_batch:
                p = Path(fpath)
                rule = random.choice(rules) if rules else None
                actions_data.append({
                    "original_path": fpath,
                    "proposed_path": str(p.parent.parent / f"Organized_{p.name}"),
                    "action_type": random.choice(["move", "rename"]),
                    "rule_id": rule.id if rule else None,
                    "reason": f"Matched rule: {rule.name}" if rule else "Manual",
                    "original_filename": p.name,
                    "new_filename": f"Org_{p.stem}{p.suffix}" if random.random() < 0.5 else p.name,
                })
            store.save_proposed_actions(pid_val, actions_data)
            total_actions += len(actions_data)

            # Approve some
            actions = store.get_proposed_actions(pid_val)
            for a in actions[:len(actions) // 2]:
                store.approve_action(a.id)

            # Create transaction batches with entries (for batch history testing)
            all_actions = store.get_proposed_actions(pid_val)
            approved = [a for a in all_actions if a.approved]
            if approved:
                chunk_size = max(10, len(approved) // 3)
                for batch_idx in range(0, len(approved), chunk_size):
                    chunk = approved[batch_idx:batch_idx + chunk_size]
                    batch = store.create_batch(
                        pid_val,
                        description=f"Stage 5 test batch #{batch_idx // chunk_size + 1}"
                    )
                    statuses = ["PENDING", "EXECUTING", "COMPLETED", "FAILED", "UNDONE"]
                    batch_status = random.choice(statuses)
                    now = datetime.now(UTC).replace(tzinfo=None)
                    kw = {}
                    if batch_status in ("COMPLETED", "FAILED"):
                        kw["completed_at"] = now
                    if batch_status == "UNDONE":
                        kw["completed_at"] = now
                        kw["undone_at"] = now
                    store.mark_batch(batch.id, batch_status, **kw)

                    for a in chunk:
                        e_status = "PENDING"
                        if batch_status == "COMPLETED":
                            e_status = random.choice(["COMPLETED", "MOVED_TO_HOLDING"])
                        elif batch_status == "FAILED":
                            e_status = random.choice(["FAILED", "PENDING"])
                        elif batch_status == "UNDONE":
                            e_status = "UNDONE"

                        store.add_entry(
                            batch_id=batch.id,
                            action_id=a.id,
                            action_type=a.action_type,
                            source_path=a.original_path,
                            destination_path=a.proposed_path,
                            source_hash=f"deadbeef{a.id:08x}",
                            source_size=random.randint(256, 1048576),
                        )
                        # Update entry status
                        entries = store.get_entries_by_batch(batch.id)
                        if entries:
                            store.update_entry(entries[-1].id, status=e_status)

    print(f"  [Database] {db_path} with {profile_count} profiles, "
          f"{total_actions} actions, batches")
    return db_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def create_stage5_data(
    root: Path = Path("D:/test-data-stage5"),
    file_count: int = 2000,
    nlp_count: int = 500,
    media_count: int = 200,
    archive_count: int = 50,
    duplicate_groups: int = 50,
    import_sources: list[str] | None = None,
    populate_db: bool = True,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Create the full Stage 5 test data structure.

    Returns a dict of category -> file count.
    """
    if root.exists():
        shutil.rmtree(str(root))
    root.mkdir(parents=True)
    print(f"Creating Stage 5 test data at {root}...\n")

    counts: dict[str, int] = {}

    counts["stress"] = generate_stress_files(root / "Stress", file_count)
    print()

    counts["nlp"] = generate_nlp_corpus(root / "NLP_Corpus", nlp_count)
    print()

    counts["media"] = generate_binary_media(root, media_count)
    print()

    counts["archives"] = generate_archives(root, archive_count)
    print()

    counts["duplicates"] = generate_duplicates(root, duplicate_groups)
    print()

    counts["edge"] = generate_edge_cases(root)
    print()

    if import_sources:
        counts["imported"] = import_external_files(root, import_sources)
        print()

    total_files = sum(1 for _ in root.rglob("*") if _.is_file())
    total_dirs = sum(1 for _ in root.rglob("*") if _.is_dir())
    print(f"Generated {total_files} files across {total_dirs} directories.")

    if populate_db:
        db_target = db_path or (root / "stage5_test.db")
        populate_database(db_target, root)

    counts["_total"] = total_files
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Stage 5 test data for OpenCoeus"
    )
    parser.add_argument("--dir", default="D:/test-data-stage5",
                        help="Output directory (default: D:/test-data-stage5)")
    parser.add_argument("--files", type=int, default=2000,
                        help="Number of stress-test files (default: 2000)")
    parser.add_argument("--nlp", type=int, default=500,
                        help="Number of NLP-rich documents (default: 500)")
    parser.add_argument("--media", type=int, default=200,
                        help="Number of media files (default: 200)")
    parser.add_argument("--archives", type=int, default=50,
                        help="Number of archive files (default: 50)")
    parser.add_argument("--dups", type=int, default=50,
                        help="Number of duplicate groups (default: 50)")
    parser.add_argument("--import-from", nargs="*", default=None,
                        help="External directories to import files from")
    parser.add_argument("--no-db", action="store_true",
                        help="Skip database population")
    parser.add_argument("--db-path", default=None,
                        help="Path for the test SQLite database")

    args = parser.parse_args()
    counts = create_stage5_data(
        root=Path(args.dir),
        file_count=args.files,
        nlp_count=args.nlp,
        media_count=args.media,
        archive_count=args.archives,
        duplicate_groups=args.dups,
        import_sources=args.import_from,
        populate_db=not args.no_db,
        db_path=Path(args.db_path) if args.db_path else None,
    )

    print("\n--- Summary ---")
    for k, v in counts.items():
        if k != "_total":
            print(f"  {k}: {v}")
    print(f"  TOTAL: {counts.get('_total', 0)}")


if __name__ == "__main__":
    main()
