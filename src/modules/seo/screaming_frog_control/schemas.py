"""StrictModel contracts for the Screaming Frog CLI governance boundary.

ADR 0013 conditions 4-8. Every value that crosses the API <-> tool boundary is
one of these models; nothing here is a loose dict (CLAUDE.md §1.2).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from pydantic import Field

from src.core.schemas import StrictModel
from src.core.worker_dispatch_schemas import WorkerJobPhase

__all__ = [
    "FIELD_MAPPING",
    "FieldMappingEntry",
    "FieldMappingStatus",
    "LicenceStatus",
    "ScreamingFrogJobInput",
    "ScreamingFrogJobOutput",
    "ScreamingFrogProgressSnapshot",
    "ScreamingFrogTemplate",
]


class FieldMappingStatus(StrEnum):
    """How confidently a UI field's Screaming Frog counterpart is known.

    ADR 0013 condition 5: "No CLI flag or `.seospiderconfig` key may be
    assumed correct without that marker."
    """

    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    NO_MAPPING = "no_mapping"


class FieldMappingEntry(NamedTuple):
    """One row of the condition-5 field-mapping table."""

    ui_field: str
    status: FieldMappingStatus
    note: str


FIELD_MAPPING: tuple[FieldMappingEntry, ...] = (
    FieldMappingEntry(
        "seed_url",
        FieldMappingStatus.VERIFIED,
        "--crawl <url>, confirmed against a real CLI run.",
    ),
    FieldMappingEntry(
        "template_name",
        FieldMappingStatus.VERIFIED,
        "--config <path>, resolved by name via TemplateRegistry — the "
        "substitute mapping this condition is satisfied by (see "
        "ScreamingFrogTemplate below), not a per-field CLI flag.",
    ),
    FieldMappingEntry(
        "max_pages",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag or documented .seospiderconfig key limits crawl size; "
        "confirmed against --help output and Screaming Frog's public docs.",
    ),
    FieldMappingEntry(
        "max_depth",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; depth is a GUI/.seospiderconfig-only crawl limit.",
    ),
    FieldMappingEntry(
        "respect_robots",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; robots.txt handling is a .seospiderconfig-only setting "
        "this engine cannot author (see ScreamingFrogTemplate).",
    ),
    FieldMappingEntry(
        "user_agent",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; the user agent string is a .seospiderconfig-only setting.",
    ),
    FieldMappingEntry(
        "js_rendering",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; JavaScript rendering mode is a .seospiderconfig-only setting.",
    ),
    FieldMappingEntry(
        "speed",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; crawl speed/thread count is a .seospiderconfig-only "
        "setting — no engine-side AsyncTokenBucket accounting may be implied "
        "for it (condition 5's explicit warning).",
    ),
    FieldMappingEntry(
        "exclude",
        FieldMappingStatus.NO_MAPPING,
        "No CLI flag; URL exclusion patterns are a .seospiderconfig-only setting.",
    ),
)
"""ADR 0013 condition 5's explicit field mapping, one row per named UI field
plus the two fields this tool's own input model carries. Every crawl-form
field a human operator might expect to configure (max_pages, max_depth,
respect_robots, user_agent, js_rendering, speed, exclude) is `NO_MAPPING`:
none has a Screaming Frog CLI flag, confirmed against a real
`ScreamingFrogSEOSpiderCli.exe --help` dump and Screaming Frog's own public
documentation. `tests/modules/seo/screaming_frog_control/test_schemas.py`
pins that every entry carries a non-empty note and a real status."""


class ScreamingFrogTemplate(StrictModel):
    """One pre-authored `.seospiderconfig` an operator may select by name.

    ADR 0013 condition 5's field mapping is satisfied this way rather than by
    a per-field CLI mapping: none of the existing crawl-form fields
    (max_pages, max_depth, respect_robots, user_agent, JS rendering, speed,
    exclude) has a Screaming Frog CLI counterpart — confirmed against the
    real CLI's `--help` output and Screaming Frog's own public docs. The
    mapping this engine offers instead is `template name -> config file
    path`, authored once by a human inside the real Screaming Frog GUI: a
    `.seospiderconfig` is a Java `ObjectInputStream`-serialised file that this
    engine cannot generate or hand-author as text (see
    `docs/adr/0013-screaming-frog-cli-process-governance-exception.md`).
    """

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(default="", max_length=500)


class LicenceStatus(StrictModel):
    """What Screaming Frog's own log said about this run's licence.

    A Screaming Frog licence expiry is a silent degrade: the crawl keeps
    running, capped at 500 URLs, with no crash and no distinct exit code
    (verified: this workstation's `crash.txt` records only unrelated JVM/config
    crashes, never a licence failure). Detection is therefore positive parsing
    of two log lines, not exception handling around a call that never raises
    (ADR 0013 condition 6).

    Attributes:
        active: Whether the "Licence Status:" line said "Active". `False`
            (fail closed) when the line never appeared — a killed or crashed
            process leaves no evidence of an active licence, and silence must
            not be read as success.
        raw_line: The exact log line, kept for the operator-facing error and
            so a human can diff it against a future Screaming Frog release.
        pages_crawled: Pages the "Completed the spider of..." line reported.
            `None` if the run never reached that line.
        free_tier_capped: `True` when `pages_crawled` lands exactly on the
            500-URL free-tier ceiling — the only observable symptom of the
            silent degrade. A real 500-page site with a valid licence would
            also trip this; the ADR accepts that false positive over silently
            shipping a truncated bundle as complete.
    """

    active: bool
    raw_line: str | None = None
    pages_crawled: int | None = Field(default=None, ge=0)
    free_tier_capped: bool = False


class ScreamingFrogJobInput(StrictModel):
    """What `ScreamingFrogControlTool.execute()` needs to launch one crawl.

    Attributes:
        seed_url: Already passed through `UrlSafetyPolicy.validate()` by the
            API admission layer (ADR 0013 condition 4) and re-checked by
            `execute()` for defense in depth. Screaming Frog's own subsequent
            redirects and discovered links are explicitly NOT covered by
            either check (ADR 0013 decision 3): they run inside a process
            this engine does not control.
        template_name: Selects a `.seospiderconfig` by name via
            `TemplateRegistry`. `None` runs Screaming Frog's own persisted
            defaults with no `--config` flag at all.
    """

    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)


class ScreamingFrogJobOutput(StrictModel):
    """What one governed Screaming Frog run produced.

    Attributes:
        bundle_dir: Where the CSV export bundle was written. Handed to
            `load_screaming_frog_bundle` unchanged (ADR 0013 decision 4) —
            this tool does not parse the CSVs itself, only produces them.
        licence: The licence read for this run. Only ever `active=True` and
            not `free_tier_capped` here — any other value raises
            `ScreamingFrogLicenceError` in `execute()` instead of reaching
            this model, so a caller never mistakes a degraded run for a
            complete one (ADR 0013 condition 6).
        elapsed_s: Wall-clock time the supervised process ran.
    """

    bundle_dir: Path
    licence: LicenceStatus
    elapsed_s: float = Field(ge=0.0)


class ScreamingFrogProgressSnapshot(StrictModel):
    """One point-in-time read of a running crawl's progress.

    Built by `progress_parser.parse_latest_progress` from Screaming Frog's
    own `SpiderProgress` trace.txt line (verified live against a real 19.4
    headless run, 2026-09-22 — see that module's docstring for the exact
    captured format). Uses `WorkerJobPhase` from `core` directly, not a
    module-local phase enum: this model's only consumer outside this module
    is `worker_daemon`'s progress-reporting callback, which hands `phase`
    straight to `WorkerCloudClient.report_progress` unconverted, and
    `WorkerJob.current_phase` on the receiving end is typed `WorkerJobPhase`
    already — an extra module-local enum would exist only to be converted
    right back.

    Attributes:
        pages_crawled: Screaming Frog's own live count of completed pages.
            `None` before the first `SpiderProgress` line has appeared.
        progress_pct: Screaming Frog's own live completion estimate. Not
            guaranteed to increase monotonically (see
            `WorkerJob.progress_pct`'s own docstring) — this snapshot
            records whatever the log said, unmodified.
        phase: `CRAWLING` once any `SpiderProgress` line has been seen this
            run; `EXPORTING` once the `Completed the spider of...` line has
            also been seen. `progress_parser.parse_latest_progress` never
            constructs a snapshot at all until one of those is true, so in
            practice this is never `None` on an instance that exists — it
            stays optional here only because `StrictModel` gives every
            other field on this class the same treatment, and a future
            caller building one directly (e.g. a test fixture) should not
            be forced to supply a phase it does not have yet.
    """

    pages_crawled: int | None = Field(default=None, ge=0)
    progress_pct: float | None = Field(default=None, ge=0.0)
    phase: WorkerJobPhase | None = None
