"""Ranking the top queries per URL, and joining them to the crawled pages."""

from __future__ import annotations

import pytest
from src.integrations.gsc_schemas import GscPageQueries, GscQueryRow
from src.modules.seo.performance.query_by_url import (
    TOP_QUERIES_PER_URL,
    rank_queries,
    top_queries_by_crawl_url,
)
from tests.modules.seo.page_classifier.report_profile_factory import make_page


def row(
    query: str,
    clicks: int = 0,
    impressions: int = 0,
    position: float = 1.0,
    page: str = "https://e.com/a/",
) -> GscQueryRow:
    return GscQueryRow(
        page=page,
        query=query,
        clicks=clicks,
        impressions=impressions,
        avg_position=position,
    )


def fetch(*rows: GscQueryRow) -> GscPageQueries:
    return GscPageQueries(
        property_url="https://e.com/",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rows=list(rows),
        complete=True,
        stop_reason="exhausted",
    )


class TestRanking:
    def test_clicks_then_impressions_then_query_text(self) -> None:
        ranked = rank_queries([row("b", 5, 10), row("a", 5, 10), row("c", 5, 20), row("d", 9, 1)])

        assert [r.query for r in ranked] == ["d", "c", "a", "b"]

    def test_at_most_the_top_five_are_kept(self) -> None:
        ranked = rank_queries([row(f"q{i}", clicks=i) for i in range(7)])

        assert TOP_QUERIES_PER_URL == 5
        assert [r.clicks for r in ranked] == [6, 5, 4, 3, 2]


class TestJoin:
    def test_each_row_attaches_to_the_crawled_page_it_names(self) -> None:
        pages = [make_page("https://e.com/a/"), make_page("https://e.com/b/")]

        result = top_queries_by_crawl_url(
            pages,
            fetch(
                row("x", 3, 9, page="https://e.com/a/"),
                row("y", 1, 2, page="https://e.com/b/"),
            ),
        )

        assert [r.query for r in result["https://e.com/a/"]] == ["x"]
        assert [r.query for r in result["https://e.com/b/"]] == ["y"]

    def test_a_page_with_no_matching_rows_is_absent_not_empty(self) -> None:
        pages = [make_page("https://e.com/a/"), make_page("https://e.com/b/")]

        result = top_queries_by_crawl_url(pages, fetch(row("x", page="https://e.com/a/")))

        assert "https://e.com/b/" not in result

    def test_an_address_that_matches_no_page_is_left_out(self) -> None:
        result = top_queries_by_crawl_url(
            [make_page("https://e.com/a/")],
            fetch(row("x", page="https://elsewhere.example/zz/")),
        )

        assert result == {}

    def test_no_fetch_means_no_queries(self) -> None:
        assert top_queries_by_crawl_url([make_page("https://e.com/a/")], None) == {}

    def test_the_same_query_from_two_rows_is_summed_not_listed_twice(self) -> None:
        result = top_queries_by_crawl_url(
            [make_page("https://e.com/a/")],
            fetch(
                row("x", 2, 10, page="https://e.com/a/"),
                row("x", 3, 30, page="https://e.com/a/"),
            ),
        )

        [only] = result["https://e.com/a/"]
        assert (only.clicks, only.impressions) == (5, 40)

    def test_position_is_weighted_by_impressions(self) -> None:
        result = top_queries_by_crawl_url(
            [make_page("https://e.com/a/")],
            fetch(
                row("x", 0, 10, 2.0, page="https://e.com/a/"),
                row("x", 0, 30, 6.0, page="https://e.com/a/"),
            ),
        )

        [only] = result["https://e.com/a/"]
        assert only.avg_position == pytest.approx(5.0)
