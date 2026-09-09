"""Build a client deliverable workbook from a Screaming Frog export or an engine crawl.

    python scripts/build_deliverable.py sf-bundle <bundle_path> [--rulebook path.xlsx]
    python scripts/build_deliverable.py engine-crawl <job-id-or-result.json> [--rulebook path.xlsx]

Both subcommands converge on the same call: build one `AuditDataset` from
whichever source was named, then hand it to `run_deliverable_pipeline`. That
convergence is this script's job, not `pipeline.py`'s - `deliverables/` may
not import `page_classifier` (ADR 0011 d.1), so `to_audit_dataset` can only
be reached from a caller on the `page_classifier` side of the seam, which a
shell script is free to be and a library module inside `deliverables/` is not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Importable as a script from the repo root, the same way `run_crawl.py` is.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.modules.seo.contracts.audit import AuditDataset  # noqa: E402
from src.modules.seo.deliverables.pipeline import run_deliverable_pipeline  # noqa: E402
from src.modules.seo.deliverables.rulebook import RulebookError  # noqa: E402
from src.modules.seo.deliverables.screaming_frog_adapter import (  # noqa: E402
    ScreamingFrogBundleError,
    load_screaming_frog_bundle,
)
from src.modules.seo.deliverables.workbook import WorkbookBuildError  # noqa: E402
from src.modules.seo.page_classifier.audit_export import (  # noqa: E402
    AuditExportError,
    to_audit_dataset,
)
from src.modules.seo.page_classifier.tool import PageClassificationOutput  # noqa: E402
from src.modules.seo.page_classifier.url_rules import normalize_url  # noqa: E402

JOBS_DIR = Path(".jobs")


def _load_result(target: str) -> PageClassificationOutput:
    """Read a crawl result from a path, or from a job id under `.jobs/`.

    Duplicated from `reconcile_screaming_frog.py` rather than imported: that
    script's own docstring says nothing else depends on it, and importing a
    private-in-spirit helper across two operator-facing scripts would make
    a change to either one silently risk the other.
    """
    candidates = [Path(target), JOBS_DIR / f"{target}.result.json"]
    for path in candidates:
        if path.is_file():
            return PageClassificationOutput.model_validate_json(path.read_text(encoding="utf-8"))
    tried = ", ".join(str(path) for path in candidates)
    raise SystemExit(f"no crawl result found. Tried: {tried}")


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Flags shared by both subcommands, so `main` need not branch on them."""
    parser.add_argument(
        "--rulebook", type=Path, default=None, help="path to a rulebook .xlsx (default: none)"
    )
    parser.add_argument(
        "--lenient-rulebook",
        action="store_true",
        help="treat a missing --rulebook path as 'no themes' instead of an error",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="directory to write the workbook into"
    )


def _sf_bundle_dataset(bundle: str) -> AuditDataset:
    """Load the Screaming Frog branch's `AuditDataset`, or exit on a bad path."""
    bundle_path = Path(bundle)
    if not bundle_path.exists():
        raise SystemExit(f"no bundle at {bundle_path}")
    return load_screaming_frog_bundle(bundle_path, normalize=normalize_url)


def _engine_crawl_dataset(target: str) -> AuditDataset:
    """Load the engine-crawl branch's `AuditDataset` from a job id or result path."""
    result = _load_result(target)
    return to_audit_dataset(result.pages, produced_at=None)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, build the dataset for the chosen subcommand, and render it.

    Args:
        argv: Argument vector to parse; `None` (the CLI default) parses
            `sys.argv[1:]`. Accepting an explicit vector is what lets a test
            drive both subcommands directly, the same way `argparse` itself
            is meant to be exercised, without shelling out to a subprocess.
    """
    parser = argparse.ArgumentParser(
        description="Build a client deliverable workbook from a Screaming Frog "
        "export or a stored engine crawl.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sf_parser = subparsers.add_parser("sf-bundle", help="build from a Screaming Frog export")
    sf_parser.add_argument("bundle", help="export directory, or a zip of one")
    _add_common_args(sf_parser)

    engine_parser = subparsers.add_parser("engine-crawl", help="build from a stored engine crawl")
    engine_parser.add_argument("result", help="job id, or a path to a .result.json")
    _add_common_args(engine_parser)

    args = parser.parse_args(argv)

    try:
        if args.command == "sf-bundle":
            dataset = _sf_bundle_dataset(args.bundle)
        else:
            dataset = _engine_crawl_dataset(args.result)
        path = run_deliverable_pipeline(
            dataset,
            normalize=normalize_url,
            rulebook_path=args.rulebook,
            rulebook_lenient=args.lenient_rulebook,
            output_dir=args.output_dir,
        )
    except (ScreamingFrogBundleError, AuditExportError, RulebookError, WorkbookBuildError) as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
