"""The one function every deliverable-building entry point calls (P1/P2 glue).

`run_deliverable_pipeline` is deliberately thin: it takes an already-built
`AuditDataset`, optionally themes it, scores it, and writes the workbook. It
does **not** load anything, and that omission is the design decision worth
recording, not an oversight.

The two loaders that exist today - `screaming_frog_adapter.load_screaming_frog_bundle`
and `page_classifier.audit_export.to_audit_dataset` - are not symmetric enough
to hide behind one injected callable. They take different argument shapes
(a bundle path plus an optional timestamp vs. a sequence of
`FullPageIntelligenceProfile` plus an optional timestamp), live on opposite
sides of the ADR 0011 seam, and only one of them (`to_audit_dataset`) can be
reached without importing `page_classifier`. A `Callable[[], AuditDataset]`
parameter here would look like it erased that asymmetry; it would not - the
caller would still have to import `page_classifier` to build the callable in
the `engine-crawl` case, so the import boundary the plan draws around
`deliverables/` would be violated one frame further out; the boundary lives
here, at the loaders, not inside the pipeline. `scripts/build_deliverable.py`
is where the two loaders' outputs converge into the one `AuditDataset` shape
this function accepts; that convergence is a script's job, not this module's.

`normalize` is a required keyword rather than an optional one with a default
`page_classifier` import, for the same reason: every caller already built
`dataset` with a normaliser in scope (the loader needed one too), so asking
for it again costs nothing and keeps this module off the forbidden side of
the seam (`tests/modules/seo/test_import_boundary.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from src.modules.seo.contracts.audit import AuditDataset
from src.modules.seo.contracts.catalogue import Severity
from src.modules.seo.contracts.url_normalizer import UrlNormalizer
from src.modules.seo.deliverables.rulebook import Rulebook, apply_rulebook
from src.modules.seo.deliverables.scoring import score_dataset
from src.modules.seo.deliverables.workbook import build_workbook

__all__ = ["run_deliverable_pipeline"]


def run_deliverable_pipeline(
    dataset: AuditDataset,
    *,
    normalize: UrlNormalizer,
    rulebook_path: Path | None = None,
    rulebook_lenient: bool = False,
    weights: Mapping[Severity, int] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Theme (optionally), score, and render `dataset` into a client workbook.

    Args:
        dataset: An already-built `AuditDataset`. Never loaded here - see the
            module docstring for why loading is out of scope.
        normalize: URL normaliser satisfying `UrlNormalizer`; the same
            function that keyed `dataset` in the first place, so rulebook
            pattern matching sees URLs spelled the same way (P1-4).
        rulebook_path: Path to a rulebook `.xlsx`. `None` means no rulebook
            was ever intended for this run - theming is skipped entirely,
            with no error and no note, since there is nothing to report.
        rulebook_lenient: Passed through to `Rulebook.from_xlsx`. Defaults to
            `False`: when a `rulebook_path` is given but the file does not
            exist, that is an error unless the caller explicitly opts into
            leniency (ADR 0011 point 6). Ignored when `rulebook_path` is
            `None`.
        weights: Severity weight vector, passed through to `score_dataset`.
            `None` uses `score_dataset`'s own default.
        output_dir: Directory to write the workbook into, passed through to
            `build_workbook`. `None` uses that function's own default.

    Returns:
        Path to the written `.xlsx` workbook.

    Raises:
        RulebookMissingError: `rulebook_path` is given, does not exist, and
            `rulebook_lenient` is `False`.
        RulebookError: `rulebook_path` exists but cannot be parsed.
        WorkbookBuildError: `dataset.pages` exceeds the workbook's page cap,
            or the write itself failed.
    """
    if rulebook_path is not None:
        rulebook = Rulebook.from_xlsx(rulebook_path, lenient=rulebook_lenient)
        dataset = apply_rulebook(dataset, rulebook, normalize=normalize)

    scoring = score_dataset(dataset, weights=weights)
    return build_workbook(dataset, scoring, output_dir=output_dir)
