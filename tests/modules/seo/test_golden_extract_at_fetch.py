"""Golden equivalence: async == serial == a committed snapshot.

The extract-at-fetch work changes *when* a page body is read and how long it is
kept. Everything a crawl produces must stay put while that happens. This test
pins the whole produced artefact for one ~500-page site, through both crawl
paths, with the async path's completion order shuffled three different ways.

Two artefacts are pinned, because the tool's output does not show everything:

* `tool` — `PageClassificationOutput`, exactly as a job stores it.
* `graph` — what discovery hands on: the unfetched set a checkpoint writes, the
  homepage body the menu is read from, and every `PageEvidence` (its `html`
  replaced by a SHA-256, so the snapshot stays reviewable).

Comparison is on canonical JSON (`sort_keys=True`). Dict key order is not part
of any contract here, and one dict genuinely varies with completion order:
`fetch_outcomes` is a `Counter` filled as responses land. List and tuple order
*is* contract — node order drives result order — and is compared exactly.

The snapshot is regenerated only on purpose, from the serial path:

    python -c "from tests.modules.seo.test_golden_extract_at_fetch import regenerate; regenerate()"
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from src.core.config import Settings
from src.modules.seo.page_classifier.async_discovery import adiscover_site
from src.modules.seo.page_classifier.discovery import SiteGraph, discover_site
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool

from tests.modules.seo.golden_site_factory import (
    BASE,
    Route,
    build_fetcher,
    build_site,
    golden_settings,
)

SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "extract_at_fetch_500.json.gz"
)
SEEDS = (1, 2, 3)


def canonical(value: object) -> str:
    """The one serialisation every comparison and the snapshot use."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def first_difference(expected: object, actual: object, path: str = "$") -> str | None:
    """Name the first JSON path at which two documents disagree, or `None`."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return f"{path}.{key}: present on one side only"
            found = first_difference(expected[key], actual[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for index, (left, right) in enumerate(zip(expected, actual, strict=False)):
            found = first_difference(left, right, f"{path}[{index}]")
            if found:
                return found
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        return None
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def _sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_graph(graph: SiteGraph) -> dict[str, Any]:
    """Everything discovery hands on, with bodies reduced to their hashes."""
    evidence = []
    for item in graph.to_page_evidence():
        dumped = item.model_dump(mode="json")
        dumped["html"] = _sha(item.html)
        evidence.append(dumped)
    return {
        "unfetched_urls": list(graph.unfetched_urls()),
        "homepage_sha256": _sha(graph.html_for(BASE)),
        "evidence": evidence,
    }


def run_tool(settings: Settings, site: dict[str, Route], *, seed: int | None) -> dict[str, Any]:
    """Run the governed tool. `seed=None` is the serial path."""
    tool = PageClassificationTool(fetcher=build_fetcher(settings, site, seed=seed))
    result = tool.run(PageClassificationInput(base_url=BASE, use_async_crawl=seed is not None))
    assert result.ok, result.error
    assert result.data is not None
    data: dict[str, Any] = result.data.model_dump(mode="json")
    return data


def run_discovery(
    settings: Settings,
    site: dict[str, Route],
    *,
    seed: int | None,
    completions: list[str] | None = None,
) -> SiteGraph:
    """Run discovery alone. `seed=None` is the serial path."""
    fetcher = build_fetcher(settings, site, seed=seed, completions=completions)
    if seed is None:
        graph, _ = discover_site(fetcher, BASE)
        return graph

    async def scenario() -> SiteGraph:
        async with fetcher:
            found, _ = await adiscover_site(fetcher, BASE)
            return found

    return asyncio.run(scenario())


def capture(settings: Settings, site: dict[str, Route], *, seed: int | None) -> dict[str, Any]:
    """Both pinned artefacts, normalised through canonical JSON."""
    raw = {
        "tool": run_tool(settings, site, seed=seed),
        "graph": project_graph(run_discovery(settings, site, seed=seed)),
    }
    loaded: dict[str, Any] = json.loads(canonical(raw))
    return loaded


def regenerate(path: Path = SNAPSHOT) -> None:
    """Rewrite the snapshot from the serial path. Deliberate use only."""
    with tempfile.TemporaryDirectory() as tmp:
        document = capture(golden_settings(Path(tmp)), build_site(), seed=None)
    buffer = io.BytesIO()
    # `mtime=0` so regenerating unchanged output yields an identical file.
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(canonical(document).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


@pytest.fixture(scope="module")
def site() -> dict[str, Route]:
    return build_site()


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(gzip.decompress(SNAPSHOT.read_bytes()).decode("utf-8"))
    return loaded


@pytest.fixture
def golden(tmp_path: Path) -> Settings:
    return golden_settings(tmp_path)


def assert_identical(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    """Byte-compare canonical JSON; on failure, say where."""
    if canonical(actual) != canonical(expected):
        where = first_difference(expected, actual)
        pytest.fail(f"{label} differs from the golden snapshot at {where}")


class TestGoldenEquivalence:
    """Concurrency, and when HTML is read, must change nothing produced."""

    def test_serial_matches_the_snapshot(self, golden, site, snapshot):
        assert_identical(capture(golden, site, seed=None), snapshot, "serial")

    @pytest.mark.parametrize("seed", SEEDS)
    def test_async_matches_the_snapshot_in_any_completion_order(self, golden, site, snapshot, seed):
        assert_identical(capture(golden, site, seed=seed), snapshot, f"async seed={seed}")

    def test_completion_order_is_actually_shuffled(self, golden, site):
        """Guards the guard: identical orders would make the seeds vacuous."""
        orders: dict[int, list[str]] = {}
        for seed in (0, *SEEDS):
            completions: list[str] = []
            run_discovery(golden, site, seed=seed, completions=completions)
            orders[seed] = completions
        assert len({tuple(order) for order in orders.values()}) == len(orders)
        assert all(sorted(order) == sorted(orders[0]) for order in orders.values())


class TestTheFixtureExercisesWhatItClaims:
    """A golden test over a site that lacks the edge cases proves nothing about them."""

    def test_the_site_is_about_five_hundred_pages(self, snapshot):
        assert 450 <= snapshot["tool"]["discovery"]["total_urls"] <= 550

    def test_fetched_pages_are_evicted_by_a_confirmed_loop(self, snapshot):
        discovery = snapshot["tool"]["discovery"]
        assert discovery["loop_urls_skipped"] > 0
        assert discovery["pages_fetched"] > discovery["total_urls"] - discovery["sitemap_only"]

    def test_errors_and_non_html_stay_unfetched_and_an_empty_body_does_not(self, snapshot):
        unfetched = set(snapshot["graph"]["unfetched_urls"])
        assert f"{BASE}/careers/old-role/" in unfetched
        assert f"{BASE}/resources/whitepaper-download/" in unfetched
        assert f"{BASE}/careers/empty/" not in unfetched
        outcomes = snapshot["tool"]["discovery"]["fetch_outcomes"]
        assert outcomes["not_html"] == 1
        assert outcomes["not_found"] >= 1

    def test_the_homepage_is_read_through_its_redirect(self, snapshot, site):
        assert snapshot["graph"]["homepage_sha256"] == _sha(site["/home/"].body)
        assert snapshot["tool"]["nav_coverage"]["nav_entries"] == 6

    def test_both_breadcrumb_forms_and_jsonld_types_are_present(self, snapshot):
        """Services publish DOM crumbs and products `BreadcrumbList` JSON-LD."""
        trails = {item["url"]: item["breadcrumb_path"] for item in snapshot["graph"]["evidence"]}
        assert trails[f"{BASE}/services/s1/sub1/"] == ["Services", "S1"]
        assert trails[f"{BASE}/products/c2/p3/"] == ["Products", "C2"]
        pages = snapshot["tool"]["pages"]
        signals = {s["source"] for page in pages for s in page["signals_evaluated"]}
        assert "SCHEMA_JSONLD" in signals

    def test_a_redirected_page_resolves_its_relative_links_where_it_landed(self, snapshot):
        urls = {page["url"] for page in snapshot["tool"]["pages"]}
        assert f"{BASE}/new/sub/child/" in urls
        assert f"{BASE}/moved/child/" not in urls
