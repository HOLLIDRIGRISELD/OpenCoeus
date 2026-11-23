"""Decision rule for the optional local language model.

The LLM is an expensive tie-breaker, not a primary classifier. Calling it for
every sufficiently long document slowed analysis and occasionally let a weak
model override good hybrid evidence. It is now used only when the evidence is
genuinely ambiguous *and* the document title could not be verified directly.
The availability probe is deliberately last: it may open a network connection,
so deterministic gates must be able to reject a document before it runs.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.models import ClassificationResult

MIN_LLM_TEXT_LENGTH = 80
UNCERTAIN_MARGIN = 0.08


def should_use_llm(
    *,
    classification: ClassificationResult,
    title_supported: bool,
    text_length: int,
    available: bool | Callable[[], bool],
) -> bool:
    """Return whether the local model should be consulted.

    ``classification.needs_review`` already encodes the configured low-confidence
    threshold. A small top-two margin is treated as uncertainty even when the
    absolute confidence is above that threshold. ``available`` may be a value or
    a lazy probe; a probe is called only after every cheap gate has passed.
    """

    if text_length < MIN_LLM_TEXT_LENGTH or title_supported:
        return False
    uncertain = (
        classification.needs_review
        or classification.confidence < 0.70
        or classification.margin < UNCERTAIN_MARGIN
    )
    if not uncertain:
        return False
    if callable(available):
        return bool(available())
    return bool(available)
