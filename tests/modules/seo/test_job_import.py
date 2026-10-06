"""`prepare_import`: bytes in, a validated terminal job out (ADR 0034)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from src.core.bounded_gzip import DecompressedTooLargeError, InvalidGzipError
from src.core.state_store import JobStatus
from src.modules.seo.page_classifier.job_import import (
    MAX_REPORTED_LOCATIONS,
    BundleInvalidError,
    prepare_import,
)
from src.modules.seo.page_classifier.tool import PageClassificationOutput

from tests.modules.seo.job_bundle_factory import (
    FINISHED,
    INSTANCE_ID,
    SOURCE_JOB_ID,
    STARTED,
    bundle_dict,
    gz,
)

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
CAP = 8 * 1024 * 1024


def _prepare(body: bytes, cap: int = CAP):  # noqa: ANN202
    return prepare_import(body, max_decompressed=cap, org_id="org-a", operator_id="alice", now=NOW)


class TestHappyPath:
    def test_builds_a_terminal_job_from_server_side_facts(self) -> None:
        data = bundle_dict()
        raw = json.dumps(data).encode()
        prepared = _prepare(gz(raw))
        job = prepared.job

        assert job.org_id == "org-a"
        assert job.tool_name == job.facet_id == "seo.page_classifier"
        assert job.status is JobStatus.SUCCEEDED
        assert (job.started_at, job.finished_at) == (STARTED, FINISHED)
        assert job.telemetry.completed == 2
        assert job.telemetry.discovered == 2
        assert job.homepage_html == data["homepage_html"]
        provenance = job.provenance
        assert provenance.origin == "local_import"
        assert provenance.source_instance_id == INSTANCE_ID
        assert provenance.source_job_id == SOURCE_JOB_ID
        assert provenance.imported_by == "alice"
        assert provenance.imported_at == NOW
        assert provenance.bundle_sha256 == hashlib.sha256(raw).hexdigest()
        assert prepared.page_count == 2
        assert prepared.decompressed_bytes == len(raw)

    def test_the_stored_result_is_reserialised_from_the_validated_model(self) -> None:
        prepared = _prepare(gz(bundle_dict()))
        parsed = PageClassificationOutput.model_validate_json(prepared.result_json)
        assert prepared.result_json == parsed.model_dump_json()

    def test_a_partial_keeps_its_reason(self) -> None:
        prepared = _prepare(gz(bundle_dict(status="partial", error="memory budget reached")))
        assert prepared.job.status is JobStatus.PARTIAL
        assert prepared.job.error == "memory budget reached"

    def test_the_label_falls_back_to_the_site(self) -> None:
        assert _prepare(gz(bundle_dict(label=""))).job.label == "https://example.com/"


class TestRefusals:
    def test_a_gzip_bomb_stops_at_the_cap(self) -> None:
        bomb = gz(b"{" + b" " * (4 * 1024 * 1024) + b"}")
        assert len(bomb) < 10_000
        with pytest.raises(DecompressedTooLargeError):
            _prepare(bomb, cap=1024 * 1024)

    def test_not_gzip_is_refused(self) -> None:
        with pytest.raises(InvalidGzipError):
            _prepare(json.dumps(bundle_dict()).encode())

    def test_deep_nesting_is_a_validation_error_not_a_crash(self) -> None:
        depth = 100_000
        nested = b'{"a":' * depth + b"1" + b"}" * depth
        with pytest.raises(BundleInvalidError) as caught:
            _prepare(gz(nested))
        assert caught.value.error_count >= 1

    def test_a_contract_failure_reports_locations_never_values(self) -> None:
        data = bundle_dict(org_id="SECRET_ORG_VALUE")
        data["result"]["pages"][0]["final_confidence_score"] = "SECRET_INPUT_VALUE"
        with pytest.raises(BundleInvalidError) as caught:
            _prepare(gz(data))
        error = caught.value
        assert error.error_count == 2
        assert "org_id" in error.locations
        assert "result.pages[0].final_confidence_score" in error.locations
        assert "SECRET" not in repr(error.locations) + str(error)
        # `from None`: no chained ValidationError carrying the input.
        assert error.__cause__ is None
        assert error.__suppress_context__ is True

    def test_a_javascript_url_refuses_the_whole_bundle(self) -> None:
        data = bundle_dict()
        data["result"]["pages"][1]["url"] = "javascript:alert(1)"
        with pytest.raises(BundleInvalidError) as caught:
            _prepare(gz(data))
        assert caught.value.locations == ["result.pages[1].url"]

    def test_reported_locations_are_bounded(self) -> None:
        data = bundle_dict()
        data["result"]["pages"] = data["result"]["pages"] * 20
        for page in data["result"]["pages"]:
            page["url"] = "javascript:x"
        with pytest.raises(BundleInvalidError) as caught:
            _prepare(gz(data))
        assert caught.value.error_count == 40
        assert len(caught.value.locations) == MAX_REPORTED_LOCATIONS
