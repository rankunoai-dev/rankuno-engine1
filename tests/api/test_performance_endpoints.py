"""Tests for attaching Search Console data to a finished crawl.

Two things are being asserted throughout. First, that the endpoint accepts what
Search Console actually produces — the archive, not the tidy CSV nobody has.
Second, that the crawl is untouched: no new job, no mutated result, nothing
different about a job that never sees an export.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore, JobRecord
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier import tool as tool_module
from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import CrawlSummary, PageClassificationOutput
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

PUBLIC_IP = "93.184.216.34"

PAGES_CSV = (
    "Top pages,Clicks,Impressions,CTR,Position\n"
    "https://e.com/a/,120,4000,3%,4.2\n"
    "https://e.com/b/,15,900,1.67%,18.4\n"
)
QUERIES_CSV = "Top queries,Clicks,Impressions,CTR,Position\ninvoice software,300,9000,3.33%,2.1\n"


def page(url: str, trail: tuple[str, ...] = ("S",), inbound: int = 4):
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
        breadcrumb_path=trail,
        inbound_internal_links_count=inbound,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.BLOG_ARTICLE,
                confidence=0.9,
            ),
        ),
        final_confidence_score=0.9,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
    )


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(store):
    app = create_app(store=store, url_policy=UrlSafetyPolicy(resolver=lambda _h: [PUBLIC_IP]))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def crawl(store) -> JobRecord:
    """A finished two-page crawl to attach an export to."""
    record = store.create(server_module.TOOL_NAME, {"base_url": "https://e.com/"}, label="e.com")
    store.finish(
        record.id,
        PageClassificationOutput(
            base_url="https://e.com/",
            site_profile=SiteProfile(),
            weight_profile=WeightProfileReport.for_site(SiteProfile()),
            discovery=DiscoveryReport(base_url="https://e.com/"),
            summary=CrawlSummary(pages_classified=2),
            pages=(page("https://e.com/a/"), page("https://e.com/b/", inbound=0)),
        ).model_dump(mode="json"),
    )
    return record


def upload(client: TestClient, job_id: str, body: bytes | str):
    payload = body.encode() if isinstance(body, str) else body
    return client.post(
        f"{API_PREFIX}/jobs/{job_id}/performance/gsc",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )


def zipped(**files: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, text in files.items():
            handle.writestr(f"{name}.csv", text)
    return buffer.getvalue()


class TestUpload:
    def test_a_bare_csv_is_resolved_and_rolled_up(self, client, crawl):
        response = upload(client, crawl.id, PAGES_CSV)
        assert response.status_code == 200
        body = response.json()
        assert body["rows"] == 2
        assert body["matched"] == 2
        assert body["match_rate_pct"] == 100.0
        assert body["is_reliable"] is True
        assert body["rollup"]["site"]["clicks"] == 135

    def test_the_archive_search_console_actually_produces(self, client, crawl):
        """Export → CSV gives a ZIP of tabs, and that is the file a person has.

        The pages tab is chosen by content, so a five-tab archive resolves the
        same as the bare CSV.
        """
        response = upload(client, crawl.id, zipped(Queries=QUERIES_CSV, Pages=PAGES_CSV))
        assert response.status_code == 200
        body = response.json()
        assert body["source_name"] == "Pages.csv"
        assert body["matched"] == 2

    def test_the_crawl_is_not_touched(self, client, crawl, store):
        """The crawl is not touched.

        No new job, no mutated result. The report is a sidecar the crawl
        knows nothing about.
        """
        before = store.read_result(crawl.id)
        upload(client, crawl.id, PAGES_CSV)
        assert store.read_result(crawl.id) == before
        assert len(store.list_jobs()) == 1

    def test_coverage_is_reported_beside_the_match_rate(self, client, crawl):
        """The trap the match rate cannot catch.

        The Search Console UI caps an export at 1,000 rows. Against a
        12,000-page site every row resolves — 100% match rate — while the report
        describes 8% of the site. Only `pages_with_data` against `pages` says so.
        """
        response = upload(client, crawl.id, "Top pages,Clicks\nhttps://e.com/a/,5\n")
        body = response.json()
        assert body["match_rate_pct"] == 100.0
        assert body["pages_with_data"] == 1
        assert body["pages"] == 2

    def test_opportunities_come_back_with_the_rollup(self, client, crawl):
        response = upload(client, crawl.id, PAGES_CSV)
        found = response.json()["opportunities"]["opportunities"]
        assert [item["url"] for item in found] == ["https://e.com/b/"]
        assert found[0]["kind"] == "orphan_with_traffic"

    def test_a_second_upload_replaces_the_first(self, client, crawl):
        """How somebody corrects a wrong date range or the wrong property.

        Keeping both would leave two reports with no way to tell which one is
        on screen.
        """
        upload(client, crawl.id, PAGES_CSV)
        upload(
            client,
            crawl.id,
            "Top pages,Clicks,Impressions,CTR,Position\nhttps://e.com/a/,7,70,10%,2.0\n",
        )
        saved = client.get(f"{API_PREFIX}/jobs/{crawl.id}/performance").json()
        assert saved["summary"]["rows"] == 1
        assert saved["summary"]["rollup"]["site"]["clicks"] == 7


class TestRefusals:
    def test_an_unknown_job(self, client):
        assert upload(client, "nope", PAGES_CSV).status_code == 404

    def test_an_empty_body(self, client, crawl):
        response = upload(client, crawl.id, "   ")
        assert response.status_code == 400
        assert "empty body" in response.json()["detail"]

    def test_a_file_that_is_not_an_export(self, client, crawl):
        response = upload(client, crawl.id, b"\x89PNG\r\n\x1a\n not a spreadsheet")
        assert response.status_code == 400
        assert "Search Console" in response.json()["detail"]

    def test_a_queries_export_is_refused_rather_than_rolled_up(self, client, crawl):
        """A queries export is refused rather than rolled up.

        Reading it would produce a report about search phrases in which
        every row fails to resolve.
        """
        assert upload(client, crawl.id, QUERIES_CSV).status_code == 400

    def test_an_oversized_upload(self, client, crawl):
        response = upload(client, crawl.id, b"x" * (server_module.MAX_PERFORMANCE_UPLOAD + 1))
        assert response.status_code == 400
        assert "over the" in response.json()["detail"]

    def test_a_result_that_predates_the_contract(self, client, store):
        record = store.create(server_module.TOOL_NAME, {"base_url": "https://e.com/"})
        store.finish(record.id, {"base_url": "https://e.com/"})
        assert upload(client, record.id, PAGES_CSV).status_code == 409


class TestPersistence:
    def test_the_report_survives_leaving_the_page(self, client, crawl):
        """The report survives leaving the page.

        The export cost a person a trip to another product. A report that
        lives only in component state is one a navigation destroys.
        """
        upload(client, crawl.id, PAGES_CSV)
        saved = client.get(f"{API_PREFIX}/jobs/{crawl.id}/performance")
        assert saved.status_code == 200
        assert saved.json()["summary"]["matched"] == 2
        assert saved.json()["created_at"]

    def test_a_job_with_no_export_says_so(self, client, crawl):
        assert client.get(f"{API_PREFIX}/jobs/{crawl.id}/performance").status_code == 404

    def test_the_sidecar_does_not_appear_in_the_job_list(self, client, crawl, store):
        """The sidecar does not appear in the job list.

        Sidecars are `<id>.<kind>.json` and skipped by dot count. A new one
        that broke that rule would be read in full on every `GET /jobs`.
        """
        upload(client, crawl.id, PAGES_CSV)
        assert [record.id for record in store.list_jobs()] == [crawl.id]

    def test_a_failed_sidecar_write_does_not_fail_the_request(self, client, crawl, monkeypatch):
        """Losing the ability to re-read a report must not lose the report."""
        monkeypatch.setattr(
            DiskJobStore,
            "write_performance",
            lambda *_args, **_kwargs: None,
        )
        assert upload(client, crawl.id, PAGES_CSV).status_code == 200


class TestDownload:
    def test_the_csv_carries_the_plain_language_reason(self, client, crawl):
        """The csv carries the plain language reason.

        The person who acts on the row is usually not the person who ran the
        crawl, so the enum name is not enough.
        """
        upload(client, crawl.id, PAGES_CSV)
        response = client.get(f"{API_PREFIX}/jobs/{crawl.id}/opportunities.csv")
        assert response.status_code == 200
        assert "attachment; filename=" in response.headers["content-disposition"]
        text = response.text
        assert "orphan_with_traffic" in text
        assert "no internal link" in text

    def test_skipped_kinds_ride_in_the_same_file(self, client, store):
        """Skipped kinds ride in the same file.

        A list handed over without them invites the reader to conclude the
        site has no orphans, when the truth is this crawl could not tell.
        """
        record = store.create(server_module.TOOL_NAME, {"base_url": "https://e.com/"})
        pages = tuple(page(f"https://e.com/p{n}/", inbound=0) for n in range(4))
        store.finish(
            record.id,
            PageClassificationOutput(
                base_url="https://e.com/",
                site_profile=SiteProfile(),
                weight_profile=WeightProfileReport.for_site(SiteProfile()),
                discovery=DiscoveryReport(base_url="https://e.com/"),
                summary=CrawlSummary(pages_classified=4),
                pages=pages,
            ).model_dump(mode="json"),
        )
        upload(client, record.id, "Top pages,Clicks\nhttps://e.com/p0/,9\n")
        text = client.get(f"{API_PREFIX}/jobs/{record.id}/opportunities.csv").text
        assert "not evaluated: inbound_links_unreliable" in text

    def test_the_unmatched_csv_lists_every_row_with_its_reason(self, client, crawl):
        """The evidence behind the match rate.

        "41.5% matched" is a number an analyst has to take on trust. This is the
        other 58.5%, one row each, so it can be checked instead — and so the
        addresses themselves can be acted on.
        """
        upload(
            client,
            crawl.id,
            PAGES_CSV
            + "https://staging.e.com/spam/,900,50000,1.8%,3.0\n"
            + "https://elsewhere.org/x/,5,50,10%,9.0\n",
        )
        text = client.get(f"{API_PREFIX}/jobs/{crawl.id}/unmatched.csv").text
        assert "https://staging.e.com/spam/" in text
        assert "other_subdomain" in text
        assert "elsewhere.org" in text
        assert "off_site" in text
        # The plain-language gloss travels with it: the person who acts on the
        # row is usually not the person who ran the crawl.
        assert "subdomain of this site" in text
        # And the group totals ride at the top, or the reader counts rows and
        # thinks that is the finding.
        assert "group total" in text

    def test_a_subdomain_is_reported_apart_from_a_stranger(self, client, crawl):
        """Merging the two is what hid 558 rows of indexed spam on gep.com."""
        response = upload(
            client,
            crawl.id,
            PAGES_CSV
            + "https://staging.e.com/spam/,900,50000,1.8%,3.0\n"
            + "https://elsewhere.org/x/,5,50,10%,9.0\n",
        )
        groups = {g["host"]: g for g in response.json()["unmatched"]}
        assert groups["staging.e.com"]["reason"] == "other_subdomain"
        assert groups["elsewhere.org"]["reason"] == "off_site"
        # Ordered by clicks: the largest part of the gap reads first.
        assert response.json()["unmatched"][0]["host"] == "staging.e.com"

    def test_the_groups_account_for_every_unmatched_row(self, client, crawl):
        """The groups account for every unmatched row.

        They partition the gap, so the match rate can be checked rather than
        believed. A group view that does not add up is worse than none.
        """
        response = upload(
            client,
            crawl.id,
            PAGES_CSV
            + "https://staging.e.com/one/,1,10,10%,3.0\n"
            + "https://staging.e.com/two/,2,20,10%,3.0\n"
            + "https://elsewhere.org/x/,5,50,10%,9.0\n",
        )
        body = response.json()
        assert sum(g["urls"] for g in body["unmatched"]) == body["rows"] - body["matched"]
        assert (
            sum(g["clicks"] for g in body["unmatched"]) == body["rollup"]["unattributed"]["clicks"]
        )

    def test_a_job_with_no_export_has_nothing_to_download(self, client, crawl):
        assert client.get(f"{API_PREFIX}/jobs/{crawl.id}/opportunities.csv").status_code == 404


def test_the_tool_module_is_untouched_by_any_of_this():
    """The performance package must not have reached into the crawl tool.

    `modules -> integrations -> core` is the rule, and a performance import
    inside the classifier would be the first step toward the crawl depending on
    an export it may never receive.
    """
    source = tool_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        assert "performance" not in handle.read()
