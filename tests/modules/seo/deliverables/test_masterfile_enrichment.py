"""The two rules `masterfile_enrichment` exists to state.

Both were latent before build-log 0116: twelve allow-listed exports have no
`Address` column at all, and the two traffic exports can never arrive, so a
zero in an Impressions column was indistinguishable from "we did not look".
"""

from __future__ import annotations

import pandas as pd
import pytest
from src.modules.seo.deliverables.masterfile_enrichment import (
    NOT_MEASURED,
    build_ga4_map,
    build_gsc_map,
    build_internal_map,
    gc,
    normalise_url_column,
    url_column_for,
)

HOME = "https://example.com/"


def reader(frames: dict[str, pd.DataFrame]):  # type: ignore[no-untyped-def]
    """A `Reader` backed by a dict, so no file touches disk."""
    return frames.get


class TestUrlColumn:
    def test_a_page_export_is_keyed_by_address(self) -> None:
        assert url_column_for("page_titles_missing.csv") == "Address"

    def test_an_inlinks_export_is_keyed_by_destination(self) -> None:
        """The inlink file is *about* the page being linked to."""
        assert url_column_for("internal_client_error_(4xx)_inlinks.csv") == "Destination"

    def test_an_offending_markup_export_is_keyed_by_source(self) -> None:
        """The insecure form lives on the source page; that is what to fix."""
        assert url_column_for("form_url_insecure.csv") == "Source"
        assert url_column_for("unsafe_crossorigin_links.csv") == "Source"
        assert url_column_for("protocolrelative_outlinks.csv") == "Source"

    def test_an_unknown_name_defaults_to_address(self) -> None:
        assert url_column_for("something_new.csv") == "Address"

    def test_normalising_an_edge_list_adds_an_address_column(self) -> None:
        frame = pd.DataFrame({"Type": ["Hyperlink"], "Source": [HOME], "Destination": ["/gone"]})

        result = normalise_url_column(frame, "http_urls_inlinks.csv")

        assert result is not None
        assert result["Address"].tolist() == ["/gone"]

    def test_normalising_a_page_export_returns_it_unchanged(self) -> None:
        frame = pd.DataFrame({"Address": [HOME]})

        assert normalise_url_column(frame, "h1_missing.csv") is frame

    def test_a_file_missing_its_expected_column_is_reported_not_guessed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`None` means "not shaped like its name" - never a silent empty set.

        The log call is exercised on purpose: it used to pass the export name
        as `extra={"filename": ...}`, and `filename` is a reserved
        `LogRecord` attribute, so `logging.makeRecord` raised `KeyError`
        instead of emitting the warning. `masterfile_source.py` carried the
        same collision at DEBUG level.
        """
        frame = pd.DataFrame({"Something Else": [HOME]})

        with caplog.at_level("WARNING"):
            assert normalise_url_column(frame, "h1_missing.csv") is None

        assert "masterfile_url_column_missing" in caplog.text


class TestGc:
    def test_it_is_case_insensitive(self) -> None:
        assert gc(["address", "Status Code"], "Address") == 0

    def test_a_missing_column_raises(self) -> None:
        with pytest.raises(KeyError):
            gc(["Address"], "Inlinks")


class TestEnrichmentMaps:
    def test_the_internal_map_carries_status_indexability_and_inlinks(self) -> None:
        frame = pd.DataFrame(
            {
                "Address": [HOME],
                "Status Code": ["200"],
                "Indexability": ["Indexable"],
                "Inlinks": ["7"],
            }
        )

        result = build_internal_map(reader({"internal_all.csv": frame}))

        assert result == {HOME: {"status_code": "200", "indexability": "Indexable", "inlinks": 7}}

    def test_a_non_numeric_inlinks_cell_becomes_none_not_zero(self) -> None:
        frame = pd.DataFrame(
            {
                "Address": [HOME],
                "Status Code": ["200"],
                "Indexability": ["Indexable"],
                "Inlinks": [""],
            }
        )

        result = build_internal_map(reader({"internal_all.csv": frame}))

        assert result is not None
        assert result[HOME]["inlinks"] is None

    def test_an_absent_spine_yields_none(self) -> None:
        assert build_internal_map(reader({})) is None

    def test_a_spine_without_the_join_columns_yields_none(self) -> None:
        frame = pd.DataFrame({"Address": [HOME]})

        assert build_internal_map(reader({"internal_all.csv": frame})) is None

    def test_the_search_console_map_parses_counts(self) -> None:
        frame = pd.DataFrame({"Address": [HOME], "Impressions": ["120"], "Clicks": ["8"]})

        assert build_gsc_map(reader({"search_console_all.csv": frame})) == {
            HOME: {"impressions": 120, "clicks": 8}
        }

    def test_a_blank_count_reads_as_zero(self) -> None:
        frame = pd.DataFrame({"Address": [HOME], "Impressions": [""], "Clicks": ["x"]})

        assert build_gsc_map(reader({"search_console_all.csv": frame})) == {
            HOME: {"impressions": 0, "clicks": 0}
        }

    def test_an_absent_search_console_export_yields_none(self) -> None:
        """Always, today: no manifest requests the tab."""
        assert build_gsc_map(reader({})) is None

    def test_the_ga4_map_parses_sessions(self) -> None:
        frame = pd.DataFrame({"Address": [HOME], "Sessions": ["42.0"]})

        assert build_ga4_map(reader({"analytics_all.csv": frame})) == {HOME: 42}

    def test_an_absent_analytics_export_yields_none(self) -> None:
        assert build_ga4_map(reader({})) is None

    def test_an_empty_frame_yields_none(self) -> None:
        empty = pd.DataFrame({"Address": [], "Sessions": []})

        assert build_ga4_map(reader({"analytics_all.csv": empty})) is None


def test_the_not_measured_string_is_the_one_adr_0011_names() -> None:
    assert NOT_MEASURED == "Not measured by this crawl"
