"""The delete-password hash must never reach a client.

`JobRecord.password_hash` is persisted by the job stores, so it cannot be
excluded on the model itself; routes return `JobView` instead. These tests pin
both halves: the view omits the hash, and the store still keeps it.
"""

from __future__ import annotations

import typing

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from src.api import server as server_module
from src.api.job_view import JobView, job_views
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore, JobRecord
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.tool import CrawlSummary, PageClassificationOutput
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
HASH = "pbkdf2_sha256$210000$c2FsdA$ZGlnZXN0"
BASE = "https://e.com/"


def _contains_model(annotation: object, target: type[BaseModel]) -> bool:
    """Whether `target` appears anywhere inside a (possibly generic) annotation."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation is target or any(
            _contains_model(field.annotation, target) for field in annotation.model_fields.values()
        )
    return any(_contains_model(arg, target) for arg in typing.get_args(annotation))


def _output() -> dict[str, object]:
    return PageClassificationOutput(
        base_url=BASE,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(base_url=BASE),
        summary=CrawlSummary(),
        pages=(),
    ).model_dump(mode="json")


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def app(store, tmp_path):
    return create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda h: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        deliverable_jobs_root=tmp_path / "deliverables",
    )


def _record(store: DiskJobStore, password_hash: str | None = HASH) -> JobRecord:
    return store.create(
        server_module.TOOL_NAME, {"base_url": BASE}, label="e.com", password_hash=password_hash
    )


def test_job_view_has_no_password_hash_field(store):
    record = _record(store)
    assert "password_hash" not in JobView.model_fields
    assert "password_hash" not in JobView.from_record(record).model_dump()
    assert HASH not in JobView.from_record(record).model_dump_json()


def test_job_view_has_delete_password_true_when_hash_set(store):
    assert JobView.from_record(_record(store)).has_delete_password is True


def test_job_view_has_delete_password_false_when_none(store):
    assert JobView.from_record(_record(store, None)).has_delete_password is False


def test_job_view_covers_every_other_record_field():
    assert set(JobRecord.model_fields) - {"password_hash"} <= set(JobView.model_fields)


def test_job_views_preserves_order(store):
    first, second = _record(store), _record(store, None)
    assert [v.id for v in job_views([first, second])] == [first.id, second.id]


def test_disk_store_still_persists_hash(store, tmp_path):
    record = _record(store)
    assert store.get(record.id).password_hash == HASH
    assert DiskJobStore(tmp_path / "jobs").get(record.id).password_hash == HASH


def test_every_jobrecord_route_omits_password_hash(app, store, tmp_path):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.response_model is not None:
            assert not _contains_model(route.response_model, JobRecord), route.path

    deliverable = DiskJobStore(tmp_path / "deliverables").create(
        "seo.deliverable", {"x": "y"}, password_hash=HASH
    )
    finished = _record(store)
    store.finish(finished.id, _output())
    with TestClient(app, headers=auth_headers()) as client:
        # Created after startup: boot-time orphan recovery fails any queued job.
        queued = _record(store)
        responses = [
            client.get(f"{API_PREFIX}/jobs"),
            client.get(f"{API_PREFIX}/jobs/{finished.id}"),
            client.post(f"{API_PREFIX}/jobs/{finished.id}/reparse"),
            client.post(f"{API_PREFIX}/jobs/{queued.id}/cancel"),
            client.get(f"{API_PREFIX}/deliverables"),
            client.get(f"{API_PREFIX}/deliverables/{deliverable.id}"),
        ]

    for response in responses:
        assert response.status_code == 200, response.text
        assert "password_hash" not in response.text
        assert "pbkdf2_sha256$" not in response.text
    assert responses[1].json()["has_delete_password"] is True
    assert responses[5].json()["has_delete_password"] is True
