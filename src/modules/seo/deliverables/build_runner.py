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

import io
import zipfile
from collections.abc import Callable
from pathlib import Path

from src.core.logger import get_logger
from src.core.state_store import DiskJobStore
from src.modules.seo.contracts.audit import AuditDataset
from src.modules.seo.contracts.url_normalizer import UrlNormalizer
from src.modules.seo.deliverables.masterfile_source import MasterfileSource
from src.modules.seo.deliverables.pipeline import run_deliverable_pipeline
from src.modules.seo.deliverables.workbook import WorkbookPageLimitExceededError

__all__ = ["run_build", "run_masterfile", "run_masterfile_batch"]

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


def run_masterfile(
    deliverable_store: DiskJobStore,
    deliverable_id: str,
    job_id: str,
    service_slug: str,
    source_factory: Callable[[], MasterfileSource],
    rulebook_path: Path | None,
) -> None:
    """Generate one masterfile workbook from a Screaming Frog export.

    Intended to run on a worker thread, dispatched by
    `deliverables_routes._dispatch_masterfile` - never on the event loop.
    Never raises: a caller that loses the exception here would leave the
    deliverable `running` forever with nothing to move it.

    Args:
        deliverable_store: Where this deliverable's record and workbook live.
        deliverable_id: The record to update.
        job_id: The source job ID (for logging and the service's own label).
        service_slug: The masterfile service to invoke (e.g. "meta_description").
        source_factory: Opens the CSV source. A callable, not an open source,
            for the reason `run_build`'s `dataset_loader` is one: opening a zip
            pre-flights every member, and that cost belongs on this thread.
            Whatever it returns is closed here, on every path.
        rulebook_path: Optional path to a rulebook for theme classification.
            Accepted and forwarded; no masterfile service reads it yet.
    """
    from src.modules.seo.deliverables.masterfile_registry import get_masterfile_service

    source: MasterfileSource | None = None
    try:
        deliverable_store.mark_running(deliverable_id)
        source = source_factory()
        service = get_masterfile_service(service_slug, job_id, source, rulebook_path)
        xlsx_bytes = service.generate()

        # Write to output directory
        output_dir = deliverable_store.root / deliverable_id
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{service_slug}.xlsx"
        output_path = output_dir / filename
        output_path.write_bytes(xlsx_bytes)

        deliverable_store.finish(
            deliverable_id,
            {
                "filename": filename,
                "service_slug": service_slug,
                "source": "masterfile",
                "source_job_id": job_id,
            },
        )
        _logger.info(
            "masterfile_built",
            extra={"deliverable_id": deliverable_id, "service": service_slug, "job_id": job_id},
        )
    except ValueError as exc:
        # Catches an unknown service slug, `MasterfileSourceError` and
        # `ScreamingFrogBundleError` by their shared base - see the module
        # docstring for why none of them is imported by name here.
        deliverable_store.mark_failed(deliverable_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - a detached worker must not leak
        _logger.exception("masterfile_job_crashed", extra={"deliverable_id": deliverable_id})
        deliverable_store.mark_failed(deliverable_id, f"{type(exc).__name__}: {exc}")
    finally:
        if source is not None:
            # A zip left open pins its file on Windows and its memory
            # everywhere; the plaintext of an encrypted bundle must not
            # outlive the build that needed it.
            source.close()


def run_masterfile_batch(
    deliverable_store: DiskJobStore,
    deliverable_id: str,
    job_id: str,
    slugs: tuple[str, ...],
    source_factory: Callable[[], MasterfileSource],
    rulebook_path: Path | None,
) -> None:
    """Build every requested masterfile and ZIP them into a single download.

    Same worker-thread contract as `run_masterfile`: never raises, never runs
    on the event loop. Each service that fails is logged and skipped rather
    than aborting the whole batch — the operator gets the seventeen that
    worked rather than nothing because the eighteenth threw.

    Args:
        deliverable_store: Where this deliverable's record and ZIP live.
        deliverable_id: The record to update.
        job_id: The source job ID.
        slugs: The services to build, in the order they appear in the ZIP.
        source_factory: Opens the CSV source (same contract as `run_masterfile`).
        rulebook_path: Optional rulebook.
    """
    from src.modules.seo.deliverables.masterfile_registry import get_masterfile_service

    source: MasterfileSource | None = None
    try:
        deliverable_store.mark_running(deliverable_id)
        source = source_factory()

        buf = io.BytesIO()
        built = 0
        skipped: list[str] = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for slug in slugs:
                try:
                    svc = get_masterfile_service(slug, job_id, source, rulebook_path)
                    xlsx_bytes = svc.generate()
                    zf.writestr(f"{slug}.xlsx", xlsx_bytes)
                    built += 1
                except Exception:  # noqa: BLE001
                    _logger.warning(
                        "masterfile_batch_skip",
                        extra={"deliverable_id": deliverable_id, "slug": slug, "job_id": job_id},
                        exc_info=True,
                    )
                    skipped.append(slug)

        if built == 0:
            deliverable_store.mark_failed(deliverable_id, "every service failed to build")
            return

        output_dir = deliverable_store.root / deliverable_id
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = "masterfiles.zip"
        (output_dir / filename).write_bytes(buf.getvalue())

        deliverable_store.finish(
            deliverable_id,
            {
                "filename": filename,
                "source": "masterfile_batch",
                "source_job_id": job_id,
                "built": built,
                "skipped": skipped,
            },
        )
        _logger.info(
            "masterfile_batch_built",
            extra={
                "deliverable_id": deliverable_id,
                "job_id": job_id,
                "built": built,
                "skipped": len(skipped),
            },
        )
    except ValueError as exc:
        deliverable_store.mark_failed(deliverable_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("masterfile_batch_crashed", extra={"deliverable_id": deliverable_id})
        deliverable_store.mark_failed(deliverable_id, f"{type(exc).__name__}: {exc}")
    finally:
        if source is not None:
            source.close()
