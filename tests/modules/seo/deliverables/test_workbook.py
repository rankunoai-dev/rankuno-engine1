"""Tests for the workbook generator (Phase 2b, ADR 0011).

Formula injection is the load-bearing concern here: `test_no_cell_anywhere_is_a_formula`
is the whole-workbook proof that `_safe_cell` is applied on every sheet, not
just the ones exercised by other tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
import pytest
from src.core.config import get_settings, reset_settings_cache
from src.modules.seo.contracts.audit import AuditDataset, AuditPage, AuditSource, Coverage
from src.modules.seo.contracts.issue_ids import IssueId
from src.modules.seo.deliverables.scoring import score_dataset
from src.modules.seo.deliverables.workbook import (
    MAX_PAGES_PER_WORKBOOK,
    SHEET_ISSUES,
    SHEET_NOTES,
    SHEET_OVERVIEW,
    SHEET_PAGES,
    WorkbookBuildError,
    _safe_cell,
    build_workbook,
)

PRODUCED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def full_coverage() -> dict[IssueId, Coverage]:
    return dict.fromkeys(IssueId, Coverage.NOT_MEASURED)


def make_dataset(**overrides: object) -> AuditDataset:
    base: dict[str, object] = {
        "source": AuditSource.ENGINE,
        "site": "example.com",
        "produced_at": PRODUCED_AT,
        "pages": (AuditPage(url="https://example.com/"),),
        "issues": {},
        "coverage": full_coverage(),
        "notes": (),
    }
    base.update(overrides)
    return AuditDataset.model_validate(base)


# -- Formula injection -------------------------------------------------------


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_safe_cell_neutralises_every_trigger_character(trigger: str) -> None:
    """`_safe_cell` prefixes every OWASP trigger character with a quote."""
    payload = f"{trigger}cmd|'/C calc'!A1"
    assert _safe_cell(payload) == f"'{payload}"


def test_safe_cell_leaves_ordinary_strings_and_non_strings_alone() -> None:
    assert _safe_cell("ordinary title") == "ordinary title"
    assert _safe_cell(42) == 42
    assert _safe_cell(None) is None


def test_malicious_page_url_is_not_written_as_a_formula(tmp_path: Path) -> None:
    """A page whose `url` field itself starts with '=' stays a string cell.

    `AuditPage.url` has no URL-format validator (`contracts/audit.py` only
    bounds its length), so a malformed or adversarial value starting with a
    trigger character is representable and must still be neutralised before
    it reaches the Pages sheet - this proves the exact path
    `build_workbook` -> `_write_pages` -> openpyxl does that.
    """
    malicious_url = '=HYPERLINK("http://evil","click")'
    dataset = make_dataset(pages=(AuditPage(url=malicious_url),))
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    pages_sheet = book[SHEET_PAGES]
    url_cell = next(
        cell
        for row in pages_sheet.iter_rows(min_row=2)
        for cell in row
        if isinstance(cell.value, str) and "evil" in cell.value
    )
    assert url_cell.data_type != "f"
    assert url_cell.value == f"'{malicious_url}"


def test_no_cell_anywhere_is_a_formula(tmp_path: Path) -> None:
    """Whole-workbook proof: zero live-formula cells across all four sheets.

    Every text field a dataset can carry (URL, theme, note) is seeded with a
    formula-trigger payload, so this is not just "the happy path has no
    formulas" - it is "no formula survives even when every field tries to be one".
    """
    trigger_text = "=SUM(A1:A9)"
    pages = (
        AuditPage(
            url="https://example.com/a",
            theme_1=trigger_text,
            theme_2="+2+2",
            language="-en",
            business_priority="@High",
        ),
    )
    coverage = full_coverage()
    coverage[IssueId.H1_MISSING] = Coverage.MEASURED
    dataset = make_dataset(
        pages=pages,
        issues={IssueId.H1_MISSING: frozenset({"https://example.com/a"})},
        coverage=coverage,
        notes=(trigger_text,),
    )
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    formula_cells = [
        (sheet.title, cell.coordinate, cell.value)
        for sheet in book.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    ]
    assert formula_cells == []
    assert set(book.sheetnames) == {SHEET_OVERVIEW, SHEET_ISSUES, SHEET_PAGES, SHEET_NOTES}


# -- Sheet content -------------------------------------------------------


def test_overview_sheet_has_no_aggregate_score_column(tmp_path: Path) -> None:
    """The Overview sheet is per-category only; ADR 0011 D2 as a workbook-level check."""
    dataset = make_dataset()
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    overview = book[SHEET_OVERVIEW]
    header_row = next(overview.iter_rows(min_row=3, max_row=3, values_only=True))
    assert header_row == ("Category", "Penalty Total", "Issues Measured", "Issues Not Measured")
    banned = ("score", "total site", "overall")
    for row in overview.iter_rows(min_row=4, values_only=True):
        for value in row:
            if isinstance(value, str):
                assert not any(b in value.lower() for b in banned)


def test_pages_sheet_is_sorted_and_carries_themes(tmp_path: Path) -> None:
    pages = (
        AuditPage(url="https://example.com/b", theme_1="Services"),
        AuditPage(url="https://example.com/a", theme_1="Blog"),
    )
    dataset = make_dataset(pages=pages)
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    rows = list(book[SHEET_PAGES].iter_rows(min_row=2, values_only=True))
    assert [r[0] for r in rows] == ["https://example.com/a", "https://example.com/b"]
    assert rows[0][1] == "Blog"
    assert rows[1][1] == "Services"


def test_issues_sheet_has_one_row_per_catalogue_entry_plus_header(tmp_path: Path) -> None:
    from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE

    dataset = make_dataset()
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    rows = list(book[SHEET_ISSUES].iter_rows(values_only=True))
    assert len(rows) == len(ISSUE_CATALOGUE) + 1  # header + one row per catalogue entry


def test_notes_sheet_carries_dataset_notes(tmp_path: Path) -> None:
    dataset = make_dataset(notes=("rulebook: missing.xlsx not found; lenient mode applied",))
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    book = openpyxl.load_workbook(path)
    values = [v for row in book[SHEET_NOTES].iter_rows(values_only=True) for v in row if v]
    assert any("lenient mode applied" in str(v) for v in values)


# -- File naming and location -------------------------------------------------


def test_output_path_uses_site_and_produced_at(tmp_path: Path) -> None:
    dataset = make_dataset()
    scoring = score_dataset(dataset)

    path = build_workbook(dataset, scoring, output_dir=tmp_path)

    assert path == tmp_path / "example.com-20260909T120000Z.xlsx"
    assert path.is_file()


def test_default_output_dir_comes_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `output_dir=`, `build_workbook` writes under `Settings.deliverables_output_dir`."""
    monkeypatch.setenv("DELIVERABLES_OUTPUT_DIR", str(tmp_path / "from-settings"))
    reset_settings_cache()
    try:
        assert get_settings().deliverables_output_dir == tmp_path / "from-settings"

        dataset = make_dataset()
        scoring = score_dataset(dataset)
        path = build_workbook(dataset, scoring)

        assert path.parent == tmp_path / "from-settings"
    finally:
        reset_settings_cache()


# -- The 500,000-page cap -----------------------------------------------------


class _OversizedTuple(tuple[AuditPage, ...]):
    """A 3-element tuple that *reports* a length past the cap.

    `build_workbook` only calls `len(dataset.pages)` before it writes
    anything, so this proves the cap is enforced without the test having to
    construct and validate 500,001 real `AuditPage` models.
    """

    def __len__(self) -> int:  # pragma: no cover - trivial override
        return MAX_PAGES_PER_WORKBOOK + 1


def test_dataset_over_the_page_cap_raises_instead_of_truncating(tmp_path: Path) -> None:
    dataset = make_dataset()
    scoring = score_dataset(dataset)
    oversized = dataset.model_copy(update={"pages": _OversizedTuple(dataset.pages)})

    with pytest.raises(WorkbookBuildError, match="exceeds MAX_PAGES_PER_WORKBOOK"):
        build_workbook(oversized, scoring, output_dir=tmp_path)


class _FakeSheet:
    def append(self, _row: object) -> None:
        pass


class _FakeWorkbookThatFailsToSave:
    """A stand-in for `openpyxl.Workbook` whose `save()` always raises.

    Patching the real class's `save` mid-write instead left its generator-based
    writer in a broken state and produced unrelated `PytestUnraisableExceptionWarning`
    noise from `lxml`'s cleanup on garbage collection - not a failure of anything
    this module does. Replacing the whole collaborator avoids ever starting a
    real write-only XML stream.
    """

    def __init__(self, write_only: bool = True) -> None:
        del write_only

    def create_sheet(self, _title: str) -> _FakeSheet:
        return _FakeSheet()

    def save(self, _path: object) -> None:
        raise OSError("disk full")


def test_write_failure_raises_workbook_build_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `OSError` from the underlying write is wrapped, not left to propagate raw.

    Matches `RulebookError` / `ScreamingFrogBundleError`'s stance: one typed
    exception for every failure in this module, never a bare `OSError`.
    """
    import src.modules.seo.deliverables.workbook as workbook_module

    monkeypatch.setattr(workbook_module, "Workbook", _FakeWorkbookThatFailsToSave)

    dataset = make_dataset()
    scoring = score_dataset(dataset)

    with pytest.raises(WorkbookBuildError, match="failed to write workbook"):
        build_workbook(dataset, scoring, output_dir=tmp_path)
