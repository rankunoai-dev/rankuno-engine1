"""Tests for the Screaming Frog adapter (plan P0-3, ADR 0011).

Every hostile input is built in `tmp_path` on example.com and carries
`?token=SENTINEL`, so a leak of any cell value into a log or an exception is a
string match away. Zip and directory guards live in `test_screaming_frog_bundle`.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.modules.seo.contracts.audit import AuditDataset, AuditSource, Coverage, IssueId
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE, ISSUE_SPECS
from src.modules.seo.deliverables import screaming_frog_adapter
from src.modules.seo.deliverables.screaming_frog_adapter import (
    LINKS_NOT_RETAINED_NOTE,
    SPINE_FILE,
    NormalizerContractError,
    ScreamingFrogBundleError,
    load_screaming_frog_bundle,
)

FIXTURE_BUNDLE = Path(__file__).resolve().parents[2] / "fixtures" / "deliverables" / "sf_bundle"
PRODUCED_AT = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
HOME = "https://example.com/"
ABOUT = "https://example.com/about/"
SENTINEL = "https://example.com/?token=SENTINEL"
LOGGER_NAME = f"rankuno.{screaming_frog_adapter.__name__}"


def identity(url: str) -> str:
    return url


def csv_text(header: Sequence[str], *rows: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def spine_text(*urls: str) -> str:
    return csv_text(["Address", "Status Code"], *[(url, "200") for url in urls])


def write_bundle(root: Path, files: dict[str, str | bytes]) -> Path:
    """Write files with a BOM, exactly as Screaming Frog exports them."""
    root.mkdir(exist_ok=True)
    for name, body in files.items():
        if isinstance(body, bytes):
            (root / name).write_bytes(body)
        else:
            (root / name).write_text(body, encoding="utf-8-sig", newline="")
    return root


def load(path: Path, normalize=identity) -> AuditDataset:
    return load_screaming_frog_bundle(path, normalize=normalize, produced_at=PRODUCED_AT)


LEAK_MARKERS = ("SENTINEL", "http://", "https://", "example.com")
"""Anything from a cell that could surface in a message. Catalogue filenames
such as `security_http_urls.csv` are permitted, so the check is for schemes."""


def assert_no_leak(text: str) -> None:
    for marker in LEAK_MARKERS:
        assert marker not in text, marker


def assert_clean(exc: BaseException) -> None:
    assert_no_leak(str(exc))


def load_raises(path: Path, rule: str, normalize=identity) -> ScreamingFrogBundleError:
    with pytest.raises(ScreamingFrogBundleError) as info:
        load(path, normalize)
    assert isinstance(info.value, ValueError)
    assert info.value.rule == rule
    assert_clean(info.value)
    return info.value


class _Recorder:
    """Stands in for the module logger so `extra=` payloads can be inspected.

    Needed because `core.logger.get_logger` wraps a `LoggerAdapter` whose
    default `process()` discards the caller's `extra` on Python 3.11.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def info(self, msg: str, *, extra: dict[str, object] | None = None) -> None:
        self.calls.append(("INFO", msg, extra or {}))

    def warning(self, msg: str, *, extra: dict[str, object] | None = None) -> None:
        self.calls.append(("WARNING", msg, extra or {}))

    def error(self, msg: str, *, extra: dict[str, object] | None = None) -> None:
        self.calls.append(("ERROR", msg, extra or {}))

    def payload(self, event: str) -> dict[str, object]:
        return next(extra for _, msg, extra in self.calls if msg == event)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(screaming_frog_adapter, "_logger", rec)
    return rec


@pytest.fixture
def sf_caplog(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """`caplog` wired to the `rankuno` logger, which does not propagate to root."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(caplog.handler)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        yield caplog
    logger.removeHandler(caplog.handler)


# --------------------------------------------------------------------------
# Coverage semantics on the committed fixture
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_dataset() -> AuditDataset:
    return load(FIXTURE_BUNDLE)


def test_every_issue_id_has_a_coverage_entry(fixture_dataset: AuditDataset):
    assert set(fixture_dataset.coverage) == set(IssueId)
    assert set(fixture_dataset.issues) == set(IssueId)
    assert fixture_dataset.source is AuditSource.SCREAMING_FROG


def test_rows_without_sources_are_not_measured_and_empty(fixture_dataset: AuditDataset):
    unsourced = [spec.id for spec in ISSUE_CATALOGUE if not spec.sf_sources]
    assert unsourced, "catalogue should contain rows with no producible input"
    for issue in unsourced:
        assert fixture_dataset.coverage[issue] is Coverage.NOT_MEASURED
        assert fixture_dataset.issues[issue] == frozenset()


def test_absent_file_is_not_measured_and_empty(fixture_dataset: AuditDataset):
    assert not (FIXTURE_BUNDLE / "h1_duplicate.csv").exists()
    assert fixture_dataset.coverage[IssueId.H1_DUPLICATE] is Coverage.NOT_MEASURED
    assert fixture_dataset.issues[IssueId.H1_DUPLICATE] == frozenset()


def test_header_only_file_is_measured_and_empty(fixture_dataset: AuditDataset):
    assert fixture_dataset.coverage[IssueId.PAGE_TITLES_MISSING] is Coverage.MEASURED
    assert fixture_dataset.issues[IssueId.PAGE_TITLES_MISSING] == frozenset()


def test_edge_list_files_contribute_source_only(fixture_dataset: AuditDataset):
    broken_target = "https://example.com/old-page/"
    inlinks = fixture_dataset.issues[IssueId.INTERNAL_LINKS_4XX_INLINKS]
    assert inlinks == frozenset({HOME, "https://example.com/blog/post-1/"})
    assert broken_target not in inlinks
    assert broken_target in fixture_dataset.issues[IssueId.RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX]


def test_source_only_shapes_without_a_type_column(fixture_dataset: AuditDataset):
    form = fixture_dataset.issues[IssueId.SECURITY_FORM_URL_INSECURE]
    assert form == frozenset({"https://example.com/contact/"})
    cross = fixture_dataset.issues[IssueId.SECURITY_UNSAFE_CROSS_ORIGIN_LINKS]
    assert cross == frozenset({"https://example.com/blog/"})


def test_one_row_file_under_100_bytes_is_read(fixture_dataset: AuditDataset):
    assert (FIXTURE_BUNDLE / "form_url_insecure.csv").stat().st_size < 100
    assert fixture_dataset.coverage[IssueId.SECURITY_FORM_URL_INSECURE] is Coverage.MEASURED
    assert fixture_dataset.issues[IssueId.SECURITY_FORM_URL_INSECURE]


def test_every_fixture_file_has_a_bom_that_does_not_leak_into_headers():
    files = sorted(FIXTURE_BUNDLE.iterdir())
    assert len(files) == 17
    for path in files:
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name
    # If the BOM leaked, the first header cell would be "\ufeffAddress" and the
    # spine would fail with no-url-column instead of loading.
    assert len(load(FIXTURE_BUNDLE).pages) == 12


def test_two_source_row_unions_files(fixture_dataset: AuditDataset):
    spec = ISSUE_SPECS[IssueId.INTERNAL_LINKS_CANONICAL_ISSUE_INLINKS]
    assert len(spec.sf_sources) == 2
    assert fixture_dataset.issues[spec.id] == frozenset({HOME, ABOUT})


def test_two_source_row_with_one_file_present_is_measured(tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b",
        {
            SPINE_FILE: spine_text(HOME, ABOUT),
            "canonicalised_inlinks.csv": csv_text(
                ["Type", "Source", "Destination"], ["H", ABOUT, HOME]
            ),
        },
    )
    dataset = load(bundle)
    issue = IssueId.INTERNAL_LINKS_CANONICAL_ISSUE_INLINKS
    assert dataset.coverage[issue] is Coverage.MEASURED
    assert dataset.issues[issue] == frozenset({ABOUT})


def test_duplicate_rows_collapse(fixture_dataset: AuditDataset):
    assert fixture_dataset.issues[IssueId.CONTENT_LOW_CONTENT_PAGES] == frozenset(
        {"https://example.com/thin/"}
    )


def test_normalisation_collapse_is_counted_not_duplicated(recorder: _Recorder):
    def strip_query(url: str) -> str:
        return url.split("?", 1)[0]

    dataset = load(FIXTURE_BUNDLE, strip_query)
    urls = [page.url for page in dataset.pages]
    assert len(urls) == len(set(urls)) == 11
    assert recorder.payload("sf_bundle_loaded")["duplicates_dropped"] == 1


def test_dataset_validates_and_json_round_trips(fixture_dataset: AuditDataset):
    payload = fixture_dataset.model_dump(mode="json")
    assert payload["source"] == "screaming_frog"
    assert AuditDataset.model_validate(payload) == fixture_dataset
    assert AuditDataset.model_validate_json(fixture_dataset.model_dump_json()) == fixture_dataset


def test_links_are_empty_with_a_note(fixture_dataset: AuditDataset):
    assert fixture_dataset.links == ()
    assert LINKS_NOT_RETAINED_NOTE in fixture_dataset.notes


def test_produced_at_defaults_to_aware_utc_now():
    dataset = load_screaming_frog_bundle(FIXTURE_BUNDLE, normalize=identity)
    assert dataset.produced_at.tzinfo is UTC


# --------------------------------------------------------------------------
# Site derivation
# --------------------------------------------------------------------------


def test_site_strips_www_and_port(tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b",
        {SPINE_FILE: spine_text("https://www.example.com:443/", "https://WWW.Example.com/a/")},
    )
    dataset = load(bundle)
    assert dataset.site == "example.com"
    assert "site:" not in " ".join(dataset.notes)


def test_multi_host_spine_takes_majority_and_notes_the_count(tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b",
        {
            SPINE_FILE: spine_text(
                "https://a.example.com/", "https://a.example.com/x/", "https://b.example.com/"
            )
        },
    )
    dataset = load(bundle)
    assert dataset.site == "a.example.com"
    note = next(n for n in dataset.notes if n.startswith("site:"))
    assert "2 hostnames" in note
    assert "example.com" not in note


# --------------------------------------------------------------------------
# Normaliser injection and self-test
# --------------------------------------------------------------------------


def test_normalizer_injection_is_real(fixture_dataset: AuditDataset):
    def rehost(url: str) -> str:
        return url.replace("example.com", "example.org", 1)

    dataset = load(FIXTURE_BUNDLE, rehost)
    assert fixture_dataset.site == "example.com"
    assert dataset.site == "example.org"
    assert all(page.url.startswith("https://example.org/") for page in dataset.pages)


def test_self_test_rejects_non_idempotent_normalizer():
    def grow(url: str) -> str:
        return url + "x"

    with pytest.raises(NormalizerContractError) as info:
        load(FIXTURE_BUNDLE, grow)
    assert info.value.rule == "not-idempotent"
    assert isinstance(info.value, ScreamingFrogBundleError)


def test_self_test_rejects_non_url_returning_normalizer():
    def path_only(url: str) -> str:
        return "/relative"

    with pytest.raises(NormalizerContractError) as info:
        load(FIXTURE_BUNDLE, path_only)
    assert info.value.rule == "probe-not-http-url"


def test_self_test_rejects_raising_normalizer():
    def boom(url: str) -> str:
        raise RuntimeError(SENTINEL)

    with pytest.raises(NormalizerContractError) as info:
        load(FIXTURE_BUNDLE, boom)
    assert info.value.rule == "probe-raised"
    assert_clean(info.value)


def test_page_classifier_normalize_url_satisfies_the_protocol():
    # Imported here and only here: the adapter must never import it (ADR 0011 d.1).
    from src.modules.seo.page_classifier.url_rules import normalize_url

    dataset = load(FIXTURE_BUNDLE, normalize_url)
    assert dataset.site == "example.com"
    assert len(dataset.pages) == 11  # ?utm_source= row collapses into /blog/


# --------------------------------------------------------------------------
# Logging: counts and catalogue names only
# --------------------------------------------------------------------------


def test_log_payloads_carry_counts_and_catalogue_names_only(recorder: _Recorder):
    load(FIXTURE_BUNDLE)
    events = {msg for _, msg, _ in recorder.calls}
    assert {"sf_file_read", "sf_sources_absent", "sf_bundle_loaded", "sf_bundle_elapsed"} <= events
    assert all(level != "ERROR" for level, _, _ in recorder.calls)
    per_file = recorder.payload("sf_file_read")
    assert {"file", "rows_read", "urls_retained"} <= per_file.keys()
    summary = recorder.payload("sf_bundle_loaded")
    assert summary["coverage_measured"] == 15
    assert summary["coverage_not_measured"] == len(IssueId) - 15
    catalogue_names = {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources} | {SPINE_FILE}
    for _, _, extra in recorder.calls:
        for value in extra.values():
            values = value if isinstance(value, list) else [value]
            for item in values:
                assert_no_leak(str(item))
                if isinstance(item, str) and item.endswith(".csv"):
                    assert item in catalogue_names


def test_absent_sources_are_a_warning_not_an_error(recorder: _Recorder):
    load(FIXTURE_BUNDLE)
    levels = {level for level, msg, _ in recorder.calls if msg == "sf_sources_absent"}
    assert levels == {"WARNING"}


def test_emitted_records_never_carry_urls(sf_caplog: pytest.LogCaptureFixture, tmp_path: Path):
    bundle = write_bundle(
        tmp_path / "b",
        {
            SPINE_FILE: spine_text(HOME, SENTINEL),
            "h1_missing.csv": csv_text(["Address"], [SENTINEL]),
        },
    )
    load(bundle)
    with pytest.raises(ScreamingFrogBundleError) as info:
        load(write_bundle(tmp_path / "c", {SPINE_FILE: spine_text(SENTINEL + " ")}))
    assert sf_caplog.records, "capture is wired to the rankuno logger"
    assert_no_leak(sf_caplog.text)
    for record in sf_caplog.records:
        assert_no_leak(repr(record.__dict__))
        assert record.levelno < logging.ERROR
    assert_clean(info.value)
