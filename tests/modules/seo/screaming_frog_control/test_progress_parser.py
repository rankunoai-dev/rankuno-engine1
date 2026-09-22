"""Tests for live progress parsing (`progress_parser.py`).

Every `SpiderProgress` line used here is real, captured live from
`ScreamingFrogSEOSpiderCli.exe 19.4` crawling on this workstation on
2026-09-22 — both from history already in the rolling `trace.txt` (an older
run) and from lines appended in real time while this module was written (a
run still in progress at the moment of capture). Neither is an invented
format; see `progress_parser.py`'s own module docstring for the full
reasoning, including the two Screaming-Frog-side oddities (the doubled
`mCompleted` key, the comma thousands separator) a regex against this line
has to account for.
"""

from __future__ import annotations

from pathlib import Path

from src.core.worker_dispatch_schemas import WorkerJobPhase
from src.modules.seo.screaming_frog_control.progress_parser import (
    ProgressPollThread,
    ScreamingFrogProgressReader,
    ScreamingFrogProgressThrottle,
    make_progress_callback,
    parse_latest_progress,
)
from src.modules.seo.screaming_frog_control.schemas import ScreamingFrogProgressSnapshot

_REAL_PROGRESS_LINE = (
    "2026-09-22 12:56:26,923 [18748] [SpiderMain 1] INFO  - SpiderProgress "
    "[mActive=4, mCompleted=3,718, mWaiting=5,474, mCompleted=40.43%]\n"
)
_REAL_PROGRESS_LINE_NO_DECIMAL = (
    "2026-09-22 12:55:13,767 [18748] [SpiderMain 1] INFO  - SpiderProgress "
    "[mActive=4, mCompleted=3,465, mWaiting=5,414, mCompleted=39%]\n"
)
_REAL_CRAWL_UPDATE_LINE = (
    "2026-08-28 11:57:28,569 [25736] [SpiderMain 1] INFO  - Crawl update: SpiderProgress "
    "[mActive=5, mCompleted=1,000, mWaiting=1,671, mCompleted=37.36%] SpiderPerformance "
    "[mAverageUrlsPerSecond=19.90, mCurrentUrlsPerSecond=78.60] in 0 hrs 0 mins 50 secs "
    "(50492). Estimated time remaining 0 hrs 1 mins 24 secs (84000).\n"
)
_REAL_COMPLETED_LINE = (
    "2026-08-28 11:57:29,769 [25736] [SpiderMain 1] INFO  - Completed the spider of "
    "https://www.highradius.com/ in 0 hrs 0 mins 51 secs (51693), null, crawled 2,676 urls\n"
)


class TestParseLatestProgress:
    def test_parses_a_real_progress_line(self) -> None:
        snapshot = parse_latest_progress(_REAL_PROGRESS_LINE)
        assert snapshot is not None
        assert snapshot.pages_crawled == 3718
        assert snapshot.progress_pct == 40.43
        assert snapshot.phase is WorkerJobPhase.CRAWLING

    def test_strips_the_comma_thousands_separator(self) -> None:
        snapshot = parse_latest_progress(_REAL_PROGRESS_LINE)
        assert snapshot is not None
        assert snapshot.pages_crawled == 3718  # not 3 (a naive \d+ would stop at the comma)

    def test_parses_a_percent_with_no_decimal_point(self) -> None:
        snapshot = parse_latest_progress(_REAL_PROGRESS_LINE_NO_DECIMAL)
        assert snapshot is not None
        assert snapshot.progress_pct == 39.0

    def test_matches_the_embedded_form_inside_a_crawl_update_line(self) -> None:
        snapshot = parse_latest_progress(_REAL_CRAWL_UPDATE_LINE)
        assert snapshot is not None
        assert snapshot.pages_crawled == 1000
        assert snapshot.progress_pct == 37.36

    def test_the_last_matching_line_in_a_chunk_wins(self) -> None:
        """trace.txt is append-only and chronological — the freshest line matters."""
        chunk = _REAL_PROGRESS_LINE_NO_DECIMAL + _REAL_PROGRESS_LINE
        snapshot = parse_latest_progress(chunk)
        assert snapshot is not None
        assert snapshot.pages_crawled == 3718

    def test_a_completion_marker_sets_the_exporting_phase(self) -> None:
        chunk = _REAL_PROGRESS_LINE + _REAL_COMPLETED_LINE
        snapshot = parse_latest_progress(chunk)
        assert snapshot is not None
        assert snapshot.phase is WorkerJobPhase.EXPORTING
        # The last SpiderProgress values are still carried, unmodified.
        assert snapshot.pages_crawled == 3718

    def test_a_completion_marker_alone_still_yields_the_exporting_phase(self) -> None:
        snapshot = parse_latest_progress(_REAL_COMPLETED_LINE)
        assert snapshot is not None
        assert snapshot.phase is WorkerJobPhase.EXPORTING
        assert snapshot.pages_crawled is None

    def test_returns_none_for_text_with_no_recognisable_progress(self) -> None:
        assert parse_latest_progress("INFO  - Licence Status: Active\n") is None

    def test_returns_none_for_empty_text(self) -> None:
        assert parse_latest_progress("") is None


class TestScreamingFrogProgressReader:
    def test_returns_none_when_nothing_new_has_been_appended(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE, encoding="utf-8")
        reader = ScreamingFrogProgressReader(log, since_offset=log.stat().st_size)

        assert reader.poll() is None

    def test_reads_only_bytes_appended_after_since_offset(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text("INFO  - some prior run's own history\n", encoding="utf-8")
        offset = log.stat().st_size
        with log.open("a", encoding="utf-8") as handle:
            handle.write(_REAL_PROGRESS_LINE)
        reader = ScreamingFrogProgressReader(log, since_offset=offset)

        snapshot = reader.poll()

        assert snapshot is not None
        assert snapshot.pages_crawled == 3718

    def test_a_second_poll_only_sees_bytes_appended_since_the_first(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE_NO_DECIMAL, encoding="utf-8")
        reader = ScreamingFrogProgressReader(log, since_offset=0)
        first = reader.poll()
        assert first is not None
        assert first.pages_crawled == 3465

        with log.open("a", encoding="utf-8") as handle:
            handle.write(_REAL_PROGRESS_LINE)
        second = reader.poll()

        assert second is not None
        assert second.pages_crawled == 3718

    def test_a_missing_file_degrades_to_none_without_raising(self, tmp_path: Path) -> None:
        reader = ScreamingFrogProgressReader(tmp_path / "does-not-exist.txt", since_offset=0)
        assert reader.poll() is None
        assert reader.rotated is True

    def test_rotation_mid_poll_degrades_gracefully_and_stays_degraded(self, tmp_path: Path) -> None:
        """Rotation mid-poll degrades gracefully and stays degraded.

        The scenario the module docstring names: trace.txt crossed SF's own
        size ceiling mid-crawl and was replaced by a fresh, smaller file.
        """
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE * 5, encoding="utf-8")
        offset = log.stat().st_size
        reader = ScreamingFrogProgressReader(log, since_offset=offset)
        assert reader.rotated is False

        # Simulate Screaming Frog's own rotation: the file is replaced by a
        # fresh, much smaller one (as trace.txt.1 takes the old content).
        log.write_text(_REAL_PROGRESS_LINE_NO_DECIMAL, encoding="utf-8")
        assert log.stat().st_size < offset

        result = reader.poll()

        assert result is None
        assert reader.rotated is True

    def test_once_rotated_never_reports_fresh_progress_again(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE * 5, encoding="utf-8")
        offset = log.stat().st_size
        reader = ScreamingFrogProgressReader(log, since_offset=offset)
        log.write_text("short\n", encoding="utf-8")
        reader.poll()  # detects rotation

        # Even if the file grows again past the original offset, this reader
        # must never resume — it cannot know whether the new bytes belong to
        # this run, a different one, or a manually started GUI.
        with log.open("a", encoding="utf-8") as handle:
            handle.write(_REAL_PROGRESS_LINE * 20)

        assert reader.poll() is None
        assert reader.rotated is True

    def test_never_reports_a_negative_or_garbage_progress_on_rotation(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE, encoding="utf-8")
        reader = ScreamingFrogProgressReader(log, since_offset=10_000)  # offset beyond EOF already

        result = reader.poll()

        assert result is None
        assert reader.rotated is True


class TestScreamingFrogProgressThrottle:
    def _snapshot(
        self, *, pages: int, pct: float, phase: WorkerJobPhase = WorkerJobPhase.CRAWLING
    ) -> ScreamingFrogProgressSnapshot:
        return ScreamingFrogProgressSnapshot(pages_crawled=pages, progress_pct=pct, phase=phase)

    def test_the_first_snapshot_is_always_reported(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0)
        assert throttle.should_report(self._snapshot(pages=1, pct=1.0), now=0.0) is True

    def test_a_second_snapshot_inside_the_interval_is_suppressed(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0)
        first = self._snapshot(pages=1, pct=1.0)
        throttle.record_sent(first, now=0.0)

        assert throttle.should_report(self._snapshot(pages=2, pct=2.0), now=1.0) is False

    def test_a_snapshot_past_the_interval_with_a_meaningful_change_is_reported(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0, min_pct_delta=1.0)
        throttle.record_sent(self._snapshot(pages=1, pct=1.0), now=0.0)

        assert throttle.should_report(self._snapshot(pages=50, pct=5.0), now=10.0) is True

    def test_a_tiny_change_past_the_interval_is_still_suppressed(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0, min_pct_delta=1.0)
        throttle.record_sent(self._snapshot(pages=100, pct=10.0), now=0.0)

        assert throttle.should_report(self._snapshot(pages=101, pct=10.2), now=10.0) is False

    def test_a_phase_transition_is_always_reported_regardless_of_the_floor(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0)
        throttle.record_sent(
            self._snapshot(pages=1, pct=1.0, phase=WorkerJobPhase.CRAWLING), now=0.0
        )

        exporting = self._snapshot(pages=1, pct=1.0, phase=WorkerJobPhase.EXPORTING)
        assert throttle.should_report(exporting, now=0.001) is True

    def test_record_sent_resets_the_floor(self) -> None:
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0)
        throttle.record_sent(self._snapshot(pages=1, pct=1.0), now=0.0)
        throttle.record_sent(self._snapshot(pages=2, pct=2.0), now=6.0)

        assert throttle.should_report(self._snapshot(pages=3, pct=3.0), now=6.5) is False


class TestMakeProgressCallback:
    def test_forwards_snapshot_fields_to_the_clients_report_progress(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class _FakeClient:
            def report_progress(self, job_id: str, **kwargs: object) -> None:
                calls.append((job_id, kwargs))

        callback = make_progress_callback(_FakeClient(), "job-1")  # type: ignore[arg-type]
        callback(
            ScreamingFrogProgressSnapshot(
                pages_crawled=10, progress_pct=50.0, phase=WorkerJobPhase.CRAWLING
            )
        )

        assert calls == [
            ("job-1", {"pages_crawled": 10, "progress_pct": 50.0, "phase": WorkerJobPhase.CRAWLING})
        ]


class TestProgressPollThread:
    """Direct coverage of the thread class itself.

    Below `tool.py`'s own integration-level thread-lifecycle tests — this is
    where the `_stop`-name-collision regression against `threading.Thread`'s
    own internals (a real bug found while writing this feature, not a
    hypothetical) is pinned at the smallest possible scope.
    """

    def test_join_succeeds_after_stop_is_called(self, tmp_path: Path) -> None:
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE, encoding="utf-8")
        reader = ScreamingFrogProgressReader(log, since_offset=0)
        throttle = ScreamingFrogProgressThrottle(min_interval_s=5.0)
        thread = ProgressPollThread(
            reader, throttle, lambda _s: None, poll_interval_s=60.0, job_id="job-1"
        )

        thread.start()
        thread.stop()
        thread.join(timeout=5.0)

        assert thread.is_alive() is False

    def test_polls_exactly_once_more_after_stop_even_with_a_long_interval(
        self, tmp_path: Path
    ) -> None:
        """The guaranteed final poll.

        Why a caller need not tune the interval down just to avoid losing
        the crawl's last few seconds.
        """
        log = tmp_path / "trace.txt"
        log.write_text(_REAL_PROGRESS_LINE, encoding="utf-8")
        reader = ScreamingFrogProgressReader(log, since_offset=0)
        throttle = ScreamingFrogProgressThrottle(min_interval_s=0.0)
        received: list[ScreamingFrogProgressSnapshot] = []
        thread = ProgressPollThread(
            reader, throttle, received.append, poll_interval_s=60.0, job_id="job-1"
        )

        thread.start()
        thread.stop()
        thread.join(timeout=5.0)

        assert received  # the long 60s interval never got a chance to matter
        assert received[0].pages_crawled == 3718
