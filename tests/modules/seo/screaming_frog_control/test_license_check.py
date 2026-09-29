"""Tests for `read_licence_status` — positive licence verification (ADR 0013 §6).

Every log line used here is a real line captured from a live
`ScreamingFrogSEOSpiderCli.exe 19.4 --headless --crawl https://example.com`
run (2026-09-15), not an invented format.
"""

from __future__ import annotations

from pathlib import Path

from src.modules.seo.screaming_frog_control.license_check import (
    FREE_TIER_URL_CEILING,
    read_licence_status,
)

_ACTIVE_LINE = (
    "2026-09-15 17:02:42,845 [38664] [main] INFO  - Licence Status: Active, "
    "expires on 26 Jan 2027 GMT. (Username: trantienduy.com SEO 31)\n"
)
_COMPLETED_LINE = (
    "2026-09-15 17:02:48,628 [38664] [SpiderMain 1] INFO  - Completed the "
    "spider of https://example.com/ in 0 hrs 0 mins 3 secs (3450), null, "
    "crawled 2 urls\n"
)


class TestReadLicenceStatus:
    def test_active_licence_with_completed_crawl(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_ACTIVE_LINE + _COMPLETED_LINE, encoding="utf-8")

        status = read_licence_status(log, since_offset=0)

        assert status.active is True
        assert status.pages_crawled == 2
        assert status.free_tier_capped is False
        assert "trantienduy.com SEO 31" in (status.raw_line or "")

    def test_expired_licence_is_not_active(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(
            "INFO  - Licence Status: Expired on 1 Jan 2020 GMT. (Username: acme)\n",
            encoding="utf-8",
        )

        status = read_licence_status(log, since_offset=0)

        assert status.active is False

    def test_missing_licence_line_fails_closed(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text("INFO - Application Started\n", encoding="utf-8")

        status = read_licence_status(log, since_offset=0)

        assert status.active is False
        assert status.raw_line is None

    def test_missing_file_fails_closed(self, tmp_path) -> None:
        status = read_licence_status(tmp_path / "does-not-exist.txt", since_offset=0)
        assert status.active is False

    def test_page_count_exactly_at_the_free_tier_ceiling_is_flagged(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        completed = _COMPLETED_LINE.replace(
            "crawled 2 urls", f"crawled {FREE_TIER_URL_CEILING} urls"
        )
        log.write_text(_ACTIVE_LINE + completed, encoding="utf-8")

        status = read_licence_status(log, since_offset=0)

        assert status.pages_crawled == FREE_TIER_URL_CEILING
        assert status.free_tier_capped is True

    def test_page_count_below_the_ceiling_is_not_flagged(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        completed = _COMPLETED_LINE.replace("crawled 2 urls", "crawled 499 urls")
        log.write_text(_ACTIVE_LINE + completed, encoding="utf-8")

        status = read_licence_status(log, since_offset=0)

        assert status.free_tier_capped is False

    def test_offset_scopes_the_read_to_this_runs_appended_bytes(self, tmp_path) -> None:
        """A prior run's line before the offset must not leak into this read.

        This is the mechanism the `seo.screaming_frog` facet's
        `max_concurrent=1` cap exists to make safe: only one supervised run
        appends to `trace.txt` at a time, so "everything after the recorded
        offset" is unambiguously this run's output.
        """
        log = tmp_path / "trace.txt"
        prior_run = "INFO  - Licence Status: Active, expires on 1 Jan 2020 GMT. (Username: old)\n"
        log.write_text(prior_run, encoding="utf-8")
        offset = log.stat().st_size

        with log.open("a", encoding="utf-8") as handle:
            handle.write("INFO  - Licence Status: Expired GMT. (Username: new)\n")

        status = read_licence_status(log, since_offset=offset)

        assert status.active is False
        assert "new" in (status.raw_line or "")

    def test_no_completed_line_means_pages_crawled_is_none(self, tmp_path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_ACTIVE_LINE, encoding="utf-8")

        status = read_licence_status(log, since_offset=0)

        assert status.active is True
        assert status.pages_crawled is None
        assert status.free_tier_capped is False


class TestExpectedUrlCount:
    """ADR 0023: a known list length narrows the free-tier inference."""

    def test_five_hundred_of_more_than_five_hundred_is_still_capped(self, tmp_path) -> None:
        trace = _trace(tmp_path, _ACTIVE + _completed(500))
        status = read_licence_status(trace, since_offset=0, expected_url_count=900)
        assert status.free_tier_capped is True
        assert status.shortfall == 400

    def test_five_hundred_of_exactly_five_hundred_is_a_finished_job(self, tmp_path) -> None:
        """The documented false positive, closed for list-mode runs only."""
        trace = _trace(tmp_path, _ACTIVE + _completed(500))
        status = read_licence_status(trace, since_offset=0, expected_url_count=500)
        assert status.free_tier_capped is False
        assert status.shortfall == 0

    def test_omitting_the_count_preserves_the_pre_adr_behaviour_exactly(self, tmp_path) -> None:
        trace = _trace(tmp_path, _ACTIVE + _completed(500))
        status = read_licence_status(trace, since_offset=0)
        assert status.free_tier_capped is True
        assert status.expected_url_count is None
        assert status.shortfall is None

    def test_a_shortfall_short_of_the_ceiling_is_not_a_licence_verdict(self, tmp_path) -> None:
        trace = _trace(tmp_path, _ACTIVE + _completed(40))
        status = read_licence_status(trace, since_offset=0, expected_url_count=100)
        assert status.free_tier_capped is False
        assert status.shortfall == 60

    def test_shortfall_is_never_negative(self, tmp_path) -> None:
        """Screaming Frog can report more rows than URLs supplied; that is not a gain."""
        trace = _trace(tmp_path, _ACTIVE + _completed(12))
        status = read_licence_status(trace, since_offset=0, expected_url_count=10)
        assert status.shortfall == 0

    def test_a_run_that_never_completed_cannot_say(self, tmp_path) -> None:
        trace = _trace(tmp_path, _ACTIVE)
        status = read_licence_status(trace, since_offset=0, expected_url_count=10)
        assert status.pages_crawled is None
        assert status.shortfall is None


_ACTIVE = "INFO  - Licence Status: Active, expires on 26 Jan 2027 GMT. (Username: x)\n"


def _completed(urls: int) -> str:
    return (
        f"INFO  - Completed the spider of https://e.com/ in 0 hrs 0 mins 1 secs (1), "
        f"null, crawled {urls} urls\n"
    )


def _trace(tmp_path, content: str) -> Path:
    path = tmp_path / "trace.txt"
    path.write_text(content, encoding="utf-8")
    return path
