"""The formula-injection guard every exported text cell passes through.

Lives in `contracts` because two packages write spreadsheets and PDFs from
crawled content: `deliverables` (the masterfile workbooks) and `page_classifier`
(the URL exports). ADR 0011 lets those two share only this package, so the guard
is defined once here and imported from both, rather than kept as two copies that
could drift apart.

The trigger set is OWASP's: `=`, `+`, `-` and `@` start a formula in Excel and
LibreOffice, and tab and carriage return are included because a cell beginning
with either can be re-parsed as a formula on paste. Covering all six costs
nothing, so the set is not narrowed to what one spreadsheet product does.
"""

from __future__ import annotations

from typing import Final

__all__ = ["FORMULA_TRIGGER_CHARS", "safe_cell"]

FORMULA_TRIGGER_CHARS: Final[frozenset[str]] = frozenset({"=", "+", "-", "@", "\t", "\r"})
"""OWASP formula injection triggers. Guard every cell value."""


def safe_cell(value: object) -> object:
    """Neutralise formula-injection trigger characters.

    Only a string whose first character is a trigger is changed. Numbers, dates
    and `None` pass through, because they cannot carry a formula. Prefixing with
    `'` makes a spreadsheet show the text instead of running it.

    Args:
        value: Cell value (any type)

    Returns:
        Safe value (string values starting with trigger chars are prefixed with ')
    """
    if isinstance(value, str) and value and value[0] in FORMULA_TRIGGER_CHARS:
        return f"'{value}"
    return value
