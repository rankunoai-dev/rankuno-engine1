"""Draft label worksheets — a starting point for human labelling, not labels.

`tests/fixtures/corpus/README.md` forbids machine-generated labels, for a reason
that is easy to state and easy to forget under deadline: **scoring the engine
against its own output measures nothing.** A corpus seeded from predictions would
report high accuracy on exactly the pages the engine already handles, and would
be silent about the ones it does not.

That rule is enforced here mechanically rather than by convention. A draft row
carries the engine's suggestion *and* an empty `expected_*` pair, and
`load_reviewed_csv` admits a row into the corpus only when a human has filled the
expected columns in and marked it reviewed. An unreviewed worksheet is inert: it
can sit in the repository indefinitely without ever influencing a measurement.

The suggestion columns exist because correcting is faster than labelling cold —
a reviewer reading `PRODUCT_DETAIL_PAGE, 0.42, [sitemap]` can accept or overrule
in a second. They are a labour saving, and they are also the most likely way this
whole apparatus could be corrupted, which is why the gate is a hard one.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import Field

from src.core.errors import ConfigurationError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.corpus import (
    CorpusEntry,
    CorpusSite,
    SiteArchetype,
)
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
)

__all__ = [
    "DRAFT_COLUMNS",
    "REVIEWED_VALUES",
    "DraftRow",
    "ReviewStats",
    "draft_rows_from_profiles",
    "load_reviewed_csv",
    "write_draft_csv",
]

_logger = get_logger("modules.seo.corpus_drafts")

DRAFT_COLUMNS = (
    "url",
    "suggested_level",
    "suggested_page_type",
    "confidence",
    "signals",
    "reviewed",
    "expected_level",
    "expected_page_type",
    "notes",
)
"""Worksheet columns, in review order.

Suggestions come first so a reviewer reads the engine's answer and its evidence
before committing to their own, and `expected_*` sit after `reviewed` so filling
them in feels like the deliberate act it is."""

REVIEWED_VALUES = frozenset({"y", "yes", "true", "1", "ok", "done"})
"""Values accepted as "a human has checked this row". Deliberately permissive
about spelling and strict about absence: anything else means unreviewed."""


class DraftRow(StrictModel):
    """One worksheet row: what the engine thinks, and space for what is true.

    Attributes:
        url: The page.
        suggested_level: Engine's hierarchy level. **A suggestion, not a label.**
        suggested_page_type: Engine's page type. Likewise.
        confidence: Engine's confidence. Low values mark the rows worth a
            reviewer's attention first.
        signals: Which signals fired, for a reviewer deciding whether to trust
            the suggestion.
        reviewed: Set by a human. Empty means this row is inert.
        expected_level: The reviewer's answer. Empty until reviewed.
        expected_page_type: The reviewer's answer. Empty until reviewed.
        notes: Reviewer's reasoning, most valuable on the hard cases.
    """

    url: str = Field(min_length=1)
    suggested_level: str = ""
    suggested_page_type: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: str = ""
    reviewed: str = ""
    expected_level: str = ""
    expected_page_type: str = ""
    notes: str = ""

    @property
    def is_reviewed(self) -> bool:
        """Whether a human has signed off on this row."""
        return self.reviewed.strip().lower() in REVIEWED_VALUES

    def to_entry(self) -> CorpusEntry | None:
        """Convert to a corpus entry, or `None` if not usable as ground truth.

        Returns `None` unless the row is marked reviewed *and* both expected
        columns hold valid taxonomy values. A row marked reviewed with empty
        expectations is a reviewer who ticked the box without doing the work,
        and admitting it would be worse than dropping it silently — so it is
        dropped loudly, via `ReviewStats`.
        """
        if not self.is_reviewed:
            return None
        try:
            level = HierarchyLevel(self.expected_level.strip().upper())
            page_type = PrimaryPageType(self.expected_page_type.strip().upper())
        except ValueError:
            return None
        return CorpusEntry(
            url=self.url,
            expected_level=level,
            expected_page_type=page_type,
            source="human review of a draft worksheet",
            notes=self.notes[:500],
        )


class ReviewStats(StrictModel):
    """How much of a worksheet has actually been reviewed.

    Attributes:
        total_rows: Rows in the file.
        reviewed: Rows marked reviewed.
        admitted: Rows that became corpus entries.
        marked_but_unusable: Rows marked reviewed whose expected values were
            missing or invalid. Non-zero means someone ticked boxes without
            filling the answer in, and the file needs going back over.
    """

    total_rows: int = Field(default=0, ge=0)
    reviewed: int = Field(default=0, ge=0)
    admitted: int = Field(default=0, ge=0)
    marked_but_unusable: int = Field(default=0, ge=0)

    @property
    def progress(self) -> float:
        """Share of rows admitted into the corpus."""
        return self.admitted / self.total_rows if self.total_rows else 0.0

    def summary_line(self) -> str:
        """One-line review status."""
        warning = (
            f"  WARNING: {self.marked_but_unusable} rows marked reviewed but unusable"
            if self.marked_but_unusable
            else ""
        )
        return (
            f"{self.admitted}/{self.total_rows} rows admitted "
            f"({self.progress:.0%} reviewed){warning}"
        )


def draft_rows_from_profiles(
    profiles: Sequence[FullPageIntelligenceProfile],
    *,
    hardest_first: bool = True,
) -> tuple[DraftRow, ...]:
    """Turn classification output into worksheet rows.

    Args:
        profiles: Classified pages from a crawl.
        hardest_first: Order by ascending confidence. A reviewer's time is best
            spent where the engine is least sure — high-confidence rows are
            usually a formality, and burying the hard ones at the bottom of a
            300-row file means they never get looked at.

    Returns:
        Worksheet rows with empty expectations.
    """
    ordered = (
        sorted(profiles, key=lambda item: item.final_confidence_score)
        if hardest_first
        else list(profiles)
    )
    return tuple(
        DraftRow(
            url=profile.url,
            suggested_level=profile.hierarchy_level.value,
            suggested_page_type=profile.primary_page_type.value,
            confidence=round(profile.final_confidence_score, 3),
            signals="|".join(sorted({s.source.value for s in profile.signals_evaluated})),
        )
        for profile in ordered
    )


def write_draft_csv(rows: Iterable[DraftRow], path: Path | str) -> int:
    """Write a worksheet to disk.

    Args:
        rows: Worksheet rows.
        path: Destination CSV.

    Returns:
        Rows written.

    Raises:
        ConfigurationError: If the file cannot be written.
    """
    destination = Path(path)
    materialised = list(rows)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(DRAFT_COLUMNS))
            writer.writeheader()
            for row in materialised:
                writer.writerow(row.model_dump(mode="json"))
    except OSError as exc:
        msg = f"Draft worksheet '{destination}' could not be written: {exc}"
        raise ConfigurationError(msg) from exc

    _logger.info(
        "draft_worksheet_written", extra={"path": str(destination), "rows": len(materialised)}
    )
    return len(materialised)


def load_reviewed_csv(
    path: Path | str,
    *,
    name: str,
    base_url: str,
    archetype: SiteArchetype,
    labelled_by: str = "",
) -> tuple[CorpusSite, ReviewStats]:
    """Load only the human-reviewed rows of a worksheet into a corpus site.

    Unreviewed rows are ignored entirely, which is what keeps a draft file inert
    until someone has actually done the work on it.

    Args:
        path: Worksheet CSV.
        name: Site identifier for the resulting corpus site.
        base_url: Site root.
        archetype: Which archetype the site belongs to.
        labelled_by: Who reviewed it. Recorded as provenance.

    Returns:
        The corpus site built from reviewed rows, and the review statistics.

    Raises:
        ConfigurationError: If the file is missing, unreadable, or lacks the
            expected columns.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Draft worksheet '{source}' could not be read: {exc}"
        raise ConfigurationError(msg) from exc

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or "url" not in reader.fieldnames:
        msg = f"Draft worksheet '{source}' has no 'url' column."
        raise ConfigurationError(msg)

    entries: list[CorpusEntry] = []
    total = reviewed = unusable = 0

    for raw in reader:
        if not (raw.get("url") or "").strip():
            continue
        total += 1
        row = DraftRow(
            url=(raw.get("url") or "").strip(),
            suggested_level=(raw.get("suggested_level") or "").strip(),
            suggested_page_type=(raw.get("suggested_page_type") or "").strip(),
            confidence=_as_float(raw.get("confidence")),
            signals=(raw.get("signals") or "").strip(),
            reviewed=(raw.get("reviewed") or "").strip(),
            expected_level=(raw.get("expected_level") or "").strip(),
            expected_page_type=(raw.get("expected_page_type") or "").strip(),
            notes=(raw.get("notes") or "").strip(),
        )
        if not row.is_reviewed:
            continue

        reviewed += 1
        entry = row.to_entry()
        if entry is None:
            unusable += 1
            _logger.warning("draft_row_marked_but_unusable", extra={"url": row.url})
            continue
        entries.append(entry)

    stats = ReviewStats(
        total_rows=total,
        reviewed=reviewed,
        admitted=len(entries),
        marked_but_unusable=unusable,
    )
    site = CorpusSite(
        name=name,
        base_url=base_url,
        archetype=archetype,
        labelled_by=labelled_by or "unrecorded reviewer",
        entries=tuple(entries),
        notes=f"Admitted from worksheet '{source.name}'. {stats.summary_line()}",
    )
    _logger.info(
        "draft_worksheet_loaded", extra={"path": str(source), "summary": stats.summary_line()}
    )
    return site, stats


def _as_float(value: str | None) -> float:
    """Parse a confidence cell, tolerating blanks and junk."""
    try:
        parsed = float((value or "0").strip() or 0.0)
    except ValueError:
        return 0.0
    return min(max(parsed, 0.0), 1.0)
