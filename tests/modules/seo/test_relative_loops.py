"""Tests for relative-href loop detection.

The tests that matter here are the ones asserting what is **not** caught. A
count-only rule would have deleted thousands of real pages across the stored
corpus — locale variants of one article, quarterly PDFs under year folders — and
the whole design is the depth check that separates those from a genuine loop.
"""

from __future__ import annotations

from src.modules.seo.page_classifier.discovery import SiteGraph
from src.modules.seo.page_classifier.relative_loops import (
    MIN_DEPTH_SPREAD,
    MIN_LOOP_URLS,
    LoopWatcher,
    find_relative_loops,
)

TAIL = "software/b2b-payments/credit-card-surcharge"


def loop_urls(count: int) -> tuple[str, ...]:
    """A tail appended under parents of steadily increasing depth.

    The real shape: each fabricated page renders the template again, so the next
    generation is one segment deeper than the last.
    """
    return tuple(
        "https://e.com/"
        + "/".join(f"p{index}s{level}" for level in range(index % 8 + 1))
        + f"/{TAIL}"
        for index in range(count)
    )


class TestLoopsAreCaught:
    def test_a_relative_loop_is_detected(self):
        report = find_relative_loops(loop_urls(MIN_LOOP_URLS * 2))
        assert report.url_count == MIN_LOOP_URLS * 2
        assert report.signatures[0].tail == TAIL

    def test_the_verdict_records_the_depth_spread(self):
        """The number that decided it, kept so a reader can check the call."""
        report = find_relative_loops(loop_urls(40))
        assert report.signatures[0].depth_count >= MIN_DEPTH_SPREAD

    def test_every_member_url_is_returned(self):
        urls = loop_urls(30)
        assert set(find_relative_loops(urls).urls) == set(urls)


class TestLegitimateRepetitionSurvives:
    """Measured false-positive cases, each taken from a real stored crawl."""

    def test_locale_variants_of_one_page_are_kept(self):
        """stripe.com serves one newsroom article under 77 locale prefixes.

        Every copy sits at the same depth, because a locale prefix is a fixed
        shape. A count-only rule would have refused all 77.
        """
        urls = tuple(
            f"https://e.com/{locale}/newsroom/news/stripe-and-uber"
            for locale in (f"l{index}" for index in range(MIN_LOOP_URLS * 3))
        )
        assert find_relative_loops(urls).url_count == 0

    def test_dated_folders_of_real_files_are_kept(self):
        """Real files repeated under many dated folders.

        infosys.com publishes `documents/transcripts/press-conference.pdf` under
        78 different year and quarter folders, and every one is a real file.
        """
        urls = tuple(
            f"https://e.com/investors/{year}/q{quarter}/documents/transcripts/call.pdf"
            for year in range(2005, 2026)
            for quarter in range(1, 5)
        )
        assert find_relative_loops(urls).url_count == 0

    def test_a_bare_and_localised_pair_is_not_a_loop(self):
        """`/blog/post` and `/en-gb/blog/post` give one tail two depths honestly.

        This is why the threshold is not 2.
        """
        urls = tuple(
            url
            for index in range(MIN_LOOP_URLS)
            for url in (
                f"https://e.com/blog/post/{index}/a/b",
                f"https://e.com/en-gb/blog/post/{index}/a/b",
            )
        )
        assert find_relative_loops(urls).url_count == 0

    def test_a_small_cluster_is_below_the_pre_filter(self):
        assert find_relative_loops(loop_urls(MIN_LOOP_URLS - 1)).url_count == 0


class TestEdges:
    def test_no_urls_is_not_an_error(self):
        report = find_relative_loops(())
        assert report.url_count == 0
        assert report.signatures == ()

    def test_short_paths_cannot_loop(self):
        """A loop needs a prefix to attach to; a two-segment path has none."""
        urls = tuple(f"https://e.com/a/b?v={index}" for index in range(MIN_LOOP_URLS * 2))
        assert find_relative_loops(urls).url_count == 0

    def test_signatures_are_ordered_by_size(self):
        big = loop_urls(60)
        small = tuple(
            url.replace(TAIL, "software/order-to-cash/credit-cloud") for url in loop_urls(30)
        )
        report = find_relative_loops(big + small)
        counts = [signature.url_count for signature in report.signatures]
        assert counts == sorted(counts, reverse=True)

    def test_a_malformed_url_does_not_raise(self):
        assert find_relative_loops(("http://[", "not a url")).url_count == 0


class TestLoopWatcher:
    """Streaming confirmation, including the URLs admitted before proof existed."""

    def test_a_confirmed_tail_is_refused_from_then_on(self):
        watcher = LoopWatcher()
        urls = loop_urls(MIN_LOOP_URLS * 2)
        refusals = sum(1 for url in urls if watcher.observe(url, url)[0])
        assert refusals > 0

    def test_confirmation_names_the_urls_already_let_through(self):
        """The evidence is the repetition, so the early members necessarily got in.

        Without eviction the count is short by however many it took to prove the
        loop, and the graph keeps them.
        """
        watcher = LoopWatcher()
        evicted: tuple[str, ...] = ()
        for url in loop_urls(MIN_LOOP_URLS * 2):
            refuse, batch = watcher.observe(url, url)
            if batch:
                evicted = batch
                assert refuse is True
        assert len(evicted) == MIN_LOOP_URLS

    def test_eviction_happens_once(self):
        watcher = LoopWatcher()
        batches = [
            batch for url in loop_urls(MIN_LOOP_URLS * 3) if (batch := watcher.observe(url, url)[1])
        ]
        assert len(batches) == 1

    def test_legitimate_repetition_is_never_confirmed(self):
        """The stripe locale case, streamed rather than batched."""
        watcher = LoopWatcher()
        for index in range(MIN_LOOP_URLS * 3):
            url = f"https://e.com/l{index}/newsroom/news/stripe-and-uber"
            assert watcher.observe(url, url) == (False, ())

    def test_the_graph_is_left_clean(self):
        """End to end: a loop must not survive in `SiteGraph`."""
        graph = SiteGraph(base_url="https://e.com/", max_pages=10_000)
        for url in loop_urls(MIN_LOOP_URLS * 4):
            graph.add(url, dom_link=True)
        for url in (f"https://e.com/real/page/{index}" for index in range(5)):
            graph.add(url, dom_link=True)

        held = {node.url for node in graph._nodes.values()}
        assert not any(TAIL in url for url in held)
        assert len(held) == 5
        # Every fabricated address is distinct, which is what the real defect
        # produces: 23,641 different URLs for one page on highradius.com.
        assert graph.report().loop_urls_skipped == MIN_LOOP_URLS * 4
