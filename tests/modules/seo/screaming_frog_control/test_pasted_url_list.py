"""Tests for reading an operator's pasted text into a URL list (ADR 0023).

What is pinned here, and why each would be invisible without a test:

* **The three tiers of tolerance.** Silent, reported, refused. A regression
  that moved a line from "reported" to "silent" would still pass every happy
  path, and the operator would approve a count with an assumption inside it
  they were never told about.
* **The parse identity.** `lines - blank - header - malformed == accepted`.
  The numbers in `PasteCounts` are rendered as prose beside an approval, and
  a set of counts that does not add up is a set of counts nobody can check.
* **`mailto:` is refused, not rewritten.** The one parsing bug in this module
  that would be a security defect rather than an annoyance: prepending
  `https://` to a line that already declares a scheme produces a URL that
  parses, survives every later filter as a path, and gets dispatched.
* **The domain grouping**, because it is what fills the seed URL, and the
  seed URL's registrable domain is what the whole list is filtered against.
"""

from __future__ import annotations

from src.modules.seo.screaming_frog_control.pasted_url_list import (
    MALFORMED_EXAMPLES,
    parse_pasted_urls,
    plan_pasted_urls,
)


def _urls(text: str) -> tuple[str, ...]:
    return parse_pasted_urls(text).urls


def test_clean_paste_is_read_verbatim_and_in_order() -> None:
    parsed = parse_pasted_urls("https://example.com/a\nhttps://example.com/b\nhttp://example.com/c")
    assert parsed.urls == (
        "https://example.com/a",
        "https://example.com/b",
        "http://example.com/c",
    )
    assert parsed.counts.accepted == 3
    assert parsed.counts.malformed_dropped == 0
    assert parsed.counts.scheme_added == 0
    assert parsed.counts.spreadsheet_rows == 0


def test_blank_lines_and_whitespace_are_dropped_silently() -> None:
    """Whitespace does not change which page is fetched, so it is not reported."""
    parsed = parse_pasted_urls("\n  https://example.com/a  \n\n\t\nhttps://example.com/b\t\n\n")
    assert parsed.urls == ("https://example.com/a", "https://example.com/b")
    assert parsed.counts.blank_dropped == 4
    assert parsed.counts.accepted == 2
    assert parsed.counts.malformed_dropped == 0


def test_crlf_and_a_bom_survive_a_round_trip_through_notepad() -> None:
    parsed = parse_pasted_urls("﻿https://example.com/a\r\nhttps://example.com/b\r\n")
    assert parsed.urls == ("https://example.com/a", "https://example.com/b")


def test_counts_reconcile_exactly() -> None:
    """`lines - blank - header - malformed == accepted`, on a messy paste."""
    counts = parse_pasted_urls(
        "URL\nhttps://example.com/a\n\nPage Title\nexample.com/b\n\n\nnot a url at all\n"
    ).counts
    assert (
        counts.lines - counts.blank_dropped - counts.header_dropped - counts.malformed_dropped
        == counts.accepted
    )


def test_a_leading_header_row_is_dropped_and_counted_not_called_malformed() -> None:
    parsed = parse_pasted_urls("Address\nhttps://example.com/a")
    assert parsed.urls == ("https://example.com/a",)
    assert parsed.counts.header_dropped == 1
    assert parsed.counts.malformed_dropped == 0


def test_a_header_word_further_down_is_a_mistake_not_a_header() -> None:
    """Only the first content line can be a header. Later ones are real errors."""
    parsed = parse_pasted_urls("https://example.com/a\nurl\nhttps://example.com/b")
    assert parsed.counts.header_dropped == 0
    assert parsed.counts.malformed_dropped == 1


def test_a_missing_scheme_is_assumed_https_and_reported() -> None:
    parsed = parse_pasted_urls("example.com/a\nwww.example.com/b\n//example.com/c")
    assert parsed.urls == (
        "https://example.com/a",
        "https://www.example.com/b",
        "https://example.com/c",
    )
    assert parsed.counts.scheme_added == 3


def test_a_spreadsheet_row_yields_its_first_address_and_is_reported() -> None:
    parsed = parse_pasted_urls(
        'Home,https://example.com/a,200\n"Pricing"\t"https://example.com/b"\t200'
    )
    assert parsed.urls == ("https://example.com/a", "https://example.com/b")
    assert parsed.counts.spreadsheet_rows == 2


def test_a_url_holding_a_comma_is_not_cut_in_half() -> None:
    """The whole line is tried before it is ever treated as a row."""
    assert _urls("https://example.com/a?ids=1,2,3") == ("https://example.com/a?ids=1,2,3",)


def test_a_quoted_cell_loses_its_quotes_and_its_csv_doubling() -> None:
    assert _urls('"https://example.com/a"') == ("https://example.com/a",)


def test_a_non_web_scheme_is_refused_and_never_given_a_prefix() -> None:
    """The defect this guards: `https://mailto:...` parses and would dispatch."""
    parsed = parse_pasted_urls(
        "mailto:sales@example.com\ntel:+441234567890\njavascript:void(0)\nftp://example.com/a"
    )
    assert parsed.urls == ()
    assert parsed.counts.malformed_dropped == 4


def test_prose_and_numbers_are_refused_rather_than_turned_into_hosts() -> None:
    parsed = parse_pasted_urls("Page Title\n404\nsome notes here\n/relative/path")
    assert parsed.urls == ()
    assert parsed.counts.malformed_dropped == 4


def test_one_stray_line_does_not_refuse_the_whole_paste() -> None:
    parsed = parse_pasted_urls("https://example.com/a\nPage Title\nhttps://example.com/b")
    assert parsed.urls == ("https://example.com/a", "https://example.com/b")
    assert parsed.counts.malformed_dropped == 1


def test_unreadable_lines_are_quoted_back_with_line_numbers_and_capped() -> None:
    """A bare count says there is a problem and nothing about where it is."""
    parsed = parse_pasted_urls("\n".join(f"row {index}" for index in range(20)))
    assert parsed.counts.malformed_dropped == 20
    assert len(parsed.counts.malformed_examples) == MALFORMED_EXAMPLES
    assert parsed.counts.malformed_examples[0] == "line 1: row 0"


def test_a_very_long_unreadable_line_is_truncated_in_the_example() -> None:
    parsed = parse_pasted_urls("x" * 500)
    assert parsed.counts.malformed_examples == ("line 1: " + "x" * 80,)


def test_an_empty_paste_reads_as_nothing_rather_than_failing() -> None:
    parsed = parse_pasted_urls("")
    assert parsed.urls == ()
    assert parsed.counts.lines == 0
    assert parsed.counts.accepted == 0


def test_duplicates_are_left_for_build_url_list_to_remove() -> None:
    """Deduping here too would give an operator two numbers for one fact."""
    assert _urls("https://example.com/a\nhttps://example.com/a") == (
        "https://example.com/a",
        "https://example.com/a",
    )


def test_plan_groups_by_registrable_domain_largest_first() -> None:
    plan = plan_pasted_urls(
        "https://example.com/a\nhttps://other.test/x\nhttps://blog.example.com/b\n"
        "https://example.com/c",
        max_urls=10_000,
    )
    assert [(entry.registrable_domain, entry.url_count) for entry in plan.domains] == [
        ("example.com", 3),
        ("other.test", 1),
    ]
    assert plan.suggested_seed_url == "https://example.com/"


def test_plan_ties_break_alphabetically_so_the_offer_is_stable() -> None:
    plan = plan_pasted_urls("https://zeta.test/a\nhttps://alpha.test/b", max_urls=10_000)
    assert [entry.registrable_domain for entry in plan.domains] == ["alpha.test", "zeta.test"]


def test_plan_suggests_the_scheme_the_paste_actually_used() -> None:
    plan = plan_pasted_urls("http://example.com/a", max_urls=10_000)
    assert plan.suggested_seed_url == "http://example.com/"


def test_plan_reports_an_over_ceiling_paste_before_the_operator_commits() -> None:
    text = "\n".join(f"https://example.com/{index}" for index in range(12))
    plan = plan_pasted_urls(text, max_urls=10)
    assert plan.exceeds_ceiling is True
    assert plan.max_urls == 10


def test_plan_of_an_unreadable_paste_offers_no_domain_and_no_seed() -> None:
    plan = plan_pasted_urls("Page Title\nanother title", max_urls=10_000)
    assert plan.domains == ()
    assert plan.suggested_seed_url == ""
    assert plan.exceeds_ceiling is False
    assert plan.counts.malformed_dropped == 2
