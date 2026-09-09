"""Client deliverables: adapters that produce an `AuditDataset` (ADR 0011).

This package imports `contracts` and `core` only. It must never import
`page_classifier`; the two are joined by the `AuditDataset` model, not by code.
Phase 0 ships the Screaming Frog adapter; Phase 1 adds the rulebook engine;
the workbook engine is Phase 2.
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

__all__ = [
    "MAX_BUNDLE_UNCOMPRESSED_BYTES",
    "MAX_COLUMNS",
    "MAX_LINE_CHARS",
    "MAX_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_ROWS_PER_FILE",
    "MAX_ZIP_MEMBERS",
    "OTHERS_THEME",
    "PRIORITY_NOT_APPLICABLE",
    "RULEBOOK_SHEET_NAME",
    "SPINE_FILE",
    "Classification",
    "NormalizerContractError",
    "Rule",
    "Rulebook",
    "RulebookError",
    "RulebookMissingError",
    "RuleType",
    "ScreamingFrogBundleError",
    "apply_rulebook",
    "load_screaming_frog_bundle",
]
