r"""Live progress parsing for a running Screaming Frog crawl.

Split out of `license_check.py` and `tool.py` to keep both under this
codebase's 400-line target (CLAUDE.md §9) and because this module answers a
different question than either: `license_check.read_licence_status` is a
one-shot terminal read, done once after a supervised process has already
exited; this module is polled repeatedly, from a background thread, across
the whole life of a still-running process, and so has to handle a failure
mode a one-shot read never encounters — `trace.txt` rotating out from under
a read in progress (see `ScreamingFrogProgressReader` below).

The verified progress-line format
----------------------------------
Screaming Frog's CLI does **not** print anything resembling
``Spidering https://example.com/page-1 ... (15 of 120, 12.5%)`` — that shape
was this feature's original illustrative example and was never observed.
What it actually prints to `trace.txt`, confirmed against a real, live
`ScreamingFrogSEOSpiderCli.exe 19.4` crawl running on this workstation while
this module was written (2026-09-22, both as older history already in the
rolling log and as fresh lines appended in real time during the read), is a
`SpiderMain` thread line of this shape, roughly once per second while the
spider is active::

    2026-09-22 12:56:26,923 [18748] [SpiderMain 1] INFO  - SpiderProgress \
[mActive=4, mCompleted=3,718, mWaiting=5,474, mCompleted=40.43%]

Two things worth naming so a future reader does not "fix" them by mistake:

* The key `mCompleted` appears **twice** with two different meanings — a
  raw completed-page count, then (later in the same bracket) a percentage.
  This is Screaming Frog's own apparent field-naming collision, not a typo
  introduced here; `_SPIDER_PROGRESS_LINE` below captures them into two
  differently-named groups precisely because the raw text does not
  distinguish them itself.
* Large counts use a comma thousands separator (`3,718`), which
  `_strip_thousands` strips before `int()`/`float()`. Note that
  `license_check._COMPLETED_LINE`'s regex (`crawled (?P<count>\d+) urls?$`)
  does **not** account for this and silently fails to match a real
  completion line like ``crawled 2,676 urls`` — confirmed against the same
  live trace.txt this module's own regex was built against. That is a
  pre-existing defect in a file this change does not otherwise touch;
  logged as a handoff rather than fixed here (see the cycle's build-log).

The same richer ``Crawl update: SpiderProgress [...] SpiderPerformance
[...]`` line Screaming Frog also prints periodically embeds an identical
``SpiderProgress [...]`` substring, so `_SPIDER_PROGRESS_LINE.finditer`
matches both forms without needing to special-case either.

Completion is detected only as a phase marker here (did a "Completed the
spider of..." line appear at all in this chunk), never for its page count —
`license_check.py` already owns extracting that count for the licence check,
and this module has no reason to duplicate (and inherit the bug in) that
extraction.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from src.core.logger import get_logger
from src.core.worker_dispatch_schemas import WorkerJobPhase
from src.integrations.worker_cloud_client import WorkerCloudClient
from src.modules.seo.screaming_frog_control.schemas import ScreamingFrogProgressSnapshot

__all__ = [
    "ProgressPollThread",
    "ScreamingFrogProgressReader",
    "ScreamingFrogProgressThrottle",
    "make_progress_callback",
    "parse_latest_progress",
]

_logger = get_logger(__name__)

_SPIDER_PROGRESS_LINE = re.compile(
    r"SpiderProgress \[mActive=[\d,]+, mCompleted=(?P<completed>[\d,]+), "
    r"mWaiting=[\d,]+, mCompleted=(?P<percent>\d+(?:\.\d+)?)%\]"
)
_COMPLETION_MARKER = re.compile(r"Completed the spider of")


def _strip_thousands(digits: str) -> str:
    """Remove Screaming Frog's comma thousands separator before parsing."""
    return digits.replace(",", "")


def parse_latest_progress(appended_text: str) -> ScreamingFrogProgressSnapshot | None:
    """Find the freshest progress state in one chunk of newly appended text.

    `trace.txt` is append-only and chronological, so the *last* matching
    `SpiderProgress` line in the chunk is always the most recent — this
    walks every match rather than stopping at the first, deliberately.

    Args:
        appended_text: Bytes a caller has already scoped to "what this run
            wrote since the last read" (see `ScreamingFrogProgressReader`).

    Returns:
        `None` if the chunk carries no recognisable progress information at
        all — e.g. it arrived before the spider phase logged its first
        update, or after a prior chunk already reached `EXPORTING` and
        nothing about that has changed since.
    """
    pages_crawled: int | None = None
    progress_pct: float | None = None
    for match in _SPIDER_PROGRESS_LINE.finditer(appended_text):
        pages_crawled = int(_strip_thousands(match.group("completed")))
        progress_pct = float(match.group("percent"))

    phase: WorkerJobPhase | None = None
    if pages_crawled is not None or progress_pct is not None:
        phase = WorkerJobPhase.CRAWLING
    if _COMPLETION_MARKER.search(appended_text):
        phase = WorkerJobPhase.EXPORTING

    if phase is None:
        return None
    return ScreamingFrogProgressSnapshot(
        pages_crawled=pages_crawled, progress_pct=progress_pct, phase=phase
    )


class ScreamingFrogProgressReader:
    """Stateful, offset-scoped, rotation-aware reads of one run's trace.txt.

    Mirrors `license_check.read_licence_status`'s offset convention (bytes
    before `since_offset` belong to a prior run, or a concurrently running
    GUI, and are never considered) but is re-entrant across many calls from
    a long-lived background thread rather than a single terminal read, so it
    has to track where it left off, and it has to survive the one failure
    mode a long poll adds that a one-shot read never meets: Screaming Frog's
    own `trace.txt` rotating (to `trace.txt.1`) mid-crawl once its configured
    size ceiling is crossed (documented, previously-unhandled limitation —
    `license_check` module docstring).

    The chosen degrade, once rotation is detected: stop reporting fresh
    progress for the remainder of this run, permanently, and log a warning
    exactly once. Deliberately not "reattach to the new, now-tiny
    trace.txt": that file may be a fresh run's own start (a manually started
    GUI, or another job entirely — the licence-check module docstring's own
    "shared across every invocation on this workstation" caveat applies
    here too), and misattributing its contents to *this* job would be worse
    than simply going quiet. The crawl itself is entirely unaffected either
    way — this class only ever reads, never writes, and a poll failure here
    must never surface as a crawl failure.
    """

    def __init__(self, trace_log_path: Path, *, since_offset: int) -> None:
        """Start tracking one run's appended bytes from `since_offset`."""
        self._path = trace_log_path
        self._offset = since_offset
        self._rotated = False

    @property
    def rotated(self) -> bool:
        """Whether a rotation was detected; once `True`, stays `True`."""
        return self._rotated

    def poll(self) -> ScreamingFrogProgressSnapshot | None:
        """Read whatever this run appended since the last successful poll.

        Returns:
            A fresh snapshot, or `None` if there is nothing new to report
            (no bytes appended, nothing recognisable in them yet, or —
            permanently, once detected — a rotation).
        """
        if self._rotated:
            return None

        try:
            size = self._path.stat().st_size
        except OSError:
            self._rotated = True
            _logger.warning("sf_progress_trace_log_missing", extra={"path": str(self._path)})
            return None

        if size < self._offset:
            self._rotated = True
            _logger.warning(
                "sf_progress_trace_log_rotated",
                extra={
                    "path": str(self._path),
                    "recorded_offset": self._offset,
                    "new_size": size,
                },
            )
            return None
        if size == self._offset:
            return None

        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                appended = handle.read().decode("utf-8", errors="replace")
        except OSError as exc:
            # Transient (e.g. a concurrent writer briefly locking the file
            # on Windows) — not treated as a rotation, so a caller is free
            # to try again on the next tick rather than going quiet for good.
            _logger.warning(
                "sf_progress_trace_log_unreadable",
                extra={"path": str(self._path), "error": str(exc)},
            )
            return None

        self._offset = size
        return parse_latest_progress(appended)


class ScreamingFrogProgressThrottle:
    """Decides whether a fresh snapshot is worth sending to the cloud.

    ADR 0015's dispatch store opens a new Postgres connection per call, with
    no pool and no in-process fallback (condition 5) — a naive "report every
    poll tick" policy would cost one such connection roughly every
    `Settings.screaming_frog_progress_poll_interval_s` (1.5s by default) for
    the entire length of a crawl that can legitimately run for
    `Settings.screaming_frog_max_runtime_s` (two hours by default): several
    thousand writes for one job. This throttle is the deliberate answer:
    coalesce on the worker side, before a network call is even attempted,
    rather than let the cloud silently absorb (or itself have to police) that
    volume. A phase transition is always let through immediately regardless
    of the floor below, since "the crawl started exporting" is exactly the
    kind of update a dashboard should never be stale about.
    """

    def __init__(self, *, min_interval_s: float, min_pct_delta: float = 1.0) -> None:
        """Build a throttle.

        Args:
            min_interval_s: Minimum wall-clock time between two accepted
                reports for an unchanged phase, however often `poll` finds a
                new snapshot in between.
            min_pct_delta: Minimum change in `progress_pct` (or any change
                in `pages_crawled` when `progress_pct` is unavailable) worth
                reporting once `min_interval_s` has elapsed. Not so small
                that a normal crawl reports every single tick, not so large
                that a dashboard looks frozen for long stretches.
        """
        self._min_interval_s = min_interval_s
        self._min_pct_delta = min_pct_delta
        self._last_sent: ScreamingFrogProgressSnapshot | None = None
        self._last_sent_at: float | None = None

    def should_report(self, snapshot: ScreamingFrogProgressSnapshot, *, now: float) -> bool:
        """Whether `snapshot` clears the coalescing bar right now."""
        if self._last_sent is None:
            return True
        if snapshot.phase != self._last_sent.phase:
            return True
        if self._last_sent_at is not None and (now - self._last_sent_at) < self._min_interval_s:
            return False
        if snapshot.progress_pct is not None and self._last_sent.progress_pct is not None:
            return abs(snapshot.progress_pct - self._last_sent.progress_pct) >= self._min_pct_delta
        return snapshot.pages_crawled != self._last_sent.pages_crawled

    def record_sent(self, snapshot: ScreamingFrogProgressSnapshot, *, now: float) -> None:
        """Record that `snapshot` was just reported, resetting the floor."""
        self._last_sent = snapshot
        self._last_sent_at = now


class ProgressPollThread(threading.Thread):
    """Owns the poll-throttle-report loop as a stoppable background thread.

    A thin `threading.Thread` subclass rather than a bare function passed to
    `threading.Thread(target=...)`: the stop mechanism (`Event.wait`, which
    returns immediately once set rather than sleeping out a full interval)
    needs to be reachable from the caller that starts this thread, so it has
    to be an attribute of something the caller keeps a handle to. Matches
    the `daemon=True` posture `api.server`'s own two startup background
    threads already use — belt-and-suspenders: `tool.execute()` always joins
    this thread itself before returning (see its own docstring), but a
    daemon thread that somehow outlived a bug in that join still cannot keep
    the interpreter alive on its own.
    """

    def __init__(
        self,
        reader: ScreamingFrogProgressReader,
        throttle: ScreamingFrogProgressThrottle,
        on_progress: Callable[[ScreamingFrogProgressSnapshot], None],
        *,
        poll_interval_s: float,
        job_id: str,
    ) -> None:
        """Build the thread. Does not start it (see `threading.Thread`)."""
        super().__init__(name=f"sf-progress-{job_id}", daemon=True)
        self._reader = reader
        self._throttle = throttle
        self._on_progress = on_progress
        self._poll_interval_s = poll_interval_s
        self._job_id = job_id
        # Named `_stop_event`, deliberately not `_stop`: `threading.Thread`
        # already owns a private `_stop` *method* internally (used by
        # `join()`'s own bookkeeping) — shadowing it with an instance
        # attribute of the same name silently breaks `join()` the moment the
        # thread finishes, with an error that has nothing to do with this
        # class's own code. Caught by this feature's own thread-lifecycle
        # test suite, not by inspection.
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Request the loop end after its current tick, if any, completes."""
        self._stop_event.set()

    def run(self) -> None:
        """Poll on an interval until stopped, then poll exactly once more.

        The extra poll after `stop()` is requested is why a caller does not
        lose the last few seconds of real progress that happened between the
        previous tick and the supervised process actually exiting.
        """
        while not self._stop_event.wait(self._poll_interval_s):
            self._poll_and_report()
        self._poll_and_report()

    def _poll_and_report(self) -> None:
        try:
            snapshot = self._reader.poll()
            if snapshot is None:
                return
            now = time.monotonic()
            if not self._throttle.should_report(snapshot, now=now):
                return
            self._throttle.record_sent(snapshot, now=now)
            self._on_progress(snapshot)
        except Exception:  # noqa: BLE001 - a reporting failure must never touch the crawl
            _logger.exception("sf_progress_report_failed", extra={"job_id": self._job_id})


def make_progress_callback(
    client: WorkerCloudClient, job_id: str
) -> Callable[[ScreamingFrogProgressSnapshot], None]:
    """Build the callback `ScreamingFrogControlTool`'s progress thread calls.

    A top-level function, not an inline closure, matching
    `worker_daemon.make_approval_callback`'s own reasoning: independently
    testable without starting a thread, launching Screaming Frog, or
    standing up a fake cloud. Deliberately does not catch anything —
    `ProgressPollThread._poll_and_report` already wraps every call to this
    in a broad `except Exception`, logging and moving on; duplicating that
    here would only hide which layer actually decided a lost report is safe
    to drop.
    """

    def _on_progress(snapshot: ScreamingFrogProgressSnapshot) -> None:
        client.report_progress(
            job_id,
            pages_crawled=snapshot.pages_crawled,
            progress_pct=snapshot.progress_pct,
            phase=snapshot.phase,
        )

    return _on_progress
