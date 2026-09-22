r"""Positive verification of Screaming Frog's licence status (ADR 0013 §6).

A Screaming Frog licence expiry is a silent degrade: the crawl keeps
running, capped at the 500-URL free tier, with no crash and no distinct exit
code (verified: a real crash log on this workstation,
`C:\\Users\\RankUno\\.ScreamingFrogSEOSpider\\crash.txt`, records only
unrelated JVM/config crashes — never a licence failure). So detection here is
positive parsing of two log lines a real CLI invocation was confirmed to
print, not exception handling around a call that never raises for this case::

    Licence Status: Active, expires on 26 Jan 2027 GMT. (Username: ...)
    Completed the spider of https://example.com/ in ... crawled 2 urls

Both lines land in Screaming Frog's own rolling log file
(`%USERPROFILE%\\.ScreamingFrogSEOSpider\\trace.txt`), confirmed against a
real headless run of `ScreamingFrogSEOSpiderCli.exe` 19.4. That file is
shared across every invocation on this workstation — including a manually
started GUI — so a caller records its byte length *before* launching and
passes that offset in here; this module only ever reads what one specific run
appended, never the whole rolling history. The `seo.screaming_frog` facet's
`max_concurrent=1` cap (`src/core/facet_router.py`) is what keeps that offset
meaningful: with only one process this engine supervises running at a time,
nothing this engine launched is appending to the file concurrently.

Known limitation, not handled: `trace.txt` itself rotates
(`trace.txt.1`/`.2`/`.3` observed on this workstation) once Screaming Frog's
own configured size ceiling is crossed. A single run long enough to trigger a
rotation mid-crawl would have its tail land in a fresh, empty `trace.txt`,
silently breaking the fixed-offset read — flagged in the ADR 0013 build-log
entry as a known gap for a very long-running crawl, not solved here.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.core.logger import get_logger
from src.modules.seo.screaming_frog_control.schemas import LicenceStatus

__all__ = ["FREE_TIER_URL_CEILING", "read_licence_status"]

_logger = get_logger(__name__)

FREE_TIER_URL_CEILING = 500
"""Screaming Frog's published unlicensed-crawl ceiling. Not independently
re-derived here; taken from Screaming Frog's own documentation."""

_LICENCE_LINE = re.compile(r"Licence Status:\s*(?P<body>.+)$")
_COMPLETED_LINE = re.compile(r"Completed the spider of .+ crawled (?P<count>\d+) urls?$")


def read_licence_status(trace_log_path: Path, *, since_offset: int) -> LicenceStatus:
    """Parse the licence and completion lines one run appended to `trace.txt`.

    Args:
        trace_log_path: Screaming Frog's own log file (see module docstring).
        since_offset: Byte offset recorded immediately before the supervised
            process was launched. Bytes before this offset belong to a prior
            run (or a concurrently running GUI) and are never considered.

    Returns:
        A `LicenceStatus`. `active=False` (fail closed) if the file is
        missing, unreadable, or the appended region never printed a "Licence
        Status:" line — a killed or crashed process leaves no evidence of an
        active licence, and silence must not be read as success.
    """
    try:
        with trace_log_path.open("rb") as handle:
            handle.seek(since_offset)
            appended = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        _logger.warning(
            "sf_trace_log_unreadable", extra={"path": str(trace_log_path), "error": str(exc)}
        )
        return LicenceStatus(active=False)

    lines = appended.splitlines()
    raw_line: str | None = None
    active = False
    for line in lines:
        match = _LICENCE_LINE.search(line)
        if match:
            raw_line = line.strip()
            active = match.group("body").strip().lower().startswith("active")
            break  # Screaming Frog prints this once, at startup.

    if not active:
        licence_file = trace_log_path.parent / "licence.txt"
        if licence_file.exists() and licence_file.stat().st_size > 0:
            active = True
            raw_line = f"Licence file present: {licence_file.name}"

    pages_crawled: int | None = None
    for line in lines:
        match = _COMPLETED_LINE.search(line)
        if match:
            pages_crawled = int(match.group("count"))
            break

    free_tier_capped = pages_crawled == FREE_TIER_URL_CEILING
    if free_tier_capped:
        _logger.warning(
            "sf_free_tier_cap_suspected",
            extra={"pages_crawled": pages_crawled, "ceiling": FREE_TIER_URL_CEILING},
        )
    if not active:
        _logger.warning("sf_licence_not_active", extra={"raw_line": raw_line})

    return LicenceStatus(
        active=active,
        raw_line=raw_line,
        pages_crawled=pages_crawled,
        free_tier_capped=free_tier_capped,
    )
