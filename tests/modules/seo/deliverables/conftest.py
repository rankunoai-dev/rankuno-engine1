"""Fixtures shared by the masterfile service tests.

`sf_export` is the one that matters: before build-log 0116 every service test
pointed at an empty directory, which is why thirteen broken services shipped
green. A test in this package that wants to know what a service *produces*
takes `sf_export`; a test that wants the not-measured path takes
`empty_export`.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from pathlib import Path

import openpyxl
import pytest
from tests.modules.seo.deliverables import sf_export as fixture_export

__all__ = [
    "detail_table",
    "empty_export",
    "first_cell",
    "sf_export",
    "sheet_names",
    "sheet_rows",
    "urls_in",
]


@pytest.fixture
def sf_export(tmp_path: Path) -> Path:
    """A synthetic Screaming Frog export with real filenames and headers."""
    return fixture_export.write_export(tmp_path / "export")


@pytest.fixture
def empty_export(tmp_path: Path) -> Iterator[Path]:
    """A directory holding no export at all - "not measured", not "none"."""
    root = tmp_path / "empty"
    root.mkdir()
    yield root


def sheet_names(payload: bytes) -> list[str]:
    """Sheet titles of a generated workbook, in order."""
    book = openpyxl.load_workbook(io.BytesIO(payload))
    return [str(name) for name in book.sheetnames]


def sheet_rows(payload: bytes, title: str | None = None) -> list[tuple[object, ...]]:
    """Every row of one sheet of a generated workbook.

    Args:
        payload: The XLSX bytes a service returned.
        title: Sheet to read. Defaults to the first sheet.

    Returns:
        Rows as tuples, values only.
    """
    book = openpyxl.load_workbook(io.BytesIO(payload))
    sheet = book[title] if title is not None else book.worksheets[0]
    return [tuple(row) for row in sheet.iter_rows(values_only=True)]


def detail_table(
    payload: bytes, title: str | None = None
) -> tuple[tuple[object, ...], list[tuple[object, ...]]]:
    """The `Detailed Data` header row and the data rows beneath it.

    Returns `((), [])` when the sheet carries no detail table at all, which is
    what the "no data" and "not measured" branches produce - the caller
    asserts on the placeholder cell instead.

    Raises:
        AssertionError: The sheet has a header row with nothing identifiable
            as a leading URL column, which would mean the layout moved.
    """
    rows = sheet_rows(payload, title)
    for index, row in enumerate(rows):
        if row and row[0] in {"URL", "Issue Type"}:
            header = tuple(cell for cell in row if cell is not None)
            body = [r for r in rows[index + 1 :] if r and r[0] is not None]
            return header, body
    return (), []


def first_cell(payload: bytes, title: str | None = None) -> object:
    """The first non-empty cell of a sheet - the placeholder, when there is one."""
    for row in sheet_rows(payload, title):
        for cell in row:
            if cell is not None:
                return cell
    return None


def urls_in(body: Sequence[tuple[object, ...]]) -> list[object]:
    """The URL column of a detail table."""
    return [row[0] for row in body]
