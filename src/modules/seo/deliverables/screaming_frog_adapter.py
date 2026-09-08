"""Turn a Screaming Frog export into an `AuditDataset(source="screaming_frog")`.

Plan P0-3 (`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4) under ADR 0011.
Screaming Frog is an input *format* here, never a dependency: this module opens
CSV files by catalogue name and nothing else. Three stances the RAE reader got
wrong and this one does not:

* **Absent is not empty.** A missing file is `NOT_MEASURED`; a header-only file
  is `MEASURED` with no members. Both are values a workbook must show.
* **Nothing is skipped by size.** RAE dropped files under 100 bytes and lost
  real one-row findings. A `form_url_insecure.csv` with one row is 87 bytes.
* **Nothing fails silently.** Every read, parse, encoding or guard failure is
  one typed `ScreamingFrogBundleError`; there is no path to "no issues".

Edge-list files (`*_inlinks.csv`, the form and cross-origin reports) contribute
their `Source` column only. The broken *target* already appears in the matching
Response Codes issue; unioning `Destination` in would double-count it (plan §7).

URL keys come from an injected `UrlNormalizer` so this module never imports
`page_classifier` (ADR 0011 d.1) and both adapters can be handed the same
function. Logs carry counts and catalogue filenames; never a URL or cell value.
"""

from __future__ import annotations

import csv
import time
import zipfile
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.contracts.audit import (
    MAX_URL_LENGTH,
    AuditDataset,
    AuditPage,
    AuditSource,
    Coverage,
    IssueId,
)
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.contracts.url_normalizer import UrlNormalizer
from src.modules.seo.deliverables._bundle import (
    MAX_BUNDLE_UNCOMPRESSED_BYTES,
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    MAX_ZIP_MEMBERS,
    Bundle,
    ScreamingFrogBundleError,
    open_bundle,
)

__all__ = [
    "LINKS_NOT_RETAINED_NOTE",
    "MAX_BUNDLE_UNCOMPRESSED_BYTES",
    "MAX_COLUMNS",
    "MAX_LINE_CHARS",
    "MAX_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_ROWS_PER_FILE",
    "MAX_ZIP_MEMBERS",
    "NORMALIZER_PROBE",
    "SPINE_FILE",
    "NormalizerContractError",
    "ScreamingFrogBundleError",
    "SfUrlCell",
    "load_screaming_frog_bundle",
]

_logger = get_logger(__name__)

SPINE_FILE: Final[str] = "internal_all.csv"
"""Every internal URL the crawl saw; the page spine and the source of `site`."""

MAX_ROWS_PER_FILE: Final[int] = 20_000_000
MAX_LINE_CHARS: Final[int] = 1_048_576
MAX_COLUMNS: Final[int] = 1_024

NORMALIZER_PROBE: Final[str] = "HTTP://WWW.Example.com/A/../b/?utm_source=x&z=1"
"""Fed to the injected normaliser on entry; the result must be http(s) and idempotent."""

LINKS_NOT_RETAINED_NOTE: Final[str] = (
    "links: edges not retained by the screaming_frog adapter (ADR 0011 D4 deferred)"
)

_URL_COLUMNS: Final[tuple[str, ...]] = ("Address", "Source")
_HTTP_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
_WWW: Final[str] = "www."

# Exceptions a streamed read can surface mid-iteration. `ScreamingFrogBundleError`
# is a `ValueError` but not one of these, so a guard refusal passes through untouched.
_READ_FAILURES: Final[tuple[type[BaseException], ...]] = (
    csv.Error,
    UnicodeDecodeError,
    OSError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    zlib.error,
    RuntimeError,
    NotImplementedError,
)


class NormalizerContractError(ScreamingFrogBundleError):
    """The injected normaliser is not one this adapter can key a dataset with."""


class SfUrlCell(StrictModel):
    """One URL cell as Screaming Frog wrote it, and again after normalisation.

    The scheme check is what makes deferring formula escaping to Phase 2 safe
    for URL fields: a value starting with `=` or `@` cannot pass. Control
    characters are rejected here because Python's `csv` does not raise on NUL.
    """

    value: str = Field(min_length=1, max_length=MAX_URL_LENGTH)

    @field_validator("value")
    @classmethod
    def _is_absolute_http_url(cls, value: str) -> str:
        if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            msg = "whitespace or control character in URL cell"
            raise ValueError(msg)
        parts = urlsplit(value)
        if parts.scheme.lower() not in _HTTP_SCHEMES or not parts.netloc:
            msg = "URL cell must be absolute http(s) with a host"
            raise ValueError(msg)
        return value


@dataclass(frozen=True)
class _FileStats:
    rows_read: int
    urls_retained: int
    rows_skipped: int


def _bounded_lines(stream: IO[str], filename: str) -> Iterator[str]:
    """Refuse a line longer than `MAX_LINE_CHARS` before `csv` buffers it."""
    for line in stream:
        if len(line) > MAX_LINE_CHARS:
            raise ScreamingFrogBundleError(filename, "line-length-cap")
        yield line


def _url_column(header: list[str], filename: str) -> int:
    """Index of the URL column: `Address` on tables, `Source` on edge lists."""
    if len(header) > MAX_COLUMNS:
        raise ScreamingFrogBundleError(filename, "column-count-cap", f"{len(header)}")
    for column in _URL_COLUMNS:
        if column in header:
            return header.index(column)
    raise ScreamingFrogBundleError(filename, "no-url-column")


def _cell(raw: str, filename: str, row: int, normalize: UrlNormalizer) -> str:
    """Validate a raw cell, normalise it, validate the result."""
    try:
        SfUrlCell(value=raw)
    except ValueError as exc:
        raise ScreamingFrogBundleError(filename, "invalid-url-cell", f"row {row}") from exc
    try:
        key = normalize(raw)
    except Exception as exc:  # noqa: BLE001 - re-raised typed with context, never swallowed
        raise ScreamingFrogBundleError(filename, "normalizer-raised", f"row {row}") from exc
    try:
        SfUrlCell(value=key)
    except ValueError as exc:
        raise ScreamingFrogBundleError(filename, "invalid-normalised-url", f"row {row}") from exc
    return key


def _read_urls(
    stream: IO[str], filename: str, normalize: UrlNormalizer
) -> tuple[list[str], _FileStats]:
    """Stream one file and return its normalised URL column in file order.

    A list, not a set, so the spine can keep first-occurrence order; callers
    that want membership build the set. Memory is bounded by the number of
    URLs, not the file: the other fourteen columns of an inlinks row are
    dropped as each row is read.
    """
    reader = csv.reader(_bounded_lines(stream, filename))
    try:
        header = next(reader, None)
        if header is None:
            raise ScreamingFrogBundleError(filename, "no-header")
        column = _url_column(header, filename)
        urls: list[str] = []
        skipped = 0
        rows = 0
        for row_number, row in enumerate(reader, start=2):
            rows += 1
            if rows > MAX_ROWS_PER_FILE:
                raise ScreamingFrogBundleError(filename, "row-count-cap")
            if len(row) <= column or not row[column]:
                skipped += 1
                continue
            urls.append(_cell(row[column], filename, row_number, normalize))
    except _READ_FAILURES as exc:
        raise ScreamingFrogBundleError(filename, "read-failed") from exc
    return urls, _FileStats(rows_read=rows, urls_retained=len(urls), rows_skipped=skipped)


def _read_named(bundle: Bundle, name: str, normalize: UrlNormalizer) -> list[str] | None:
    """`None` when the bundle lacks the file; that is the NOT_MEASURED signal."""
    stream = bundle.open_text(name)
    if stream is None:
        return None
    with stream:
        urls, stats = _read_urls(stream, name, normalize)
    _logger.info(
        "sf_file_read",
        extra={
            "file": name,
            "rows_read": stats.rows_read,
            "urls_retained": stats.urls_retained,
            "rows_skipped": stats.rows_skipped,
        },
    )
    return urls


def _self_test(normalize: UrlNormalizer) -> None:
    """Refuse a normaliser that is not http(s)-preserving and idempotent."""
    try:
        once = normalize(NORMALIZER_PROBE)
        twice = normalize(once)
    except Exception as exc:  # noqa: BLE001 - converted to the typed contract error
        raise NormalizerContractError("<normalizer>", "probe-raised") from exc
    parts = urlsplit(once)
    if parts.scheme.lower() not in _HTTP_SCHEMES or not parts.netloc:
        raise NormalizerContractError("<normalizer>", "probe-not-http-url")
    if once != twice:
        raise NormalizerContractError("<normalizer>", "not-idempotent")


def _derive_site(spine: Iterable[str]) -> tuple[str, int]:
    """Majority hostname of the spine, `www.` and port stripped.

    Stripping `www.` binds the engine adapter (P0-4) and the rulebook lookup
    (P1-4) to the same spelling, which is the whole point of `site`.
    """
    hosts: Counter[str] = Counter()
    for url in spine:
        host = urlsplit(url).hostname
        if host:
            hosts[host.removeprefix(_WWW)] += 1
    if not hosts:
        raise ScreamingFrogBundleError(SPINE_FILE, "no-hostname-in-spine")
    site, _ = hosts.most_common(1)[0]
    return site, len(hosts)


def _build(bundle: Bundle, normalize: UrlNormalizer, produced_at: datetime) -> AuditDataset:
    spine_rows = _read_named(bundle, SPINE_FILE, normalize)
    if spine_rows is None:
        raise ScreamingFrogBundleError(SPINE_FILE, "spine-absent")
    spine = dict.fromkeys(spine_rows)
    if not spine:
        raise ScreamingFrogBundleError(SPINE_FILE, "spine-empty")
    site, host_count = _derive_site(spine)

    issues: dict[IssueId, frozenset[str]] = {}
    coverage: dict[IssueId, Coverage] = {}
    absent: list[str] = []
    for spec in ISSUE_CATALOGUE:
        members: set[str] = set()
        measured = False
        for name in spec.sf_sources:
            urls = _read_named(bundle, name, normalize)
            if urls is None:
                absent.append(name)
                continue
            measured = True
            members.update(urls)
        unknown = len(members - spine.keys())
        if unknown:
            raise ScreamingFrogBundleError(
                spec.sf_sources[0], "url-not-in-spine", f"{unknown} URL(s), {spec.id.value}"
            )
        coverage[spec.id] = Coverage.MEASURED if measured else Coverage.NOT_MEASURED
        issues[spec.id] = frozenset(members)

    if absent:
        _logger.warning("sf_sources_absent", extra={"files": absent, "count": len(absent)})
    notes = [LINKS_NOT_RETAINED_NOTE]
    if host_count > 1:
        notes.append(f"site: {host_count} hostnames in spine; majority chosen")
    measured_count = sum(1 for value in coverage.values() if value is Coverage.MEASURED)
    _logger.info(
        "sf_bundle_loaded",
        extra={
            "pages": len(spine),
            "duplicates_dropped": len(spine_rows) - len(spine),
            "coverage_measured": measured_count,
            "coverage_not_measured": len(coverage) - measured_count,
        },
    )
    return AuditDataset(
        source=AuditSource.SCREAMING_FROG,
        site=site,
        produced_at=produced_at,
        pages=tuple(AuditPage(url=url) for url in spine),
        issues=issues,
        coverage=coverage,
        notes=tuple(notes),
    )


def load_screaming_frog_bundle(
    bundle: Path, *, normalize: UrlNormalizer, produced_at: datetime | None = None
) -> AuditDataset:
    """Read a Screaming Frog export directory or zip into an `AuditDataset`.

    Both adapters must be handed the same `normalize` function (in production,
    `page_classifier.url_rules.normalize_url`) so their datasets share URL keys
    and spell `site` identically. It is a parameter, not an import, because
    this package may not depend on `page_classifier` (ADR 0011 d.1).

    Args:
        bundle: Path to an export directory, or to a zip of one. Dispatch is
            on content (directory, or `PK` magic), never on extension.
        normalize: URL normaliser satisfying `UrlNormalizer`; self-tested on
            entry with `NORMALIZER_PROBE`.
        produced_at: Timestamp for the dataset; defaults to now, UTC.

    Returns:
        A validated dataset with every `IssueId` covered and `links` empty.

    Raises:
        ScreamingFrogBundleError: Any guard refusal, read, parse or encoding
            failure, a missing or empty spine, or an issue URL outside it.
        NormalizerContractError: `normalize` fails its self-test.
    """
    started = time.perf_counter()
    _self_test(normalize)
    handle = open_bundle(bundle)
    try:
        dataset = _build(handle, normalize, produced_at or datetime.now(UTC))
    finally:
        handle.close()
    _logger.info("sf_bundle_elapsed", extra={"elapsed_s": round(time.perf_counter() - started, 3)})
    return dataset
