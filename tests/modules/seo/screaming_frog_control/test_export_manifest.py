"""Tests for the `--export-tabs` / `--bulk-export` manifest.

The load-bearing property under test: every `sf_sources` filename
`catalogue.py` declares is producible by exactly one argument in this
manifest, using the naming transform Screaming Frog was confirmed (against a
real CLI run) to apply. This is what stops the manifest silently drifting out
of sync with the catalogue it exists to feed.
"""

from __future__ import annotations

import re

from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.deliverables.screaming_frog_adapter import SPINE_FILE
from src.modules.seo.screaming_frog_control.export_manifest import (
    BULK_EXPORT,
    EXPORT_TABS,
    SPINE_TAB,
)

# The exact transform Screaming Frog was observed to apply to an argument
# string to produce its output filename (see export_manifest.py's module
# docstring for the five real CLI runs this was verified against).
_STRIP_CHARS = ("-", "<", ">", "&")


def _expected_filename(arg: str, *, last_segment_only: bool) -> str:
    """Reproduce Screaming Frog's own argument -> filename transform.

    Args:
        arg: An `--export-tabs` or `--bulk-export` argument string.
        last_segment_only: `True` for `--bulk-export`, whose menu-category
            prefix (one or two leading `:`-separated segments — confirmed
            live for both shapes) never contributes to the filename, only
            the true export name does. `False` for `--export-tabs`, whose
            "Tab:Filter" is the compound identity and uses both parts.
    """
    segment = arg.split(":")[-1] if last_segment_only else arg
    text = segment.lower()
    for ch in _STRIP_CHARS:
        text = text.replace(ch, "")
    text = text.replace(".", "_")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ", "_").replace(":", "_")
    text = re.sub(r"_+", "_", text)
    return text + ".csv"


# The five threshold-based filenames embed a number Screaming Frog's live
# config supplies (verified for the H1 case only; see the module docstring's
# needs-verification note) rather than the literal "x" the CLI's --help shows.
_THRESHOLD_OVERRIDES = {
    "H1:Over X Characters": "h1_over_70_characters.csv",
    "Meta Description:Below X Pixels": "meta_description_below_400_pixels.csv",
    "Meta Description:Over X Pixels": "meta_description_over_985_pixels.csv",
    "Page Titles:Below X Pixels": "page_titles_below_200_pixels.csv",
    "Page Titles:Over X Pixels": "page_titles_over_561_pixels.csv",
}


class TestManifestCoversTheCatalogue:
    def test_every_catalogue_source_file_is_producible_by_one_argument(self) -> None:
        producible = {
            _THRESHOLD_OVERRIDES.get(arg, _expected_filename(arg, last_segment_only=False))
            for arg in EXPORT_TABS
        } | {_expected_filename(arg, last_segment_only=True) for arg in BULK_EXPORT}
        catalogue_files = {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources}

        missing = catalogue_files - producible
        assert not missing, f"catalogue sf_sources with no manifest argument: {sorted(missing)}"

    def test_spine_tab_produces_the_adapters_spine_filename(self) -> None:
        assert _expected_filename(SPINE_TAB, last_segment_only=False) == SPINE_FILE

    def test_no_argument_is_listed_twice_within_export_tabs(self) -> None:
        assert len(EXPORT_TABS) == len(set(EXPORT_TABS))

    def test_no_argument_is_listed_twice_within_bulk_export(self) -> None:
        assert len(BULK_EXPORT) == len(set(BULK_EXPORT))

    def test_export_tabs_and_bulk_export_share_no_argument(self) -> None:
        assert set(EXPORT_TABS).isdisjoint(BULK_EXPORT)
