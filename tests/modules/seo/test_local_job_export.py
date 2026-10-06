"""Choosing and packaging a local crawl for the cloud (ADR 0034, audit condition 6)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from src.core.state_store import DiskJobStore, JobRecord
from src.modules.seo.page_classifier.job_bundle import BundleSource, JobImportBundle
from src.modules.seo.page_classifier.local_job_export import (
    INSTANCE_ID_FILENAME,
    ExportRefusedError,
    build_bundle,
    encode_bundle,
    exportable_jobs,
    load_or_create_instance_id,
    normalise_host,
    read_instance_id,
)

from tests.modules.seo.job_bundle_factory import crawl_output


def finished_job(
    store: DiskJobStore, base: str = "https://www.example.com/", **kw: object
) -> JobRecord:
    record = store.create("seo.page_classifier", {"base_url": base}, label=base)
    store.mark_running(record.id)
    output = crawl_output()
    for key, value in kw.items():
        setattr(output, key, value)
    store.finish(record.id, output.model_dump(mode="json"))
    store.write_homepage(record.id, "<html>home</html>")
    return store.get(record.id)


def source(record: JobRecord) -> BundleSource:
    return BundleSource(source_instance_id="li-test-instance", source_job_id=record.id)


class TestSelection:
    @pytest.mark.parametrize(
        ("text", "host"),
        [
            ("groundsguys.com", "groundsguys.com"),
            ("www.GroundsGuys.com", "groundsguys.com"),
            ("https://www.groundsguys.com/", "groundsguys.com"),
        ],
    )
    def test_hosts_normalise(self, text: str, host: str) -> None:
        assert normalise_host(text) == host

    def test_only_finished_page_classifier_results_newest_first(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        older = finished_job(store)
        newer = finished_job(store)
        store.create("seo.page_classifier", {"base_url": "https://www.example.com/"})  # queued
        failed = store.create("seo.page_classifier", {"base_url": "https://www.example.com/"})
        store.mark_failed(failed.id, "boom")
        other = finished_job(store, base="https://other.org/")

        assert [r.id for r in exportable_jobs(store, "example.com")] == [newer.id, older.id]
        assert {r.id for r in exportable_jobs(store)} == {newer.id, older.id, other.id}


class TestInstanceId:
    def test_created_once_then_reused(self, tmp_path: Path) -> None:
        assert read_instance_id(tmp_path) is None
        first = load_or_create_instance_id(tmp_path)
        assert first.startswith("li-")
        assert load_or_create_instance_id(tmp_path) == first
        assert (tmp_path / INSTANCE_ID_FILENAME).read_text(encoding="utf-8") == first

    def test_it_is_invisible_to_the_job_list(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        load_or_create_instance_id(tmp_path)
        assert store.list_jobs() == []

    def test_a_corrupt_file_is_refused_not_overwritten(self, tmp_path: Path) -> None:
        (tmp_path / INSTANCE_ID_FILENAME).write_text("../../etc/passwd", encoding="utf-8")
        with pytest.raises(ExportRefusedError):
            load_or_create_instance_id(tmp_path)


class TestBuild:
    def test_a_finished_job_builds_a_valid_deterministic_bundle(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = finished_job(store)
        built = build_bundle(store, record, source(record))

        assert built.homepage_dropped is False
        assert built.bundle.homepage_html == "<html>home</html>"
        assert built.bundle.status == "succeeded"
        assert encode_bundle(built.bundle) == encode_bundle(
            build_bundle(store, record, source(record)).bundle
        )
        round_trip = JobImportBundle.model_validate_json(
            gzip.decompress(encode_bundle(built.bundle))
        )
        assert round_trip == built.bundle

    def test_an_oversized_homepage_is_left_out(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = finished_job(store)
        store.write_homepage(record.id, "x" * (6 * 1024 * 1024))
        built = build_bundle(store, record, source(record))
        assert built.homepage_dropped is True
        assert built.bundle.homepage_html is None

    def test_an_unfinished_job_is_refused(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = store.create("seo.page_classifier", {"base_url": "https://example.com/"})
        with pytest.raises(ExportRefusedError, match="only finished crawls"):
            build_bundle(store, record, source(record))

    def test_a_url_the_cloud_would_refuse_is_caught_locally(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = finished_job(store, base_url="javascript:alert(1)")
        with pytest.raises(ExportRefusedError, match=r"result\.base_url"):
            build_bundle(store, record, source(record))

    def test_a_result_off_contract_is_refused_without_its_values(self, tmp_path: Path) -> None:
        store = DiskJobStore(tmp_path)
        record = store.create("seo.page_classifier", {"base_url": "https://example.com/"})
        store.finish(record.id, {"base_url": "SECRET_VALUE"})
        with pytest.raises(ExportRefusedError) as caught:
            build_bundle(store, store.get(record.id), source(record))
        assert "SECRET_VALUE" not in str(caught.value)
