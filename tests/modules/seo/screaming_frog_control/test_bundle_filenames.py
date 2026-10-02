"""`ISSUE_SOURCE_FILENAMES` is a hand-held copy; this pins it to the catalogue.

The worker may not import `ISSUE_CATALOGUE` (ADR 0030), so the upload
allow-list holds the filenames as literals. Tests ship in no executable and may
import the catalogue, which makes this the one place the two can be compared.
"""

from __future__ import annotations

from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.screaming_frog_control.bundle_filenames import ISSUE_SOURCE_FILENAMES
from src.modules.seo.screaming_frog_control.upload_manifest import (
    ALLOWED_BUNDLE_FILENAMES,
    SPINE_FILENAME,
)


def _catalogue_filenames() -> frozenset[str]:
    return frozenset(name for spec in ISSUE_CATALOGUE for name in spec.sf_sources)


def test_no_catalogue_source_is_missing_from_the_fixed_list() -> None:
    """A deliverable would ask for a file the upload gate silently drops."""
    assert _catalogue_filenames() - ISSUE_SOURCE_FILENAMES == frozenset()


def test_no_fixed_name_is_unknown_to_the_catalogue() -> None:
    """An extra name widens an untrusted upload boundary for nothing."""
    assert ISSUE_SOURCE_FILENAMES - _catalogue_filenames() == frozenset()


def test_the_allow_list_is_unchanged_from_the_catalogue_derivation() -> None:
    """Byte-for-byte the set the import-time derivation used to produce."""
    assert frozenset({SPINE_FILENAME}) | _catalogue_filenames() == ALLOWED_BUNDLE_FILENAMES
