"""Turn a client's URL-pattern rulebook into themes on an `AuditDataset`'s pages.

Plan P1-1 through P1-4 (`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §5) under
ADR 0011. RAE's failure mode this file exists to close: a missing rulebook
silently gave every page `Low` priority, and a shorter pattern could shadow a
longer, more specific one depending on row order in the spreadsheet. Both are
made structurally impossible here: a missing file is a load-time error unless
the caller opts into `lenient=True`, and `classify()`'s precedence is computed
from rule shape (exact match, then pattern length), never from list position.

URL keys are looked up through an injected `UrlNormalizer`, the same contract
`screaming_frog_adapter.py` uses, so this module never imports
`page_classifier` (ADR 0011 d.1).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import Field, PrivateAttr, ValidationError, model_validator

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.contracts.audit import MAX_NOTE_LENGTH, AuditDataset, AuditPage
from src.modules.seo.contracts.url_normalizer import UrlNormalizer

__all__ = [
    "OTHERS_THEME",
    "PRIORITY_NOT_APPLICABLE",
    "RULEBOOK_SHEET_NAME",
    "Classification",
    "Rule",
    "Rulebook",
    "RulebookError",
    "RulebookMissingError",
    "RuleType",
    "apply_rulebook",
]

_logger = get_logger(__name__)

RULEBOOK_SHEET_NAME: Final[str] = "Rulebook"
_HEADER_SCAN_ROWS: Final[int] = 5
_HEADER_URL_PATTERN: Final[str] = "URL Pattern"
_HEADER_RULE_TYPE: Final[str] = "Rule Type"
_HEADER_THEME_1: Final[str] = "Theme 1"
_HEADER_THEME_2: Final[str] = "Theme 2"
_HEADER_BUSINESS_PRIORITY: Final[str] = "Business Priority"
_LANGUAGE_HEADER_VARIANTS: Final[frozenset[str]] = frozenset({"language", "languuage", "lang"})

_FALLBACK_RULE_TYPE_MARKERS: Final[frozenset[str]] = frozenset({"—", "-", "fallback"})
_FALLBACK_PATTERN_MARKER: Final[str] = "no match"

MAX_PATTERN_LENGTH: Final[int] = 500
"""Regex and literal patterns are operator-authored, not user-uploaded, but a
cap is still the cheapest guard against a pathological pattern (Step 5 audit,
plan §6 item 7). It is not a substitute for a timeout-capable regex engine,
which Phase 1 does not add."""

OTHERS_THEME: Final[str] = "Others"
PRIORITY_NOT_APPLICABLE: Final[str] = "N/A"
"""Unmatched URL, no fallback row: RAE's bug rendered this as `Low`, which a
client reads as "someone looked and it's fine". `N/A` says no one classified
it, which is the true state (plan P1-4)."""


class RuleType(StrEnum):
    """How a rule's `pattern` is compared against a page's URL path.

    Domain taxonomy enum, UPPER values (CLAUDE.md ruling 3), matching
    `contracts.catalogue.Severity`/`Priority` rather than `AuditSource`.
    """

    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    EXACT = "EXACT"
    REGEX = "REGEX"
    FALLBACK = "FALLBACK"


_RULE_TYPE_TEXT: Final[dict[str, RuleType]] = {
    "contains": RuleType.CONTAINS,
    "starts with": RuleType.STARTS_WITH,
    "startswith": RuleType.STARTS_WITH,
    "ends with": RuleType.ENDS_WITH,
    "endswith": RuleType.ENDS_WITH,
    "exact": RuleType.EXACT,
    "regex": RuleType.REGEX,
}


class RulebookError(ValueError):
    """A rulebook file, sheet or row cannot be turned into a `Rulebook`.

    One exception type for every load, format or rule-compilation failure,
    matching `ScreamingFrogBundleError`'s stance: there is no path on which a
    malformed rulebook is mistaken for an absent one.
    """


class RulebookMissingError(RulebookError):
    """The rulebook path does not exist and the caller did not pass `lenient=True`.

    ADR 0011 point 6: a missing rulebook on a client deliverable is an error
    by default. `lenient=True` is the explicit, auditable opt-out.
    """


class Rule(StrictModel):
    """One rulebook row: a pattern, how to match it, and the labels it assigns.

    Validated eagerly (`model_validator`) so a bad regex is a load-time
    failure, never a surprise mid-classification (plan P1-1).
    """

    rule_type: RuleType
    pattern: str = Field(max_length=MAX_PATTERN_LENGTH)
    theme_1: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    theme_2: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    language: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    business_priority: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    @model_validator(mode="after")
    def _pattern_matches_rule_type(self) -> Rule:
        """FALLBACK rows carry no pattern; every other row must, and REGEX must compile."""
        if self.rule_type is RuleType.FALLBACK:
            if self.pattern:
                msg = "a FALLBACK rule must have an empty pattern"
                raise ValueError(msg)
            return self
        if not self.pattern:
            msg = f"a {self.rule_type.value} rule must have a non-empty pattern"
            raise ValueError(msg)
        if self.rule_type is RuleType.REGEX:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                msg = f"invalid regex pattern {self.pattern!r}: {exc}"
                raise ValueError(msg) from exc
        return self


class Classification(StrictModel):
    """One page's rulebook verdict. Field names mirror `AuditPage` 1:1.

    `apply_rulebook` assigns these straight onto `AuditPage.theme_1` /
    `theme_2` / `language` / `business_priority`, no renaming step.
    """

    theme_1: str | None = None
    theme_2: str | None = None
    language: str | None = None
    business_priority: str | None = None


class Rulebook(StrictModel):
    """An ordered-irrelevant set of rules plus the metadata a caller needs to note.

    `source_path` and `empty_due_to_missing_file` exist so `apply_rulebook`
    can write a dataset note when `from_xlsx(..., lenient=True)` swallowed a
    missing file — `from_xlsx` itself has no dataset to write onto.
    """

    rules: tuple[Rule, ...] = ()
    source_path: str | None = None
    empty_due_to_missing_file: bool = False

    _compiled: dict[str, re.Pattern[str]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _validate_and_compile(self) -> Rulebook:
        """Enforce at most one fallback row and cache every REGEX pattern once.

        Compiling here, not in `classify()`, is what makes "compiled at load"
        true for a `Rulebook` built by hand in a test, not only one built by
        `from_xlsx`.
        """
        fallback_count = sum(1 for rule in self.rules if rule.rule_type is RuleType.FALLBACK)
        if fallback_count > 1:
            msg = f"a rulebook may have at most one FALLBACK rule; found {fallback_count}"
            raise ValueError(msg)
        for rule in self.rules:
            if rule.rule_type is RuleType.REGEX and rule.pattern not in self._compiled:
                self._compiled[rule.pattern] = re.compile(rule.pattern)
        return self

    @classmethod
    def from_xlsx(cls, path: Path, *, lenient: bool = False) -> Rulebook:
        """Load a `Rulebook` sheet from `path`.

        Args:
            path: Path to an `.xlsx` workbook containing a `Rulebook` sheet.
            lenient: When `True`, a missing `path` returns an empty rulebook
                with `empty_due_to_missing_file=True` instead of raising.
                Only a genuinely absent file is swallowed; a present-but-
                malformed workbook always raises (ADR 0011 point 6).

        Returns:
            A validated `Rulebook`.

        Raises:
            RulebookMissingError: `path` does not exist and `lenient` is `False`.
            RulebookError: `path` exists but is not a readable workbook, has no
                `Rulebook` sheet, has no header row in the first five rows, or a
                row names an unrecognised rule type or an invalid pattern.
        """
        if not path.is_file():
            if lenient:
                _logger.warning("rulebook_missing_lenient", extra={"path": str(path)})
                return cls(rules=(), source_path=str(path), empty_due_to_missing_file=True)
            raise RulebookMissingError(f"rulebook not found: {path}")

        try:
            book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - openpyxl raises several unrelated types
            raise RulebookError(f"{path}: not a readable workbook") from exc

        try:
            if RULEBOOK_SHEET_NAME not in book.sheetnames:
                raise RulebookError(f"{path}: no {RULEBOOK_SHEET_NAME!r} sheet")
            sheet = book[RULEBOOK_SHEET_NAME]
            columns, header_row = _find_header(sheet, path)
            rules = tuple(_parse_rows(sheet, columns, header_row, path))
        finally:
            book.close()

        _logger.info("rulebook_loaded", extra={"path": str(path), "rule_count": len(rules)})
        return cls(rules=rules, source_path=str(path))

    def classify(self, url: str) -> Classification:
        """Return the theme/language/priority verdict for one URL.

        All matching rules are collected before a winner is chosen, so the
        result never depends on `self.rules`' order (plan P1-3): `EXACT`
        matches win outright; otherwise the longest matching `pattern` wins,
        with pattern text and rule type as tie-breaks so the outcome is a
        total order even when two rules share a pattern.

        Args:
            url: An absolute or relative URL; only its path is matched.

        Returns:
            The winning rule's labels, the fallback row's labels when nothing
            matches and one is defined, or `Others` / `N/A` when nothing
            matches and no fallback row exists - never `Low`.
        """
        path = urlsplit(url).path
        fallback = next((rule for rule in self.rules if rule.rule_type is RuleType.FALLBACK), None)
        candidates = [
            rule
            for rule in self.rules
            if rule.rule_type is not RuleType.FALLBACK and self._matches(rule, path)
        ]
        if not candidates:
            if fallback is not None:
                return Classification(
                    theme_1=fallback.theme_1,
                    theme_2=fallback.theme_2,
                    language=fallback.language,
                    business_priority=fallback.business_priority,
                )
            return Classification(theme_1=OTHERS_THEME, business_priority=PRIORITY_NOT_APPLICABLE)

        exact = [rule for rule in candidates if rule.rule_type is RuleType.EXACT]
        pool = exact or candidates
        winner = max(pool, key=lambda rule: (len(rule.pattern), rule.pattern, rule.rule_type.value))
        return Classification(
            theme_1=winner.theme_1,
            theme_2=winner.theme_2,
            language=winner.language,
            business_priority=winner.business_priority,
        )

    def _matches(self, rule: Rule, path: str) -> bool:
        """Whether `rule` matches `path`. Case-insensitive except `REGEX`."""
        if rule.rule_type is RuleType.REGEX:
            return self._compiled[rule.pattern].search(path) is not None
        folded_path = path.casefold()
        folded_pattern = rule.pattern.casefold()
        if rule.rule_type is RuleType.CONTAINS:
            return folded_pattern in folded_path
        if rule.rule_type is RuleType.STARTS_WITH:
            return folded_path.startswith(folded_pattern)
        if rule.rule_type is RuleType.ENDS_WITH:
            return folded_path.endswith(folded_pattern)
        return folded_path == folded_pattern  # RuleType.EXACT


@dataclass(frozen=True)
class _Columns:
    """0-based column indices located in the header row. Optional ones may be `None`."""

    pattern: int
    rule_type: int
    theme_1: int | None
    theme_2: int | None
    language: int | None
    business_priority: int | None


def _find_header(sheet: Worksheet, path: Path) -> tuple[_Columns, int]:
    """Locate the header row within the first five rows and index its columns.

    `URL Pattern` anchors the search; every other column is optional except
    `Rule Type`, without which no row could be classified.
    """
    for row_index, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=_HEADER_SCAN_ROWS, values_only=True), start=1
    ):
        header = [str(cell).strip() if cell is not None else "" for cell in row]
        if _HEADER_URL_PATTERN not in header:
            continue
        if _HEADER_RULE_TYPE not in header:
            raise RulebookError(f"{path}: header row has no {_HEADER_RULE_TYPE!r} column")
        language_col = next(
            (i for i, cell in enumerate(header) if cell.casefold() in _LANGUAGE_HEADER_VARIANTS),
            None,
        )
        columns = _Columns(
            pattern=header.index(_HEADER_URL_PATTERN),
            rule_type=header.index(_HEADER_RULE_TYPE),
            theme_1=header.index(_HEADER_THEME_1) if _HEADER_THEME_1 in header else None,
            theme_2=header.index(_HEADER_THEME_2) if _HEADER_THEME_2 in header else None,
            language=language_col,
            business_priority=(
                header.index(_HEADER_BUSINESS_PRIORITY)
                if _HEADER_BUSINESS_PRIORITY in header
                else None
            ),
        )
        return columns, row_index
    raise RulebookError(
        f"{path}: no header row with a {_HEADER_URL_PATTERN!r} column in the first "
        f"{_HEADER_SCAN_ROWS} rows"
    )


def _cell_text(row: tuple[object, ...], index: int | None) -> str:
    """Stripped text of one cell, or `''` for a missing column or blank cell."""
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _parse_rows(sheet: Worksheet, columns: _Columns, header_row: int, path: Path) -> Iterator[Rule]:
    """Yield one `Rule` per data row, skipping blank rows entirely.

    A row is a fallback row when its rule-type cell is one of the documented
    markers or its pattern cell reads "No match" (plan P1-2), whichever the
    author used.
    """
    for row_number, row in enumerate(
        sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1
    ):
        pattern_text = _cell_text(row, columns.pattern)
        rule_type_text = _cell_text(row, columns.rule_type)
        if not pattern_text and not rule_type_text:
            continue

        theme_1 = _cell_text(row, columns.theme_1) or None
        theme_2 = _cell_text(row, columns.theme_2) or None
        language = _cell_text(row, columns.language) or None
        business_priority = _cell_text(row, columns.business_priority) or None

        is_fallback = (
            rule_type_text.casefold() in _FALLBACK_RULE_TYPE_MARKERS
            or pattern_text.casefold() == _FALLBACK_PATTERN_MARKER
        )
        if is_fallback:
            yield Rule(
                rule_type=RuleType.FALLBACK,
                pattern="",
                theme_1=theme_1,
                theme_2=theme_2,
                language=language,
                business_priority=business_priority,
            )
            continue

        rule_type = _RULE_TYPE_TEXT.get(rule_type_text.casefold())
        if rule_type is None:
            raise RulebookError(f"{path}: row {row_number}: unknown rule type {rule_type_text!r}")
        if not pattern_text:
            raise RulebookError(
                f"{path}: row {row_number}: {rule_type.value} rule has an empty pattern"
            )
        try:
            yield Rule(
                rule_type=rule_type,
                pattern=pattern_text,
                theme_1=theme_1,
                theme_2=theme_2,
                language=language,
                business_priority=business_priority,
            )
        except ValidationError as exc:
            raise RulebookError(f"{path}: row {row_number}: {exc}") from exc


def apply_rulebook(
    dataset: AuditDataset, rulebook: Rulebook, *, normalize: UrlNormalizer
) -> AuditDataset:
    """Return a new dataset whose pages carry the rulebook's themes.

    `normalize` is injected rather than imported (ADR 0011 d.1); it is the
    same function that keyed `dataset.pages` in the first place, so this is
    where a page's hostname is re-derived www.-stripped before its path is
    matched, keeping the lookup key spelled the same way everywhere in the
    pipeline (plan P1-4).

    Args:
        dataset: The dataset to classify. Never mutated.
        rulebook: The rulebook to classify against.
        normalize: URL normaliser satisfying `UrlNormalizer`.

    Returns:
        A new, fully-validated `AuditDataset` with `theme_1`, `theme_2`,
        `language` and `business_priority` set on every page. When `rulebook`
        is the empty result of `Rulebook.from_xlsx(..., lenient=True)`, a note
        recording that is appended.
    """
    new_pages = []
    for page in dataset.pages:
        result = rulebook.classify(normalize(page.url))
        new_pages.append(
            AuditPage(
                url=page.url,
                theme_1=result.theme_1,
                theme_2=result.theme_2,
                language=result.language,
                business_priority=result.business_priority,
            )
        )

    notes = dataset.notes
    if rulebook.empty_due_to_missing_file:
        notes = (
            *notes,
            f"rulebook: {rulebook.source_path} not found; lenient mode applied, "
            "all pages classified Others/N/A",
        )

    _logger.info(
        "rulebook_applied",
        extra={"pages": len(new_pages), "rule_count": len(rulebook.rules)},
    )
    return AuditDataset(
        source=dataset.source,
        site=dataset.site,
        produced_at=dataset.produced_at,
        pages=tuple(new_pages),
        issues=dataset.issues,
        coverage=dataset.coverage,
        links=dataset.links,
        notes=notes,
    )
