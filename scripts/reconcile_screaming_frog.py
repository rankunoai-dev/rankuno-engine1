"""Reconcile a Screaming Frog export against a stored crawl, from the shell.

    python scripts/reconcile_screaming_frog.py <job-id-or-result.json> <export.csv>
    python scripts/reconcile_screaming_frog.py <job-id> <export.csv> --merge --out merged.json

Reports by default and merges only when asked. The gap is the thing most runs
want to see, and a tool that rewrote the result every time would make "just
check" impossible.

Nothing else in the engine depends on this script. A crawl with no Screaming
Frog export is complete on its own terms; this is an optional cross-check for
operators who happen to have a licence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Importable as a script from the repo root, the same way `run_crawl.py` is.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.modules.seo.page_classifier.screaming_frog_merge import (  # noqa: E402
    merge_reconciled_urls,
)
from src.modules.seo.page_classifier.screaming_frog_reconciler import (  # noqa: E402
    ReconciliationReport,
)
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    PageClassificationOutput,
)

JOBS_DIR = Path(".jobs")
SAMPLE = 15
"""URLs printed per category. The counts are exact; the lists are a sample."""


def _load_result(target: str) -> PageClassificationOutput:
    """Read a crawl result from a path, or from a job id under `.jobs/`.

    Accepting both is not indulgence: the id is what the UI shows and the path
    is what a scripted run has, and requiring a translation step between them is
    the kind of friction that stops a cross-check being run at all.
    """
    candidates = [Path(target), JOBS_DIR / f"{target}.result.json"]
    for path in candidates:
        if path.is_file():
            return PageClassificationOutput.model_validate_json(path.read_text(encoding="utf-8"))
    tried = ", ".join(str(path) for path in candidates)
    raise SystemExit(f"no crawl result found. Tried: {tried}")


def _print_report(report: ReconciliationReport, merged: int) -> None:
    """Write the reconciliation to stdout.

    Output is ASCII on purpose: the Windows console defaults to cp1252 and
    renders an em dash as a replacement character, so a report full of them
    reads as corrupted output rather than as typography.

    `print` is correct here and nowhere else in this codebase: `scripts/` is the
    operator-facing shell surface, and `run_crawl.py` sets the same precedent.
    The ruff `T20` ban applies to `src/`.
    """
    print(f"\nReconciliation - {report.base_url}")
    print("=" * 68)
    print(f"  Screaming Frog rows   {report.frog_rows:>8,}   ({report.frog_live:,} live)")
    print(f"  Rankuno URLs          {report.engine_urls:>8,}")
    print(f"  found by both         {report.in_both:>8,}")

    print(f"\n  Screaming Frog only   {len(report.frog_only):>8,}")
    for reason, count in sorted(report.frog_reasons.items(), key=lambda kv: -kv[1]):
        print(f"      {reason:<24} {count:>6,}")

    print(f"\n  Rankuno only          {len(report.engine_only):>8,}")
    for reason, count in sorted(report.engine_reasons.items(), key=lambda kv: -kv[1]):
        print(f"      {reason:<24} {count:>6,}")

    missed = report.missed_pages
    print(f"\n  PAGES RANKUNO MISSED  {len(missed):>8,}   <- the defect")
    for url in missed[:SAMPLE]:
        print(f"      {url}")
    if len(missed) > SAMPLE:
        print(f"      ... and {len(missed) - SAMPLE:,} more")

    orphans = report.orphans
    print(f"\n  SITEMAP ORPHANS       {len(orphans):>8,}   <- the finding")
    print("      Published, and no internal link reaches them. A link crawler")
    print("      cannot see these by construction; they need internal links.")
    for url in orphans[:SAMPLE]:
        print(f"      {url}")
    if len(orphans) > SAMPLE:
        print(f"      ... and {len(orphans) - SAMPLE:,} more")

    print(f"\n  merged into the tree  {merged:>8,}")


def main() -> int:
    """Parse arguments, reconcile, and optionally write a merged result."""
    parser = argparse.ArgumentParser(
        description="Compare a Screaming Frog export with a Rankuno crawl.",
    )
    parser.add_argument("result", help="job id, or a path to a .result.json")
    parser.add_argument("export", help="path to internal_html.csv")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="fold the missed pages into the tree (default: report only)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the merged result here. Implies --merge.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of a table",
    )
    args = parser.parse_args()

    before = _load_result(args.result)
    export_path = Path(args.export)
    if not export_path.is_file():
        raise SystemExit(f"no export at {export_path}")
    # `utf-8-sig` strips the byte-order mark Screaming Frog writes. Without it
    # the first header never matches "Address" and the export reconciles to
    # nothing at all, silently.
    csv_text = export_path.read_text(encoding="utf-8-sig", errors="replace")

    outcome = merge_reconciled_urls(before, csv_text)

    if args.json:
        print(json.dumps(outcome.report.model_dump(mode="json"), indent=2))
    else:
        _print_report(outcome.report, outcome.merged if (args.merge or args.out) else 0)

    if args.out or args.merge:
        destination = args.out or Path("merged.result.json")
        destination.write_text(
            json.dumps(outcome.output.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        if not args.json:
            print(f"\n  wrote {destination}  ({len(outcome.output.pages):,} pages)")
    elif not args.json:
        print("\n  Report only. Pass --merge to fold the missed pages in.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
