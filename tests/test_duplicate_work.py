"""Guards against recomputing the same data during one analysis batch."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event

from app.intelligence import classifier as _classifier_module
from app.services import analysis_service
from app.services.context import AppContext
from tests.conftest import write_text


def _library(root: Path, count: int) -> None:
    for index in range(count):
        write_text(
            root / f"invoice_{index:02d}.txt",
            f"INVOICE\nInvoice number: INV-{index}\nAmount due: {index}.00\n",
        )


def test_stored_detected_format_is_reused(context: AppContext, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    _library(root, 2)

    original = analysis_service.inspect_format
    calls: list[object] = []

    def counting(path, extension=None):
        calls.append(path)
        return original(path, extension)

    monkeypatch.setattr(analysis_service, "inspect_format", counting)

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == 2
    assert calls == []


def test_keywords_are_extracted_once_per_file(context: AppContext, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    _library(root, 2)

    calls: list[str] = []

    def counting(text, *, limit=8):
        calls.append(str(limit))
        return _original_service(text, limit=limit)

    _original_service = analysis_service.extract_keywords
    monkeypatch.setattr(analysis_service, "extract_keywords", counting)

    original_classifier = _classifier_module.extract_keywords
    classifier_calls: list[str] = []

    def counting_classifier(text, *, limit=8):
        classifier_calls.append(str(limit))
        return original_classifier(text, limit=limit)

    monkeypatch.setattr(_classifier_module, "extract_keywords", counting_classifier)

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == 2
    assert len(calls) == 2
    assert classifier_calls == []


def test_keyword_and_summary_work_is_bounded_to_a_prefix(monkeypatch) -> None:
    from app.intelligence import keywords as keywords_module
    from app.intelligence import summarisation as summarisation_module

    keyword_lengths: list[int] = []
    original_keyword_pattern = keywords_module._WORD

    class CountingKeywordPattern:
        def findall(self, text: str):
            keyword_lengths.append(len(text))
            return original_keyword_pattern.findall(text)

    monkeypatch.setattr(keywords_module, "_WORD", CountingKeywordPattern())

    sentence_lengths: list[int] = []
    original_sentence_pattern = summarisation_module._SENTENCE

    class CountingSentencePattern:
        def split(self, text: str):
            sentence_lengths.append(len(text))
            return original_sentence_pattern.split(text)

    monkeypatch.setattr(summarisation_module, "_SENTENCE", CountingSentencePattern())

    long_text = ("Acme invoice amount due payment terms. " * 2000)
    assert keywords_module.extract_keywords(long_text)
    assert summarisation_module.extractive_summary(long_text)

    assert keyword_lengths
    assert sentence_lengths
    assert max(keyword_lengths) <= 20_000
    assert max(sentence_lengths) <= 20_000


def test_duplicate_lookup_is_grouped_and_skips_empty_hashes(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _library(root, 8)

    single_calls: list[tuple[int, str]] = []
    grouped_calls: list[dict[int, str]] = []

    def counting_single(file_id: int, sha256: str) -> int | None:
        single_calls.append((file_id, sha256))
        return None

    def counting_grouped(file_ids: list[int], hashes: dict[int, str]) -> dict[int, int]:
        grouped_calls.append(hashes)
        return {}

    monkeypatch.setattr(context.files, "find_analysed_duplicate", counting_single)
    monkeypatch.setattr(
        context.files, "find_analysed_duplicates", counting_grouped, raising=False
    )

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)

    assert report.analysed == 8
    assert single_calls == []
    assert len(grouped_calls) == 1
    assert all(grouped_calls[0].values())


def test_second_claim_of_the_same_file_is_skipped(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    write_text(root / "invoice.txt", "INVOICE\nAmount due: 10.00\n")
    context.scanning.scan(root)
    file_id = context.files.find_by_path(root / "invoice.txt")
    assert file_id is not None
    monkeypatch.setattr(
        context.files, "ids_by_status", lambda statuses, limit=None: [file_id]
    )

    first = context.analysis.analyse_pending(use_llm=False)
    second = context.analysis.analyse_pending(use_llm=False)

    assert first.analysed == 1
    assert second.analysed == 0


def test_prompt_templates_are_cached(context: AppContext) -> None:
    from app.intelligence import llm as llm_module

    original = llm_module._read_prompt
    for _ in range(3):
        llm_module.LocalLLMClient._render_prompt(
            "document_analysis.txt", {"categories": "A", "document_text": "B"}
        )
    assert original.cache_info().hits >= 2


def test_rebuild_uses_one_transaction(context: AppContext, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    _library(root, 3)
    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)

    commits = [0]

    def on_commit(_connection) -> None:
        commits[0] += 1

    event.listen(context.db.engine, "commit", on_commit)
    try:
        context.recovery.rebuild_search_index()
    finally:
        event.remove(context.db.engine, "commit", on_commit)
    assert commits[0] <= 1


def test_folder_cache_evicts_least_recently_used(context: AppContext, tmp_path: Path) -> None:
    from app.services.analysis_service import FOLDER_CACHE_LIMIT, AnalysisService

    cache: dict[Path, set[Path]] = {
        tmp_path / f"root_{index}": set() for index in range(FOLDER_CACHE_LIMIT)
    }
    oldest = next(iter(cache))
    newest_of_originals = next(reversed(cache))
    AnalysisService._folder_set(newest_of_originals, cache)
    AnalysisService._folder_set(tmp_path / "new_root", cache)

    assert oldest not in cache
    assert newest_of_originals in cache
    assert len(cache) == FOLDER_CACHE_LIMIT
