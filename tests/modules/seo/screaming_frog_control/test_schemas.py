"""Tests for the Screaming Frog governance StrictModel contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.modules.seo.screaming_frog_control.schemas import (
    FIELD_MAPPING,
    FieldMappingStatus,
    LicenceStatus,
    ScreamingFrogJobInput,
    ScreamingFrogJobOutput,
    ScreamingFrogTemplate,
)

_UI_FORM_FIELDS_WITH_NO_CLI_COUNTERPART = frozenset(
    {"max_pages", "max_depth", "respect_robots", "user_agent", "js_rendering", "speed", "exclude"}
)


class TestFieldMapping:
    """ADR 0013 condition 5: every entry must carry a real status and a note."""

    def test_every_entry_has_a_real_status_and_a_nonempty_note(self) -> None:
        for entry in FIELD_MAPPING:
            assert isinstance(entry.status, FieldMappingStatus)
            assert entry.note.strip()

    def test_no_field_name_is_listed_twice(self) -> None:
        names = [entry.ui_field for entry in FIELD_MAPPING]
        assert len(names) == len(set(names))

    def test_every_named_crawl_form_field_is_covered_and_marked_no_mapping(self) -> None:
        by_name = {entry.ui_field: entry.status for entry in FIELD_MAPPING}
        for field in _UI_FORM_FIELDS_WITH_NO_CLI_COUNTERPART:
            assert field in by_name, f"{field} is missing from FIELD_MAPPING"
            assert by_name[field] is FieldMappingStatus.NO_MAPPING

    def test_seed_url_and_template_name_are_verified(self) -> None:
        by_name = {entry.ui_field: entry.status for entry in FIELD_MAPPING}
        assert by_name["seed_url"] is FieldMappingStatus.VERIFIED
        assert by_name["template_name"] is FieldMappingStatus.VERIFIED


class TestScreamingFrogTemplate:
    def test_accepts_a_lowercase_slug_name(self) -> None:
        template = ScreamingFrogTemplate(name="acme-standard")
        assert template.name == "acme-standard"
        assert template.description == ""

    def test_rejects_a_name_with_uppercase_or_spaces(self) -> None:
        with pytest.raises(ValidationError):
            ScreamingFrogTemplate(name="Acme Standard")

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ScreamingFrogTemplate(name="acme", extra_field="nope")  # type: ignore[call-arg]


class TestLicenceStatus:
    def test_defaults_are_conservative(self) -> None:
        status = LicenceStatus(active=False)
        assert status.raw_line is None
        assert status.pages_crawled is None
        assert status.free_tier_capped is False

    def test_negative_pages_crawled_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LicenceStatus(active=True, pages_crawled=-1)


class TestScreamingFrogJobInput:
    def test_template_name_is_optional(self) -> None:
        job = ScreamingFrogJobInput(seed_url="https://example.com/")
        assert job.template_name is None

    def test_empty_seed_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScreamingFrogJobInput(seed_url="")

    def test_empty_template_name_is_rejected_rather_than_treated_as_none(self) -> None:
        with pytest.raises(ValidationError):
            ScreamingFrogJobInput(seed_url="https://example.com/", template_name="")


class TestScreamingFrogJobOutput:
    def test_round_trips_through_json_mode_dump(self, tmp_path) -> None:
        output = ScreamingFrogJobOutput(
            bundle_dir=tmp_path / "job-1",
            licence=LicenceStatus(active=True, raw_line="Licence Status: Active", pages_crawled=3),
            elapsed_s=12.5,
        )
        dumped = output.model_dump(mode="json")
        assert dumped["bundle_dir"] == str(tmp_path / "job-1")
        assert dumped["licence"]["active"] is True

    def test_negative_elapsed_is_rejected(self, tmp_path) -> None:
        with pytest.raises(ValidationError):
            ScreamingFrogJobOutput(
                bundle_dir=tmp_path, licence=LicenceStatus(active=True), elapsed_s=-1.0
            )
