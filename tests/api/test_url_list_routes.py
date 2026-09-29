"""End-to-end HTTP tests for the `--crawl-list` dispatch surface (ADR 0022).

What this file exists to prove, in the order the risk runs:

* **Which sources are offered**, and that "Orphans Only" is not offered for a
  crawl nobody has cross-checked — the option is defined by that comparison,
  so offering it would be offering a choice that cannot work.
* **The four-gate hash binding**, end to end and then broken on purpose. The
  tamper test previews one list and confirms another; nothing like it existed
  before this cycle, and without it "approval" would mean a click.
* **IDOR**, on both halves: generating a list from a crawl another org owns,
  and fetching stored bytes as the wrong worker or the wrong org. A crawl's
  URL list is a complete map of a customer's site, and this feature hands it
  to an external binary on somebody's desktop.
* **The concurrency refusal**, which must name what is running rather than
  return a bare 429.

The dispatch store is the same in-memory fake `test_worker_routes.py` uses,
imported rather than copied so the two files cannot disagree about what the
store does. `PostgresWorkerDispatchStore`'s own SQL is covered in
`tests/core/test_postgres_worker_dispatch_store.py`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore, JobRecord
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_auth import DiskWorkerStore
from src.modules.seo.screaming_frog_control.url_list import fingerprint, render_url_list

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.api.test_worker_routes import (
    BUNDLE_SECRET,
    DISPATCH_SECRET,
    PUBLIC_IP,
    _FakeWorkerDispatchStore,
    _register_worker,
    _worker_headers,
)

BASE = "https://example.com/"


def _result(urls: list[str]) -> dict[str, object]:
    """A result blob shaped like `PageClassificationOutput`'s JSON dump.

    Only the two facts this feature reads are populated — the `pages` array
    and its `url` field. Building a full profile per page would make the
    fixture about the classifier rather than about the list.
    """
    return {
        "base_url": BASE,
        "discovery": {"total_urls": len(urls)},
        "pages": [{"url": url, "canonical_url": url} for url in urls],
        "navigation": {"url": "https://example.com/nav-not-a-page"},
    }


@pytest.fixture
def dispatch_store() -> _FakeWorkerDispatchStore:
    return _FakeWorkerDispatchStore()


@pytest.fixture
def job_store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(tmp_path, dispatch_store, job_store) -> TestClient:
    app = create_app(
        store=job_store,
        url_policy=UrlSafetyPolicy(resolver=lambda _host: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        worker_store=DiskWorkerStore(tmp_path / "workers"),
        worker_dispatch_store=dispatch_store,
        dispatch_signing_secret=DISPATCH_SECRET,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def _finished_crawl(
    job_store: DiskJobStore,
    urls: list[str] | None = None,
    *,
    org_id: str = "default",
    label: str = "Crawl: example.com",
) -> JobRecord:
    record = job_store.create(
        "seo.page_classifier",
        {"base_url": BASE},
        label=label,
        org_id=org_id,
    )
    job_store.finish(record.id, _result(urls if urls is not None else ["https://example.com/a"]))
    return job_store.get(record.id)


def _with_reconciliation(job_store: DiskJobStore, job_id: str, orphans: list[str]) -> None:
    job_store.write_reconciliation(job_id, {"summary": {}, "orphans": orphans, "in_both": []})


def _preview(
    client, worker, *, source_job_id=None, source="all", org_id="default"
) -> httpx.Response:
    body: dict[str, object] = {"seed_url": BASE, "correlation_id": "c1"}
    if source_job_id is not None:
        body["url_list"] = {"source_job_id": source_job_id, "source": source}
    return client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json=body,
        headers=auth_headers(org_id=org_id),
    )


def _confirm(client, worker, preview_body, *, sha256=..., org_id="default") -> httpx.Response:
    digest = preview_body.get("url_list", {}).get("sha256") if sha256 is ... else sha256
    body: dict[str, object] = {
        "token": preview_body["token"],
        "seed_url": BASE,
        "correlation_id": "c1",
    }
    if digest is not None:
        body["url_list_sha256"] = digest
    return client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch",
        json=body,
        headers=auth_headers(org_id=org_id),
    )


# --- source discovery ---------------------------------------------------------


class TestSources:
    def test_requires_authentication(self, client, job_store):
        crawl = _finished_crawl(job_store)
        assert client.get(f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources").status_code == 401

    def test_unknown_crawl_is_404(self, client):
        response = client.get(f"{API_PREFIX}/jobs/nope/url-list/sources", headers=auth_headers())
        assert response.status_code == 404

    def test_another_orgs_crawl_is_not_readable(self, client, job_store):
        """IDOR: a crawl's URL list is a complete map of somebody's site."""
        crawl = _finished_crawl(job_store, org_id="other-org")
        response = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        )
        assert response.status_code == 403

    def test_orphans_is_not_offered_without_a_cross_check(self, client, job_store):
        crawl = _finished_crawl(job_store)
        body = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        ).json()
        orphans = next(s for s in body["sources"] if s["source"] == "orphans")
        assert orphans["available"] is False
        assert "cross-check" in orphans["unavailable_reason"]

    def test_orphans_is_offered_once_a_cross_check_exists(self, client, job_store):
        crawl = _finished_crawl(job_store)
        _with_reconciliation(job_store, crawl.id, ["https://example.com/orphan"])
        body = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        ).json()
        orphans = next(s for s in body["sources"] if s["source"] == "orphans")
        assert orphans["available"] is True
        assert orphans["candidate_url_count"] == 1
        assert "(Recommended)" in orphans["label"]

    def test_a_cross_check_that_found_no_orphans_says_so(self, client, job_store):
        crawl = _finished_crawl(job_store)
        _with_reconciliation(job_store, crawl.id, [])
        body = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        ).json()
        orphans = next(s for s in body["sources"] if s["source"] == "orphans")
        assert orphans["available"] is False
        assert orphans["candidate_url_count"] == 0

    def test_all_counts_the_crawls_own_pages_only(self, client, job_store):
        """The `navigation` node's own `url` must not inflate the count."""
        crawl = _finished_crawl(job_store, [f"https://example.com/{n}" for n in range(7)])
        body = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        ).json()
        every = next(s for s in body["sources"] if s["source"] == "all")
        assert every["candidate_url_count"] == 7
        assert every["available"] is True

    def test_an_unfinished_crawl_offers_nothing(self, client, job_store):
        record = job_store.create("seo.page_classifier", {"base_url": BASE}, label="running")
        body = client.get(
            f"{API_PREFIX}/jobs/{record.id}/url-list/sources", headers=auth_headers()
        ).json()
        assert [s["available"] for s in body["sources"]] == [False, False]

    def test_an_oversized_crawl_is_refused_with_the_reason_not_trimmed(
        self, client, job_store, monkeypatch
    ):
        from src.api import url_list_routes

        crawl = _finished_crawl(job_store, [f"https://example.com/{n}" for n in range(20)])
        _shrink_ceiling(monkeypatch, url_list_routes, 5)
        body = client.get(
            f"{API_PREFIX}/jobs/{crawl.id}/url-list/sources", headers=auth_headers()
        ).json()
        every = next(s for s in body["sources"] if s["source"] == "all")
        assert every["available"] is False
        assert every["exceeds_ceiling"] is True
        assert "not trimmed to fit" in every["unavailable_reason"]
        assert body["max_urls"] == 5


def _shrink_ceiling(monkeypatch, module, ceiling: int) -> None:
    """Lower the list ceiling for one test, through `get_settings()` only."""
    from src.core.config import get_settings

    real = get_settings()
    patched = real.model_copy(update={"screaming_frog_url_list_max_urls": ceiling})
    monkeypatch.setattr(module, "get_settings", lambda: patched)


# --- preview: generation, filtering, storage ----------------------------------


class TestPreview:
    def test_a_preview_with_no_url_list_is_unchanged(self, client, job_store):
        worker = _register_worker(client)
        body = _preview(client, worker).json()
        assert body["url_list"] is None

    def test_a_preview_generates_stores_and_fingerprints_the_list(
        self, client, job_store, dispatch_store
    ):
        crawl = _finished_crawl(job_store, ["https://example.com/a", "https://example.com/b"])
        worker = _register_worker(client)

        body = _preview(client, worker, source_job_id=crawl.id).json()

        assert body["url_list"]["url_count"] == 2
        assert body["url_list"]["sample"] == ["https://example.com/a", "https://example.com/b"]
        expected = fingerprint(render_url_list(body["url_list"]["sample"]))
        assert body["url_list"]["sha256"] == expected
        # Stored at preview time, before anybody approved anything.
        stored = dispatch_store.read_url_list(expected, org_id="default")
        assert stored is not None
        assert stored.url_count == 2

    def test_the_counts_let_a_modal_say_how_many_were_excluded(self, client, job_store):
        crawl = _finished_crawl(
            job_store,
            [
                "https://example.com/a",
                "https://example.com/a",
                *[f"https://other{n}.com/x" for n in range(18)],
            ],
        )
        worker = _register_worker(client)

        counts = _preview(client, worker, source_job_id=crawl.id).json()["url_list"]["counts"]

        assert counts["off_domain_dropped"] == 18
        assert counts["duplicates_dropped"] == 1
        assert counts["kept"] == 1

    def test_orphans_uses_the_saved_cross_check(self, client, job_store):
        crawl = _finished_crawl(job_store, ["https://example.com/a", "https://example.com/b"])
        _with_reconciliation(job_store, crawl.id, ["https://example.com/orphan"])
        worker = _register_worker(client)

        body = _preview(client, worker, source_job_id=crawl.id, source="orphans").json()

        assert body["url_list"]["url_count"] == 1
        assert body["url_list"]["sample"] == ["https://example.com/orphan"]

    def test_orphans_without_a_cross_check_is_refused_with_the_reason(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)

        response = _preview(client, worker, source_job_id=crawl.id, source="orphans")

        assert response.status_code == 409
        assert "cross-check" in response.json()["detail"]

    def test_a_list_that_is_entirely_off_domain_is_refused_not_dispatched_empty(
        self, client, job_store
    ):
        crawl = _finished_crawl(job_store, ["https://other.com/a", "https://elsewhere.com/b"])
        worker = _register_worker(client)

        response = _preview(client, worker, source_job_id=crawl.id)

        assert response.status_code == 422
        assert "outside the crawl's own domain" in response.json()["detail"]

    def test_an_oversized_list_is_refused_with_an_explanation(self, client, job_store, monkeypatch):
        from src.api import url_list_routes

        crawl = _finished_crawl(job_store, [f"https://example.com/{n}" for n in range(9)])
        _shrink_ceiling(monkeypatch, url_list_routes, 3)
        worker = _register_worker(client)

        response = _preview(client, worker, source_job_id=crawl.id)

        assert response.status_code == 422
        assert "ceiling" in response.json()["detail"]
        assert "Orphans Only" in response.json()["detail"]

    def test_a_crawl_belonging_to_another_org_cannot_be_used_as_a_source(self, client, job_store):
        """IDOR, on the generating half."""
        crawl = _finished_crawl(job_store, org_id="other-org")
        worker = _register_worker(client)

        response = _preview(client, worker, source_job_id=crawl.id)

        assert response.status_code == 403

    def test_an_unknown_source_value_is_rejected_by_the_model(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        response = client.post(
            f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
            json={
                "seed_url": BASE,
                "correlation_id": "c1",
                "url_list": {"source_job_id": crawl.id, "source": "everything"},
            },
            headers=auth_headers(),
        )
        assert response.status_code == 422


# --- confirm: the four-gate binding -------------------------------------------


class TestConfirmBinding:
    def test_the_matching_digest_queues_a_list_job(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()

        response = _confirm(client, worker, preview)

        assert response.status_code == 202
        job = client.get(
            f"{API_PREFIX}/workers/jobs/{response.json()['id']}", headers=auth_headers()
        ).json()
        assert job["envelope"]["url_list_sha256"] == preview["url_list"]["sha256"]
        assert job["url_list_url_count"] == 1

    def test_confirming_a_different_list_is_refused(self, client, job_store, dispatch_store):
        """Preview one URL, confirm a hundred: the tamper this binding exists for.

        The second list is genuinely generated and genuinely stored, so the
        digest sent on confirm names a real, readable list belonging to this
        same org. The only thing wrong with it is that it is not the list the
        preview token was minted against — which is exactly the case a check
        that merely verified "is this a list we hold" would wave through.
        """
        small = _finished_crawl(job_store, ["https://example.com/a"])
        large = _finished_crawl(
            job_store, [f"https://example.com/{n}" for n in range(100)], label="big"
        )
        worker = _register_worker(client)
        approved = _preview(client, worker, source_job_id=small.id).json()
        other = _preview(client, worker, source_job_id=large.id).json()
        assert (
            dispatch_store.read_url_list(other["url_list"]["sha256"], org_id="default") is not None
        )

        response = _confirm(client, worker, approved, sha256=other["url_list"]["sha256"])

        assert response.status_code == 403
        assert "different URL list" in response.json()["detail"]

    def test_one_mutated_url_in_the_delivered_list_is_refused(self, client, job_store):
        """The same tamper, expressed as an edit rather than a substitution."""
        crawl = _finished_crawl(job_store, ["https://example.com/a", "https://example.com/b"])
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        mutated = fingerprint(
            render_url_list(["https://example.com/a", "https://example.com/EVIL"])
        )
        assert mutated != preview["url_list"]["sha256"]

        response = _confirm(client, worker, preview, sha256=mutated)

        assert response.status_code in {403, 404}
        assert client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers()).json()["jobs"] == []

    def test_dropping_the_digest_on_confirm_is_refused(self, client, job_store):
        """Omitting the list is a different dispatch, not a relaxation of one."""
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()

        response = _confirm(client, worker, preview, sha256=None)

        assert response.status_code == 403

    def test_adding_a_digest_to_a_listless_preview_is_refused(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        listless = _preview(client, worker).json()
        other = _preview(client, worker, source_job_id=crawl.id).json()

        response = _confirm(client, worker, listless, sha256=other["url_list"]["sha256"])

        assert response.status_code == 403

    def test_a_digest_this_org_cannot_read_is_refused(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        unknown = "d" * 64

        response = _confirm(client, worker, preview, sha256=unknown)

        assert response.status_code == 404
        assert "no longer available" in response.json()["detail"]

    def test_an_offline_worker_is_still_refused_before_anything_is_queued(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client, online=False)
        preview = _preview(client, worker, source_job_id=crawl.id).json()

        response = _confirm(client, worker, preview)

        assert response.status_code == 409
        assert "offline" in response.json()["detail"]


# --- concurrency --------------------------------------------------------------


class TestConcurrency:
    def test_a_second_dispatch_is_refused_while_one_is_running(self, client, job_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        first = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())
        assert first.status_code == 202

        second = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())

        assert second.status_code == 409

    def test_the_refusal_explains_why_and_names_what_is_running(self, client, job_store):
        """Not a bare 429. An operator has to know what to wait for."""
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        first = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())

        detail = _confirm(
            client, worker, _preview(client, worker, source_job_id=crawl.id).json()
        ).json()["detail"]

        assert "Screaming Frog runs 1 crawl at a time" in detail
        assert "licence log is shared" in detail
        assert first.json()["id"] in detail

    def test_a_dispatch_is_allowed_again_once_the_first_finishes(
        self, client, job_store, dispatch_store
    ):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        first = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())
        dispatch_store.mark_failed(first.json()["id"], "finished")

        second = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())

        assert second.status_code == 202

    def test_the_refusal_does_not_burn_the_approval(self, client, job_store, dispatch_store):
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        first = _confirm(client, worker, _preview(client, worker, source_job_id=crawl.id).json())
        blocked_preview = _preview(client, worker, source_job_id=crawl.id).json()
        assert _confirm(client, worker, blocked_preview).status_code == 409

        dispatch_store.mark_failed(first.json()["id"], "finished")

        assert _confirm(client, worker, blocked_preview).status_code == 202

    def test_another_workers_job_does_not_block_this_one(self, client, job_store):
        """The cap is per machine, because the shared `trace.txt` is per machine."""
        crawl = _finished_crawl(job_store)
        busy = _register_worker(client, name="desktop-1")
        idle = _register_worker(client, name="desktop-2")
        _confirm(client, busy, _preview(client, busy, source_job_id=crawl.id).json())

        response = _confirm(client, idle, _preview(client, idle, source_job_id=crawl.id).json())

        assert response.status_code == 202


# --- the worker's own fetch ---------------------------------------------------


class TestWorkerFetch:
    def _queued(self, client, job_store, urls=None) -> tuple[dict, dict, dict]:
        crawl = _finished_crawl(job_store, urls)
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        job = _confirm(client, worker, preview).json()
        return worker, job, preview

    def test_the_owning_worker_receives_the_exact_approved_bytes(self, client, job_store):
        worker, job, preview = self._queued(
            client, job_store, ["https://example.com/a", "https://example.com/b"]
        )

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        assert response.status_code == 200
        assert fingerprint(response.content) == preview["url_list"]["sha256"]
        assert response.content == b"https://example.com/a\r\nhttps://example.com/b\r\n"

    def test_the_response_carries_no_digest_header(self, client, job_store):
        """A digest beside the bytes is a digest an attacker can also rewrite."""
        worker, job, preview = self._queued(client, job_store)

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        assert not any("sha" in name.lower() for name in response.headers)

    def test_requires_a_worker_credential(self, client, job_store):
        _worker, job, _preview_body = self._queued(client, job_store)
        assert client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/url-list").status_code == 401

    def test_a_session_token_is_not_a_worker_credential(self, client, job_store):
        _worker, job, _preview_body = self._queued(client, job_store)
        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list", headers=auth_headers()
        )
        assert response.status_code == 401

    def test_another_worker_in_the_same_org_is_refused(self, client, job_store):
        """IDOR, on the delivery half. Same org is not the same machine."""
        _worker, job, _preview_body = self._queued(client, job_store)
        intruder = _register_worker(client, name="desktop-2")

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(intruder["worker_id"], intruder["worker_secret"]),
        )

        assert response.status_code == 403

    def test_a_plain_crawl_job_has_no_list_to_fetch(self, client, job_store):
        worker = _register_worker(client)
        preview = _preview(client, worker).json()
        job = _confirm(client, worker, preview, sha256=None).json()

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        assert response.status_code == 404
        assert "not a list crawl" in response.json()["detail"]

    def test_an_expired_list_is_404_with_an_actionable_message(
        self, client, job_store, dispatch_store
    ):
        worker, job, preview = self._queued(client, job_store)
        dispatch_store._expired_url_lists.add(preview["url_list"]["sha256"])  # noqa: SLF001

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        assert response.status_code == 404
        assert "retention window" in response.json()["detail"]

    def test_the_list_survives_the_source_crawl_being_deleted(self, client, job_store, tmp_path):
        """The reason generation happens at preview time and not at download.

        The approved bytes are frozen in the dispatch store; the crawl they
        came from is a local artefact that can be deleted, re-run, or extended
        afterwards without changing a single byte of what the worker fetches.
        """
        crawl = _finished_crawl(job_store, ["https://example.com/a"])
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        job = _confirm(client, worker, preview).json()

        for path in (tmp_path / "jobs").glob(f"{crawl.id}*"):
            path.unlink()
        assert not list((tmp_path / "jobs").glob(f"{crawl.id}*"))

        response = client.get(
            f"{API_PREFIX}/workers/jobs/{job['id']}/url-list",
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        assert response.status_code == 200
        assert fingerprint(response.content) == preview["url_list"]["sha256"]


# --- truncation reporting on the finished job ---------------------------------


class TestShortfallReporting:
    def _job_with_progress(self, client, job_store, dispatch_store, *, urls, crawled) -> dict:
        crawl = _finished_crawl(job_store, [f"https://example.com/{n}" for n in range(urls)])
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        job = _confirm(client, worker, preview).json()
        client.post(
            f"{API_PREFIX}/workers/jobs/{job['id']}/progress",
            json={"pages_crawled": crawled, "progress_pct": None, "phase": "exporting"},
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )
        return client.get(f"{API_PREFIX}/workers/jobs/{job['id']}", headers=auth_headers()).json()

    def test_a_complete_run_reports_a_zero_shortfall_and_no_note(
        self, client, job_store, dispatch_store
    ):
        view = self._job_with_progress(client, job_store, dispatch_store, urls=6, crawled=6)
        assert view["url_list_url_count"] == 6
        assert view["url_list_shortfall"] == 0
        assert view["url_list_shortfall_note"] == ""

    def test_a_short_run_reports_the_gap(self, client, job_store, dispatch_store):
        view = self._job_with_progress(client, job_store, dispatch_store, urls=10, crawled=4)
        assert view["url_list_shortfall"] == 6
        assert "6 were not fetched" in view["url_list_shortfall_note"]

    def test_a_run_with_no_progress_yet_cannot_say(self, client, job_store):
        """Absence is not zero, and a UI must not render it as zero."""
        crawl = _finished_crawl(job_store)
        worker = _register_worker(client)
        preview = _preview(client, worker, source_job_id=crawl.id).json()
        job = _confirm(client, worker, preview).json()

        view = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}", headers=auth_headers()).json()

        assert view["url_list_shortfall"] is None
        assert view["url_list_shortfall_note"] == ""

    def test_a_plain_crawl_job_never_reports_a_shortfall(self, client, job_store):
        worker = _register_worker(client)
        job = _confirm(client, worker, _preview(client, worker).json(), sha256=None).json()
        client.post(
            f"{API_PREFIX}/workers/jobs/{job['id']}/progress",
            json={"pages_crawled": 3, "progress_pct": None, "phase": "exporting"},
            headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
        )

        view = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}", headers=auth_headers()).json()

        assert view["url_list_url_count"] is None
        assert view["url_list_shortfall"] is None


def test_the_result_fixture_matches_the_shape_the_store_streams(job_store):
    """Guards the fixture itself: a wrong shape would make every test above vacuous."""
    crawl = _finished_crawl(job_store, ["https://example.com/a", "https://example.com/b"])
    assert list(job_store.iter_result_page_urls(crawl.id)) == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    raw = json.loads((job_store.root / f"{crawl.id}.result.json").read_text(encoding="utf-8"))
    assert raw["navigation"]["url"] == "https://example.com/nav-not-a-page"
