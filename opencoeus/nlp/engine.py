from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from ..extractors import FileSignals
from .result import NLPResult

logger = logging.getLogger(__name__)

_MAX_NLP_CHARS = 30_000

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s{2,}")


def sanitize_filename(name: str) -> str:
    """Strip invalid Windows filename characters, control chars, and stray whitespace."""
    cleaned = _INVALID_CHARS.sub(" ", name)
    cleaned = _SPACES.sub(" ", cleaned)
    return cleaned.strip(" .-")[:200]

_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Invoice", re.compile(r"(invoice|inv[-#\s]?\d|amount\s+d(ue|ate)|billing|payment\s+terms)", re.IGNORECASE)),
    ("Meeting-Notes", re.compile(r"(meeting\s*(notes|minutes|log)|attendees?:|agenda|action\s+items)", re.IGNORECASE)),
    ("Specification", re.compile(r"(specification|spec[:.\s]|technical\s*(spec|requirement)|architecture\s*(overview|diagram))", re.IGNORECASE)),
    ("Report", re.compile(r"(report|summary|analysis|findings|conclusion)", re.IGNORECASE)),
    ("Budget", re.compile(r"(budget|financial|revenue|expenses?|forecast|quarterly)", re.IGNORECASE)),
    ("Contract", re.compile(r"(contract|agreement|terms?\s*(and|of)\s*(service|conditions|use)|legal)", re.IGNORECASE)),
    ("Presentation", re.compile(r"(presentation|slides?|deck)", re.IGNORECASE)),
    ("Readme", re.compile(r"(readme|getting\s+started)", re.IGNORECASE)),
    ("Backup", re.compile(r"(backup|archive|restore|snapshot)", re.IGNORECASE)),
    ("Spreadsheet", re.compile(r"(spreadsheet|worksheet|tab|csv|tabular)", re.IGNORECASE)),
    ("Resume", re.compile(r"(resume|cv|curriculum\s+vitae)", re.IGNORECASE)),
    ("Letter", re.compile(r"(dear\s+\w+|sincerely|yours\s+faithfully)", re.IGNORECASE)),
    ("Memo", re.compile(r"(memo|memorandum|to:?|from:?|re:?|subject:?)", re.IGNORECASE)),
    ("Article", re.compile(r"(article|abstract|introduction|methodology|references)", re.IGNORECASE)),
    ("Proposal", re.compile(r"(proposal|statement\s+of\s+work|scope\s+of\s+work|deliverables)", re.IGNORECASE)),
    ("Manual", re.compile(r"(manual|guide|tutorial|user\s+guide|reference)", re.IGNORECASE)),
    ("Certificate", re.compile(r"(certificate|certification|completion|certified)", re.IGNORECASE)),
    ("Form", re.compile(r"(form|application|registration|questionnaire)", re.IGNORECASE)),
    ("Policy", re.compile(r"(policy|procedure|compliance|regulation)", re.IGNORECASE)),
    ("Checklist", re.compile(r"(checklist|check\s*list|todo|tasks)", re.IGNORECASE)),
    ("Thesis", re.compile(r"(thesis|dissertation|doctoral|master['\u2019]s\s+thesis)", re.IGNORECASE)),
    ("Agenda", re.compile(r"(agenda|schedule|timeline|itinerary)", re.IGNORECASE)),
    ("Newsletter", re.compile(r"(newsletter|news\s*letter|issue\s+\d)", re.IGNORECASE)),
    ("Order", re.compile(r"(order|purchase\s+order|po\s*[-\s]?\d+)", re.IGNORECASE)),
    ("Quote", re.compile(r"(quote|quotation|estimate|price\s+list)", re.IGNORECASE)),
    ("Timesheet", re.compile(r"(timesheet|time\s*sheet|time\s+tracking|hours)", re.IGNORECASE)),
]

_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "it", "this", "that", "was",
    "are", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "not", "no", "nor", "so", "if", "then",
    "than", "also", "very", "just", "about", "above", "after", "again",
    "all", "any", "because", "before", "between", "both", "each",
    "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "too", "under", "up", "into", "over", "out", "off",
    "down", "here", "there", "when", "where", "why", "how", "what",
    "which", "who", "whom", "i", "you", "he", "she", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "myself", "yourself", "himself", "herself",
    "itself", "ourselves", "themselves",
})


class NLPEngine:

    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self._nlp = None
        self.confidence_threshold = confidence_threshold

    def _ensure_loaded(self) -> None:
        if self._nlp is not None:
            return
        try:
            import spacy
            self._nlp = spacy.load("en_core_web_sm")
        except Exception:
            logger.warning("spaCy model not available; NLP features disabled")
            self._nlp = None

    def analyze(self, file_path: Path, signals: FileSignals, stem: str = "") -> NLPResult:
        result = NLPResult(nlp_generated=False)
        self._ensure_loaded()

        text = signals.text
        metadata = signals.metadata
        category = signals.file_type
        ext = signals.extension

        entities: dict[str, list[str]] = {}
        doc = None

        if self._nlp and text and text.strip():
            doc = self._nlp(text[:_MAX_NLP_CHARS])
            for ent in doc.ents:
                label = ent.label_
                if label not in entities:
                    entities[label] = []
                if len(entities[label]) < 5:
                    entities[label].append(ent.text)

        persons = entities.get("PERSON", [])
        orgs = entities.get("ORG", [])
        gpes = entities.get("GPE", [])
        dates = entities.get("DATE", [])
        products = entities.get("PRODUCT", [])
        events = entities.get("EVENT", [])

        if persons:
            result.author = persons[0]
        elif metadata.get("author"):
            result.author = str(metadata["author"])

        if orgs:
            result.organization = orgs[0]
        elif metadata.get("creator"):
            result.organization = str(metadata["creator"])

        if gpes:
            result.location = gpes[0]

        entity_texts = products + events
        if entity_texts:
            result.project = entity_texts[0]
        elif metadata.get("subject"):
            result.project = str(metadata["subject"])

        if dates:
            result.date = dates[0]

        result.document_type = self._classify_document_type(text, metadata, persons, orgs)

        if text and text.strip():
            result.keywords = self._extract_keywords(text)
            result.summary = self._generate_summary(text)

        if category == "image":
            result.camera_model = metadata.get("camera_model", "")
            if not result.camera_model:
                result.camera_model = metadata.get("camera_make", "")
            date_taken = metadata.get("date_taken", "")
            if date_taken:
                result.date = date_taken[:10] if len(date_taken) >= 10 else date_taken

        if category == "audio":
            result.artist = metadata.get("artist", "")
            result.album = metadata.get("album", "")
            if not result.topic:
                result.topic = metadata.get("title", "")

        if category == "archive":
            contents = metadata.get("archive_contents", [])
            if contents:
                common_prefix = Path(contents[0]).parts[0] if contents else ""
                result.project = common_prefix

        confidence = self._calculate_confidence(signals, entities, doc)
        result.confidence = confidence

        result.smart_filename = self._generate_filename(result, stem, ext)
        result.smart_destination = self._generate_destination(result)

        return result

    def _classify_document_type(self, text: str, metadata: dict, persons: list[str], orgs: list[str]) -> str:
        combined = text
        if metadata:
            combined = text + "\n" + " ".join(str(v) for v in metadata.values() if v)
        for doc_type_name, pattern in _DOC_TYPE_PATTERNS:
            if pattern.search(combined):
                return doc_type_name
        return "Document"

    def _extract_keywords(self, text: str) -> list[str]:
        words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", text)
        filtered = [w.lower() for w in words if w.lower() not in _STOP_WORDS and len(w) > 2]
        common = Counter(filtered).most_common(20)
        seen = set()
        ordered = []
        for word, _count in common:
            if word not in seen:
                seen.add(word)
                ordered.append(word)
                if len(ordered) >= 10:
                    break
        return ordered

    def _generate_summary(self, text: str) -> str:
        clean = text.replace("\n", " ").strip()
        clean = re.sub(r"\s+", " ", clean)
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        for sentence in sentences:
            words = sentence.split()
            if 5 <= len(words) <= 40:
                safe = re.sub(r'[<>:"/\\|?*]', "-", sentence).strip(" .-")
                if safe:
                    return safe[:120]
        return ""

    def _calculate_confidence(self, signals: FileSignals, entities: dict[str, list[str]], doc) -> float:
        base = signals.confidence_hint
        boost = 0.0

        if signals.signals_present:
            boost += 0.05 * min(len(signals.signals_present), 4)

        total_entities = sum(len(v) for v in entities.values())
        if total_entities >= 5:
            boost += 0.15
        elif total_entities >= 2:
            boost += 0.08

        if "PERSON" in entities:
            boost += 0.05
        if "ORG" in entities:
            boost += 0.05
        if "GPE" in entities:
            boost += 0.03
        if "DATE" in entities:
            boost += 0.03

        if signals.file_type in ("document",) and len(signals.text) > 500:
            boost += 0.1

        if signals.file_type in ("image",) and ("camera_model" in signals.metadata or "date_taken" in signals.metadata):
            boost += 0.1

        if signals.file_type in ("audio",) and ("artist" in signals.metadata or "title" in signals.metadata):
            boost += 0.1

        if signals.file_type in ("installer", "system", "temp"):
            boost -= 0.3

        if doc and len(doc.ents) > 0:
            boost += 0.02

        return max(0.0, min(1.0, base + boost))

    def _generate_filename(self, result: NLPResult, stem: str, ext: str) -> str:
        parts = []
        if result.document_type and result.document_type != "Document":
            parts.append(result.document_type)

        if result.topic:
            parts.append(result.topic)

        if result.author:
            parts.append(result.author)
        elif result.organization:
            parts.append(result.organization)
        elif result.project:
            parts.append(result.project)
        elif result.artist:
            parts.append(result.artist)

        if result.camera_model:
            parts.append(result.camera_model)

        if not parts:
            return f"{sanitize_filename(stem)[:60]}{ext}"

        def _slug(text: str) -> str:
            text = re.sub(r"[^A-Za-z0-9 _-]+", " ", text)
            words = [w for w in text.split() if w]
            return "-".join(words)

        safe = "_".join(
            (_slug(p).lower() or "untitled") for p in parts if p.strip()
        )
        return f"{sanitize_filename(safe)[:60]}{ext}"

    def _generate_destination(self, result: NLPResult) -> str:
        parts = []
        if result.document_type and result.document_type != "Document":
            parts.append(result.document_type)
        elif result.file_type and result.file_type not in ("document", "unknown"):
            parts.append(result.file_type.capitalize())
        else:
            parts.append("Documents")

        if result.organization:
            parts.append(result.organization)
        elif result.project:
            parts.append(result.project)
        elif result.author:
            parts.append(result.author)
        elif result.artist:
            parts.append(result.artist)

        if result.date:
            year_match = re.search(r"\b(20\d{2})\b", result.date)
            if year_match:
                parts.append(year_match.group(1))

        return "/".join(
            re.sub(r'[<>:"/\\|?*]', "_", p).strip("_").replace(" ", "_")
            for p in parts
        )
