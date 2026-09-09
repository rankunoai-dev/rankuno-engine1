"""Client deliverables: adapters that produce an `AuditDataset` (ADR 0011).

This package imports `contracts` and `core` only. It must never import
`page_classifier`; the two are joined by the `AuditDataset` model, not by code.
Phase 0 ships the Screaming Frog adapter; Phase 1 adds the rulebook engine;
Phase 2a/2b add per-category scoring and the workbook generator. The upload
endpoint that would move a workbook off this workstation is still deferred.
"""

from src.modules.seo.deliverables.rulebook import (
    OTHERS_THEME,
    PRIORITY_NOT_APPLICABLE,
    RULEBOOK_SHEET_NAME,
    Classification,
    Rule,
    Rulebook,
    RulebookError,
    RulebookMissingError,
    RuleType,
    apply_rulebook,
)
from src.modules.seo.deliverables.scoring import (
    SEVERITY_WEIGHTS,
    CategoryPenalty,
    IssuePenalty,
    ScoringResult,
    get_severity_weights,
    score_dataset,
)
from src.modules.seo.deliverables.screaming_frog_adapter import (
    MAX_BUNDLE_UNCOMPRESSED_BYTES,
    MAX_COLUMNS,
    MAX_LINE_CHARS,
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    MAX_ROWS_PER_FILE,
    MAX_ZIP_MEMBERS,
    SPINE_FILE,
    NormalizerContractError,
    ScreamingFrogBundleError,
    load_screaming_frog_bundle,
)
from src.modules.seo.deliverables.workbook import (
    MAX_PAGES_PER_WORKBOOK,
    SHEET_ISSUES,
    SHEET_NOTES,
    SHEET_OVERVIEW,
    SHEET_PAGES,
    WorkbookBuildError,
    build_workbook,
)

__all__ = [
    "MAX_BUNDLE_UNCOMPRESSED_BYTES",
    "MAX_COLUMNS",
    "MAX_LINE_CHARS",
    "MAX_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_PAGES_PER_WORKBOOK",
    "MAX_ROWS_PER_FILE",
    "MAX_ZIP_MEMBERS",
    "OTHERS_THEME",
    "PRIORITY_NOT_APPLICABLE",
    "RULEBOOK_SHEET_NAME",
    "SEVERITY_WEIGHTS",
    "SHEET_ISSUES",
    "SHEET_NOTES",
    "SHEET_OVERVIEW",
    "SHEET_PAGES",
    "SPINE_FILE",
    "CategoryPenalty",
    "Classification",
    "IssuePenalty",
    "NormalizerContractError",
    "Rule",
    "Rulebook",
    "RulebookError",
    "RulebookMissingError",
    "RuleType",
    "ScoringResult",
    "ScreamingFrogBundleError",
    "WorkbookBuildError",
    "apply_rulebook",
    "build_workbook",
    "get_severity_weights",
    "load_screaming_frog_bundle",
    "score_dataset",
]
