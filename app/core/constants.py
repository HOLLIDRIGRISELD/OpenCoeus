"""Constants shared across layers."""

from __future__ import annotations

APP_NAME = "OpenCoeus"
APP_VERSION = "0.6.0"
DB_SCHEMA_VERSION = 1

CHUNKER_VERSION = "1"
CLASSIFIER_VERSION = "1"

MAX_FILENAME_LENGTH = 120

FILENAME_SEPARATOR = " "

DEFAULT_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "Education",
        "Assignments",
        "Coursework submissions marked against a rubric, deadline or learning outcomes",
    ),
    (
        "Education",
        "Lecture Notes",
        "Teaching notes and class handouts captured during lectures or tutorials",
    ),
    (
        "Education",
        "Research",
        "Academic papers, literature reviews, theses and structured studies with references",
    ),
    (
        "Education",
        "Presentations",
        "Slide decks and seminar presentations with agenda or speaking notes",
    ),
    (
        "Finance",
        "Invoices",
        "Invoices and bills issued by a seller, with invoice number and amount due",
    ),
    (
        "Finance",
        "Receipts",
        "Proof-of-purchase receipts and expense claims confirming a completed payment",
    ),
    (
        "Finance",
        "Statements",
        "Bank or account statements listing balances and transactions over a period",
    ),
    (
        "Business",
        "Contracts",
        "Signed agreements, terms and legal obligations between named parties",
    ),
    (
        "Business",
        "Reports",
        "Business reports, proposals and meeting minutes for internal stakeholders",
    ),
    (
        "Technical",
        "Documentation",
        "Software manuals, setup guides, API references and troubleshooting notes",
    ),
    (
        "Personal",
        "Documents",
        "Identity records, private correspondence and personal administration documents",
    ),
    (
        "Government",
        "Reports",
        "Council and government reports, public consultations, official statistics, "
        "freedom-of-information responses and public-sector correspondence",
    ),
    (
        "Finance",
        "Expenses",
        "Expense claims and spending datasets listing suppliers, cost centres, amounts and transactions",
    ),
    (
        "Technical",
        "Source Code",
        "Source code, scripts, configuration files, manifests and code-repository content",
    ),
    (
        "Technical",
        "Web Pages",
        "HTML pages, web exports, browser saves and rendered web content",
    ),
    (
        "Personal",
        "Calendar",
        "Calendar events, appointments, schedules and iCalendar files",
    ),
)

UNCLASSIFIED = "Unclassified"

STATUS_DISCOVERED = "discovered"
STATUS_PENDING_EXTRACTION = "pending_extraction"
STATUS_EXTRACTING = "extracting"
STATUS_EXTRACTED = "extracted"
STATUS_PENDING_ANALYSIS = "pending_analysis"
STATUS_ANALYSING = "analysing"
STATUS_ANALYSED = "analysed"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_ORGANISED = "organised"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNAVAILABLE = "unavailable"

SUGGESTION_PENDING = "pending"
SUGGESTION_ACCEPTED = "accepted"
SUGGESTION_REJECTED = "rejected"
SUGGESTION_APPLIED = "applied"

PLAN_DRAFT = "draft"
PLAN_APPROVED = "approved"
PLAN_EXECUTING = "executing"
PLAN_COMPLETED = "completed"
PLAN_PARTIAL = "partially_completed"
PLAN_FAILED = "failed"
PLAN_REVALIDATION = "revalidation_required"

OP_PENDING = "pending"
OP_COMPLETED = "completed"
OP_FAILED = "failed"
OP_ROLLED_BACK = "rolled_back"
OP_SKIPPED = "skipped"

ACTION_RENAME = "rename"
ACTION_MOVE = "move"
ACTION_RENAME_MOVE = "rename_and_move"
ACTION_MKDIR = "create_directory"
