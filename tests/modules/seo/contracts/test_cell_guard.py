"""The formula-injection guard that every export text cell passes through."""

from __future__ import annotations

from datetime import date

import pytest
from src.modules.seo.contracts.cell_guard import FORMULA_TRIGGER_CHARS, safe_cell


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_a_formula_trigger_is_prefixed_with_an_apostrophe(trigger: str) -> None:
    assert safe_cell(f"{trigger}SUM(A1)") == f"'{trigger}SUM(A1)"


@pytest.mark.parametrize("trigger", ["\t", "\r"])
def test_tab_and_carriage_return_are_guarded_as_well(trigger: str) -> None:
    assert safe_cell(f"{trigger}x") == f"'{trigger}x"


def test_the_trigger_set_is_the_documented_six() -> None:
    assert frozenset({"=", "+", "-", "@", "\t", "\r"}) == FORMULA_TRIGGER_CHARS


@pytest.mark.parametrize("value", ["plain", "a=b", "https://e.com/=x", "", "1+1"])
def test_only_a_leading_trigger_is_changed(value: str) -> None:
    assert safe_cell(value) == value


@pytest.mark.parametrize("value", [0, -3, 2.5, None, True, date(2026, 10, 19)])
def test_values_that_cannot_carry_a_formula_pass_through_unchanged(value: object) -> None:
    assert safe_cell(value) is value


def test_the_deliverables_module_uses_this_same_function() -> None:
    """One guard, not two copies that could drift apart."""
    from src.modules.seo.deliverables.masterfile_base import safe_cell as deliverables_safe_cell

    assert deliverables_safe_cell is safe_cell
