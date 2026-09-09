"""Differential check: our Screaming Frog adapter vs the RAE archive (P0-7).

    python scripts/diff_against_rae.py

Opt-in and read-only. Skips cleanly (exit 0) when `Settings.rae_archive_dir`
is unset — the plan default and every developer machine without the archive.
When set, each subdirectory of that path is treated as one Screaming Frog
export ("crawl folder") and compared two ways:

* **Ours**: `load_screaming_frog_bundle` — the adapter under the gate.
* **RAE's**: a from-scratch reimplementation of `load_url_set`'s documented
  behaviour (plan §7): union whichever of Address/Source/Destination columns
  a file has, skip files under 100 bytes. No RAE code is copied (ADR 0011,
  "No RAE code is copied"); only its column and size rules are restated.

ADR 0011 scopes the archive as an oracle for **issue-set membership only** —
never scoring, never workbook layout. Four differences are deliberate and
documented in the plan, never "fixed": inlinks unioning Source+Destination
vs our Source-only, the 100-byte skip, the ten Security exports RAE never
wired (D3), and label spelling (moot here — comparisons are keyed by
`IssueId`, never by RAE's label strings). This script reports anything
outside those four as a regression; it proves nothing about scores or layout.

Not part of the quality gate (plan P0-7 row) — the 49-crawl archive lives
outside the repository and is exercised manually by an operator who has it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from src.core.config import get_settings
from src.modules.seo.contracts.audit import AuditDataset, IssueId
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE, RAE_LABELS
from src.modules.seo.contracts.url_normalizer import UrlNormalizer
from src.modules.seo.deliverables.screaming_frog_adapter import (
    ScreamingFrogBundleError,
    load_screaming_frog_bundle,
)
from src.modules.seo.page_classifier.url_rules import normalize_url

_RAE_MIN_FILE_BYTES = 100
"""RAE's `load_url_set` silently skips anything smaller (plan §7.2)."""

_RAE_URL_COLUMNS = frozenset({"address", "source", "destination"})
"""Column names RAE unions, case-insensitively, whichever are present."""

_INLINKS_SOURCE_ONLY = (
    "RAE unions Source + Destination on this file; the adapter reads Source only (plan §7.1)"
)
_HUNDRED_BYTE_SKIP = (
    "RAE skips a contributing file under 100 bytes; the adapter does not (plan §7.2)"
)
_UNWIRED_SECURITY = "RAE never wired this Security export (plan D3 / §7.3)"

UNWIRED_SECURITY_ISSUES: frozenset[IssueId] = frozenset(
    {
        IssueId.SECURITY_FORM_URL_INSECURE,
        IssueId.SECURITY_FORM_ON_HTTP_URL,
        IssueId.SECURITY_MISSING_HSTS_HEADER,
        IssueId.SECURITY_UNSAFE_CROSS_ORIGIN_LINKS,
        IssueId.SECURITY_PROTOCOL_RELATIVE_RESOURCE_LINKS,
        IssueId.SECURITY_MISSING_CONTENT_SECURITY_POLICY_HEADER,
        IssueId.SECURITY_MISSING_X_CONTENT_TYPE_OPTIONS_HEADER,
        IssueId.SECURITY_MISSING_X_FRAME_OPTIONS_HEADER,
        IssueId.SECURITY_MISSING_SECURE_REFERRER_POLICY_HEADER,
        IssueId.SECURITY_BAD_CONTENT_TYPE,
    }
)
"""The ten Security rows RAE's own issue table pointed at no CSV (D3); wiring
them here is this plan's fix, not RAE's, so RAE's oracle set is always empty
for these ten and a non-empty adapter set is expected, not a regression."""


@dataclass(frozen=True)
class OracleIssueResult:
    """One `IssueId`'s URL set as RAE's `load_url_set` would have read it.

    `has_destination_column` and `skipped_small_file` are per-issue, not
    per-URL: the plan's known differences are categorical (an entire issue
    reads differently), so that is the granularity a diff report needs.
    """

    urls: frozenset[str]
    has_destination_column: bool
    skipped_small_file: bool


def read_rae_style_issue(
    crawl_dir: Path, sf_sources: tuple[str, ...], normalize: UrlNormalizer
) -> OracleIssueResult:
    """Read one issue's URLs the way RAE's `load_url_set` documented reading it.

    Independent reimplementation, not a port: RAE's function is 20 lines
    behind a `pandas` import this repository does not take. This walks the
    same files with the standard library and the same two rules — union
    Address/Source/Destination, skip anything under 100 bytes.
    """
    urls: set[str] = set()
    has_destination = False
    skipped_small = False
    for name in sf_sources:
        path = crawl_dir / name
        if not path.is_file():
            continue
        if path.stat().st_size < _RAE_MIN_FILE_BYTES:
            skipped_small = True
            continue
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if header is None:
                    continue
                lowered = [cell.strip().lower() for cell in header]
                columns = [i for i, cell in enumerate(lowered) if cell in _RAE_URL_COLUMNS]
                if "destination" in lowered:
                    has_destination = True
                for row in reader:
                    for index in columns:
                        if index < len(row) and row[index]:
                            urls.add(normalize(row[index]))
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    return OracleIssueResult(frozenset(urls), has_destination, skipped_small)


@dataclass(frozen=True)
class IssueDifference:
    """An unexpected mismatch: not explained by any plan §7 known difference."""

    issue_id: IssueId
    our_only: frozenset[str]
    oracle_only: frozenset[str]


@dataclass(frozen=True)
class SuppressedDifference:
    """A mismatch that plan §7 documents as deliberate — reported, not counted."""

    issue_id: IssueId
    reason: str


@dataclass(frozen=True)
class CrawlDiffReport:
    """One crawl folder's differential result."""

    crawl: str
    differences: tuple[IssueDifference, ...] = ()
    known: tuple[SuppressedDifference, ...] = field(default=())


def diff_dataset_against_rae(
    dataset: AuditDataset, crawl_dir: Path, *, normalize: UrlNormalizer
) -> CrawlDiffReport:
    """Compare one loaded `AuditDataset` against the RAE-style read of its folder.

    Matched by `IssueId` throughout (never by RAE's label string), so label
    spelling fixes — the fourth known difference — never register at all.
    """
    differences: list[IssueDifference] = []
    known: list[SuppressedDifference] = []

    for spec in ISSUE_CATALOGUE:
        our_set = dataset.issues.get(spec.id, frozenset())

        if spec.id in UNWIRED_SECURITY_ISSUES:
            if our_set:
                known.append(SuppressedDifference(spec.id, _UNWIRED_SECURITY))
            continue

        if not spec.sf_sources:
            continue  # Neither side can measure this row today.

        oracle = read_rae_style_issue(crawl_dir, spec.sf_sources, normalize)
        our_only = our_set - oracle.urls
        oracle_only = oracle.urls - our_set

        if oracle.has_destination_column and oracle_only:
            known.append(SuppressedDifference(spec.id, _INLINKS_SOURCE_ONLY))
            oracle_only = frozenset()
        if oracle.skipped_small_file and our_only:
            known.append(SuppressedDifference(spec.id, _HUNDRED_BYTE_SKIP))
            our_only = frozenset()

        if our_only or oracle_only:
            differences.append(
                IssueDifference(spec.id, frozenset(our_only), frozenset(oracle_only))
            )

    return CrawlDiffReport(crawl_dir.name, tuple(differences), tuple(known))


def _print_report(report: CrawlDiffReport) -> None:
    print(f"\n{report.crawl}")
    if not report.differences:
        suffix = f" ({len(report.known)} known difference(s) suppressed)" if report.known else ""
        print(f"  OK - matches RAE issue membership{suffix}")
        return
    for diff in report.differences:
        label = RAE_LABELS[diff.issue_id].label
        print(f"  UNEXPECTED  {diff.issue_id.value}  ({label})")
        print(f"      ours only:  {len(diff.our_only):>6,}")
        print(f"      RAE only:   {len(diff.oracle_only):>6,}")


def main() -> int:
    """Run the differential check, or skip cleanly when opted out.

    Returns:
        0 when unset, the archive is empty, or every crawl folder matches
        (modulo known differences); 1 when an unexpected difference exists.
    """
    settings = get_settings()
    archive_dir = settings.rae_archive_dir
    if archive_dir is None:
        print("RAE_ARCHIVE_DIR not set; differential check skipped (opt-in, ADR 0011).")
        return 0
    if not archive_dir.is_dir():
        print(f"RAE_ARCHIVE_DIR is not a directory: {archive_dir}")
        return 0

    crawl_dirs = sorted(p for p in archive_dir.iterdir() if p.is_dir())
    if not crawl_dirs:
        print(f"No crawl folders found under {archive_dir}")
        return 0

    regressions = 0
    for crawl_dir in crawl_dirs:
        try:
            dataset = load_screaming_frog_bundle(crawl_dir, normalize=normalize_url)
        except ScreamingFrogBundleError as exc:
            print(f"\n{crawl_dir.name}\n  SKIPPED - adapter refused ({exc})")
            continue
        report = diff_dataset_against_rae(dataset, crawl_dir, normalize=normalize_url)
        _print_report(report)
        regressions += len(report.differences)

    print(f"\n{len(crawl_dirs)} crawl folder(s) checked, {regressions} unexpected difference(s).")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
