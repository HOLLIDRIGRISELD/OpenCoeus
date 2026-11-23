"""Hybrid document classification.

The classifier is deliberately not "an LLM that decides". It combines three
signals that can each be inspected:

1. **Deterministic keyword evidence** — domain vocabularies for common document
   families, with word-boundary matching.
2. **Semantic similarity** — cosine similarity between the document's embedding
   and the description of every category.
3. **Structural evidence** — filename and extension hints, weighted lower.

The weighted result is a ranked set of categories. Confidence is a calibrated
function of the winning score and the margin over the runner-up, not a number
invented by a language model. If the evidence is weak, the document is routed to
``Unclassified`` for human review.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from app.core.logging_config import get_logger
from app.domain.models import ClassificationResult
from app.intelligence.embeddings import EmbeddingEngine
from app.intelligence.keywords import extract_keywords

logger = get_logger(__name__)

RULE_WEIGHT = 0.45
SEMANTIC_WEIGHT = 0.55
SEMANTIC_BASELINE = 0.05
SEMANTIC_SCALE = 0.95
HASHING_BASELINE = 0.0
HASHING_SCALE = 0.25
MIN_EVIDENCE_SCORE = 0.22
UNCERTAIN_MARGIN = 0.08
FEEDBACK_WEIGHT = 0.32


def confidence_from_evidence(*, top_score: float, margin: float, rule_hits: float) -> float:
    """Turn ranked evidence into a bounded confidence score.

    The margin between the winner and runner-up is weighted more heavily than
    the raw score: a moderate winner with a clear gap is more trustworthy than
    two categories that score almost the same. This function is pure so it can
    be tuned against a labelled set without touching the classifier.
    """

    rule_bonus = min(1.0, max(0.0, rule_hits) / 3.0)
    score = 0.08 + 0.52 * top_score + 0.55 * margin + 0.08 * rule_bonus
    return min(0.98, max(0.0, round(score, 3)))


def semantic_range(is_semantic: bool) -> tuple[float, float]:
    """Return the cosine range used to normalise the active embedding backend."""

    if is_semantic:
        return SEMANTIC_BASELINE, SEMANTIC_SCALE
    return HASHING_BASELINE, HASHING_SCALE


_RULES: dict[str, tuple[str, ...]] = {
    "Education/Assignments": (
        "assignment", "coursework", "submission", "deadline", "marking", "rubric",
        "student id", "learning outcomes", "module code", "hand in",
    ),
    "Education/Lecture Notes": (
        "lecture", "seminar", "tutorial", "revision", "lecture notes", "week ",
        "learning outcomes", "reading list", "class notes", "study notes",
    ),
    "Education/Research": (
        "abstract", "literature review", "methodology", "hypothesis", "research question",
        "findings", "references", "doi", "et al", "survey", "experiment",
    ),
    "Education/Presentations": (
        "slide", "presentation", "seminar", "agenda", "learning outcomes", "lecture",
    ),
    "Finance/Invoices": (
        "invoice", "invoice number", "bill to", "amount due", "subtotal", "vat", "tax",
        "purchase order", "remit", "payment terms", "total due",
    ),
    "Finance/Receipts": (
        "receipt", "cashier", "transaction", "paid", "change due", "order total", "thank you for your purchase",
    ),
    "Finance/Statements": (
        "statement", "opening balance", "closing balance", "account number", "sort code",
        "iban", "transactions", "credit", "debit",
    ),
    "Business/Contracts": (
        "contract", "agreement", "terms and conditions", "party", "parties", "employment",
        "termination", "confidentiality", "signature", "witness", "governing law",
    ),
    "Business/Reports": (
        "report", "executive summary", "findings", "recommendations", "meeting minutes",
        "proposal", "objectives", "stakeholders", "action items", "business case",
    ),
    "Technical/Documentation": (
        "documentation", "installation", "configuration", "api", "endpoint", "usage",
        "troubleshooting", "reference", "schema", "command", "syntax", "readme",
        "getting started", "requirements",
    ),
    "Personal/Documents": (
        "passport", "national insurance", "date of birth", "curriculum vitae", "resume",
        "personal statement", "bank account", "travel itinerary", "boarding pass", "insurance policy",
    ),
    "Government/Reports": (
        "council", "public sector", "official", "consultation", "electoral",
        "planning", "foi", "freedom of information", "department for", "ministry", "premises",
    ),
    "Finance/Expenses": (
        "expense", "expense claim", "supplier", "cost centre", "reimbursement", "claim",
        "amount", "vat", "transaction", "spending",
    ),
    "Technical/Source Code": (
        "function", "import ", "export ", "const ", "def ", "class ", "npm", "package.json",
        "powershell", "css", "javascript", "python", "#!/", "require(", "module.exports",
        "async ", "await ", "=>",
    ),
    "Technical/Web Pages": (
        "<html", "<!doctype", "<div", "<span", "stylesheet", "href=", "web page",
        "browser", "octicon", "blob-code", "<head", "<meta", "<link", "<script",
        "<body", "</html>",
    ),
    "Personal/Calendar": (
        "vevent", "vcalendar", "dtstart", "dtend", "summary", "appointment", "event",
        "schedule", "calendar",
    ),
}

_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "Education": ("assignment", "lecture", "coursework", "university", "module", "semester", "exam"),
    "Finance": ("invoice", "receipt", "statement", "payment", "bank", "balance", "transaction"),
    "Business": ("contract", "client", "proposal", "meeting", "agreement", "company", "report"),
    "Technical": (
        "software", "api", "database", "system", "technical", "code", "server",
        "documentation", "script", "web", "html",
    ),
    "Personal": (
        "personal", "private", "passport", "cv", "resume", "travel",
        "calendar", "event", "appointment", "schedule",
    ),
    "Government": ("government", "council", "public", "official", "department", "ministry"),
}


@dataclass(slots=True)
class CategoryTarget:
    path: str
    description: str
    vector: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(1, dtype=np.float32))


class HybridClassifier:
    """Assigns a hierarchical category to a document.

    Args:
        categories: Mapping of ``"Parent/Child"`` to a human-written description.
        embeddings: Embedding engine used for semantic comparison.
        rule_weight: Weight of deterministic keyword evidence.
        semantic_weight: Weight of embedding similarity.
        review_threshold: Below this confidence the result is marked for review.
        feedback: Confirmed ``(category_path, vector)`` pairs from past reviews.
            They add a bounded prior; they never override the whole score.
    """

    def __init__(
        self,
        categories: dict[str, str],
        embeddings: EmbeddingEngine,
        *,
        rule_weight: float = RULE_WEIGHT,
        semantic_weight: float = SEMANTIC_WEIGHT,
        review_threshold: float = 0.60,
        feedback: Sequence[tuple[str, np.ndarray]] = (),
    ) -> None:
        if not categories:
            raise ValueError("At least one category description is required")
        self.embeddings = embeddings
        self.rule_weight = rule_weight
        self.semantic_weight = semantic_weight
        self.review_threshold = review_threshold
        self._feedback = list(feedback)
        self._feedback_vectors: list[tuple[str, np.ndarray]] = []
        hierarchical = [
            CategoryTarget(path=path, description=description or path.replace("/", " "))
            for path, description in categories.items()
            if "/" in path
        ]
        flat = [
            CategoryTarget(path=path, description=description or path)
            for path, description in categories.items()
            if "/" not in path
        ]
        self._targets = hierarchical + flat
        if not self._targets:
            raise ValueError("At least one category description is required")
        self._target_paths = {target.path for target in self._targets}
        self._vectors_ready = False

    def _ensure_vectors(self) -> None:
        if self._vectors_ready:
            return
        texts = [f"{target.path.replace('/', ' ')}. {target.description}" for target in self._targets]
        vectors = self.embeddings.encode(texts)
        for target, vector in zip(self._targets, vectors, strict=True):
            target.vector = vector
        dimension = self.embeddings.dimension
        self._feedback_vectors = [
            (path, vector)
            for path, vector in self._feedback
            if path in self._target_paths and vector.shape == (dimension,)
        ]
        self._vectors_ready = True

    def classify(
        self,
        text: str,
        *,
        filename: str = "",
        extension: str = "",
        title: str | None = None,
        document_vector: np.ndarray | None = None,
        keywords: Sequence[str] | None = None,
    ) -> ClassificationResult:
        """Classify a document from its text and filename.

        ``document_vector`` may be supplied by the analysis pipeline when it has
        already embedded the document's chunks. That avoids a second encode and
        uses the whole document instead of a truncated prefix.
        """

        self._ensure_vectors()
        haystack = " \n".join(
            part
            for part in (
                title or "",
                text[:12_000],
                filename.replace("_", " "),
                extension,
            )
            if part
        ).lower()
        if not haystack.strip():
            haystack = f"{filename} {extension}".lower()

        rule_scores = {target.path: self._rule_score(target.path, haystack) for target in self._targets}
        rule_norm = {path: min(1.0, score / 3.0) for path, score in rule_scores.items()}

        if document_vector is None:
            document_text = (
                (title + "\n\n" if title else "") + text[:4000] + "\n" + filename.replace("_", " ")
            )
            document_vector = self.embeddings.encode_one(document_text.strip() or filename)
        semantic_scores = {
            target.path: float(np.dot(document_vector, target.vector)) for target in self._targets
        }
        baseline, scale = semantic_range(self.embeddings.is_semantic)
        semantic_norm = {
            path: max(0.0, min(1.0, (score - baseline) / (scale - baseline)))
            for path, score in semantic_scores.items()
        }

        feedback_boosts = {path: 0.0 for path in rule_scores}
        if document_vector.shape == (self.embeddings.dimension,):
            for path, vector in self._feedback_vectors:
                similarity = max(0.0, float(np.dot(document_vector, vector)))
                feedback_boosts[path] = max(
                    feedback_boosts[path], FEEDBACK_WEIGHT * similarity
                )

        combined = {
            path: (
                self.rule_weight * rule_norm[path]
                + self.semantic_weight * semantic_norm[path]
                + feedback_boosts[path]
            )
            for path in rule_scores
        }
        ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
        top_path, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, top_score - second_score)

        rule_hits = rule_scores[top_path]
        has_content = bool((title or "").strip() or text.strip())
        if (top_score < MIN_EVIDENCE_SCORE or not has_content) and rule_hits < 1:
            return ClassificationResult(
                primary_category="Unclassified",
                secondary_category=None,
                category_path="Unclassified",
                confidence=round(min(0.45, 0.20 + top_score), 3),
                method="hybrid(insufficient_evidence)",
                margin=margin,
                tags=list(keywords[:5]) if keywords is not None else extract_keywords(text, limit=5),
                evidence=["No category reached the minimum evidence threshold."],
                scores={path: round(score, 3) for path, score in ranked[:4]},
                model_name=self.embeddings.model_name,
                needs_review=True,
            )

        confidence = confidence_from_evidence(
            top_score=top_score, margin=margin, rule_hits=rule_hits
        )

        primary, _, secondary = top_path.partition("/")
        evidence = self._evidence(
            top_path, rule_scores, semantic_scores, haystack, feedback_boosts
        )
        tags = list(keywords[:7]) if keywords is not None else extract_keywords(text, limit=7)
        for label in (secondary, primary):
            if label and label not in tags:
                tags.append(label)

        feedback_flag = ",feedback=on" if self._feedback_vectors else ""
        method = (
            f"hybrid(rules={self.rule_weight:.2f},"
            f"semantic={self.semantic_weight:.2f},model={self.embeddings.model_name}"
            f"{feedback_flag})"
        )
        return ClassificationResult(
            primary_category=primary,
            secondary_category=secondary or None,
            category_path=top_path,
            confidence=confidence,
            margin=margin,
            method=method,
            tags=tags[:9],
            evidence=evidence,
            scores={path: round(score, 3) for path, score in ranked[:5]},
            model_name=self.embeddings.model_name,
            needs_review=confidence < self.review_threshold,
        )

    def _rule_score(self, category_path: str, haystack: str) -> float:
        keywords = _RULES.get(category_path, ())
        score = 0.0
        for keyword in keywords:
            if _contains(haystack, keyword):
                score += 1.0
        top_level = category_path.split("/")[0]
        for hint in _TYPE_HINTS.get(top_level, ()):
            if _contains(haystack, hint):
                score += 0.25
        return score

    def _evidence(
        self,
        top_path: str,
        rule_scores: dict[str, float],
        semantic_scores: dict[str, float],
        haystack: str,
        feedback_boosts: dict[str, float] | None = None,
    ) -> list[str]:
        evidence: list[str] = []
        matched = [keyword for keyword in _RULES.get(top_path, ()) if _contains(haystack, keyword)]
        if matched:
            evidence.append("Matched document terms: " + ", ".join(matched[:6]))
        evidence.append(
            f"Semantic similarity to '{top_path}' description: {semantic_scores[top_path]:.2f}"
        )
        if feedback_boosts:
            best_path, best_boost = max(
                feedback_boosts.items(), key=lambda item: item[1], default=("", 0.0)
            )
            if best_boost > 0.05:
                evidence.append(
                    f"Confirmed review decision supports '{best_path}' "
                    f"(prior {best_boost:.2f})."
                )
        if rule_scores[top_path] > 0:
            evidence.append(f"Deterministic keyword score: {rule_scores[top_path]:.1f}")
        runner_up = sorted(
            ((path, score) for path, score in semantic_scores.items() if path != top_path),
            key=lambda item: item[1],
            reverse=True,
        )
        if runner_up and runner_up[0][1] > 0.25:
            evidence.append(f"Next closest category: {runner_up[0][0]} ({runner_up[0][1]:.2f})")
        return evidence


def _contains(haystack: str, needle: str) -> bool:
    """Word-boundary-aware substring match (safe for multi-word phrases)."""

    if " " in needle or not needle.isalnum():
        return needle in haystack
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
