"""Run one workbook build to completion against a `DiskJobStore` (cycle 0087).

The business logic behind the API's async build endpoints lives here, not in
`src/api/deliverables_routes.py`: a route validates a request and dispatches
work, it does not decide how a build fails. `run_build` is the one function
both build-triggering endpoints call, after they have already loaded (or
deferred loading) their own `AuditDataset` - engine-crawl and Screaming-Frog
sources stay symmetric with `run_deliverable_pipeline` for the same reason
`pipeline.py`'s own docstring gives for not loading a source itself.

Two seam rules this file exists to keep:

* `deliverables/` may not import `page_classifier` (ADR 0011 d.1). The engine
  source's loader (`to_audit_dataset`) and its normaliser (`normalize_url`)
  both live on the `page_classifier` side, so neither is imported here -
  `dataset_loader` and `normalize` arrive as parameters from a caller in
  `src/api/`, the one layer allowed to import both sides, the same pattern
  `scripts/build_deliverable.py` already uses.
* Every build-failure type this module can see - `AuditExportError`,
  `RulebookError`, `ScreamingFrogBundleError`, `WorkbookBuildError` - is a
  `ValueError` subclass. Catching `ValueError` here (after the one subclass
  worth distinguishing) reports every one of them correctly without importing
  a single one, which is what keeps this file on the right side of the first
  rule without hand-maintaining an import list that mirrors it.

Imports `core.state_store.DiskJobStore` directly rather than the `JobStore`
Protocol: a build needs a real filesystem root to write its workbook under
(`deliverable_store.root / deliverable_id`), which the Protocol does not
promise.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.core.logger import get_logger
from src.core.state_store import DiskJobStore
from src.modules.seo.contracts.audit import AuditDataset
from src.modules.seo.contracts.url_normalizer import UrlNormalizer
from src.modules.seo.deliverables.pipeline import run_deliverable_pipeline
from src.modules.seo.deliverables.workbook import WorkbookPageLimitExceededError

__all__ = ["run_build"]

_logger = get_logger(__name__)


def run_build(
    deliverable_store: DiskJobStore,
    deliverable_id: str,
    dataset_loader: Callable[[], AuditDataset],
    normalize: UrlNormalizer,
    rulebook_path: Path | None,
    source: str,
) -> None:
    """Load a dataset, theme/score/render it, and record the outcome.

    Intended to run on a worker thread, dispatched by
    `deliverables_routes._dispatch_build` - never on the event loop. Never
    raises: a caller that loses the exception here would leave the
    deliverable `running` forever with nothing to move it, the same contract
    `server.py`'s `_run_job` keeps for a crawl.

    Args:
        deliverable_store: Where this deliverable's record and workbook live.
        deliverable_id: The record to update.
        dataset_loader: Builds the `AuditDataset` to render. Called here, on
            the worker thread, so a slow parse (a large Screaming Frog bundle)
            costs the same thread the workbook write already does, never the
            event loop. May raise `AuditExportError` or
            `ScreamingFrogBundleError`; both are handled below by type,
            neither by name (see the module docstring).
        normalize: URL normaliser satisfying `UrlNormalizer`; must be the same
            function that keyed the dataset `dataset_loader` will return, so
            rulebook pattern matching sees URLs spelled the same way.
        rulebook_path: Path to a validated rulebook `.xlsx`, or `None` to
            skip theming entirely.
        source: `"engine"` or `"screaming_frog"`, recorded on the finished
            result for display.
    """
    try:
        deliverable_store.mark_running(deliverable_id)
        dataset = dataset_loader()
        output_dir = deliverable_store.root / deliverable_id
        path = run_deliverable_pipeline(
            dataset, normalize=normalize, rulebook_path=rulebook_path, output_dir=output_dir
        )
        deliverable_store.finish(
            deliverable_id,
            {
                "filename": path.name,
                "site": dataset.site,
                "pages": len(dataset.pages),
                "source": source,
                "produced_at": dataset.produced_at.isoformat(),
            },
        )
        _logger.info(
            "deliverable_built",
            extra={"deliverable_id": deliverable_id, "pages": len(dataset.pages), "source": source},
        )
    except WorkbookPageLimitExceededError as exc:
        # Distinguished from a generic build failure per the Step 5 audit: a
        # caller (or a person reading `error` in the job list) can tell "the
        # crawl is too big for one workbook" from "the write itself failed"
        # without parsing a message string.
        deliverable_store.mark_failed(deliverable_id, f"too many pages for a workbook: {exc}")
    except ValueError as exc:
        # Catches AuditExportError, RulebookError, ScreamingFrogBundleError
        # and any other WorkbookBuildError by their shared base - see the
        # module docstring for why none of them is imported by name here.
        deliverable_store.mark_failed(deliverable_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - a detached worker must not leak
        _logger.exception("deliverable_job_crashed", extra={"deliverable_id": deliverable_id})
        deliverable_store.mark_failed(deliverable_id, f"{type(exc).__name__}: {exc}")
