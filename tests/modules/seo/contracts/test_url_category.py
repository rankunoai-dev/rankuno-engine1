"""Path categories and their sort order, checked against the shared parity fixture.

The same fixture is read by `rankuno-ui/src/lib/dashboardModel.test.ts`. A case
added here is therefore a case the TypeScript helper must also satisfy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.modules.seo.contracts.url_category import (
    HOMEPAGE_CATEGORY,
    UNCATEGORISED,
    category_key,
    category_sort_key,
)

PARITY = Path(__file__).resolve().parents[3] / "fixtures" / "url_category" / "parity.json"
CASES: list[dict[str, str]] = json.loads(PARITY.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["url"] or "<empty>")
def test_category_matches_the_shared_fixture(case: dict[str, str]) -> None:
    assert category_key(case["url"]) == case["category"]


def test_the_fixture_covers_every_category_shape() -> None:
    """A fixture of easy cases would let the two languages drift without a failing test."""
    categories = {case["category"] for case in CASES}
    assert {HOMEPAGE_CATEGORY, UNCATEGORISED, "blog", "%e2%82%ac-deals", "a b"} <= categories


def test_the_homepage_sorts_first_and_uncategorised_last() -> None:
    urls = ["https://e.com/zeta/", "not a url", "https://e.com/", "https://e.com/alpha/"]

    ordered = sorted(urls, key=category_sort_key)

    assert ordered == [
        "https://e.com/",
        "https://e.com/alpha/",
        "https://e.com/zeta/",
        "not a url",
    ]


def test_a_real_segment_named_uncategorised_is_not_grouped_with_unparseable_addresses() -> None:
    """The tier comes from whether the address parsed, not from comparing category text."""
    urls = ["not a url", "https://e.com/(uncategorised)/x"]

    ordered = sorted(urls, key=category_sort_key)

    assert ordered == ["https://e.com/(uncategorised)/x", "not a url"]


def test_ties_within_a_category_break_on_the_url() -> None:
    urls = ["https://e.com/blog/b", "https://e.com/blog/a"]

    assert sorted(urls, key=category_sort_key) == [
        "https://e.com/blog/a",
        "https://e.com/blog/b",
    ]


def test_query_and_fragment_do_not_change_the_category() -> None:
    assert category_key("https://e.com/blog?x=/other#frag") == "blog"
