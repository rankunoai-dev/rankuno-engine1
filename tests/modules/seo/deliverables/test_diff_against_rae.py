"""Tests for the RAE differential check (plan P0-7, ADR 0011).

The fixture directories built here are shaped like an RAE crawl-report folder
(a flat directory of Screaming Frog CSVs) but every byte in them is written by
this test. No RAE data enters the repository (ADR 0011, "No RAE code is
copied" — the same stance extends to data).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import scripts.diff_against_rae as diff_against_rae
from scripts.diff_against_rae import (
    UNWIRED_SECURITY_ISSUES,
    diff_dataset_against_rae,
    main,
    read_rae_style_issue,
)
from src.core.config import Settings, reset_settings_cache
from src.modules.seo.contracts.audit import IssueId
from src.modules.seo.deliverables.screaming_frog_adapter import load_screaming_frog_bundle

PRODUCED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def identity(url: str) -> str:
    return url


def csv_text(header: Sequence[str], *rows: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def spine_text(*urls: str) -> str:
    return csv_text(["Address", "Status Code"], *[(url, "200") for url in urls])


def write_crawl_folder(root: Path, files: dict[str, str | bytes]) -> Path:
    """Write a synthetic crawl folder, BOM included, matching a real SF export."""
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        if isinstance(body, bytes):
            (root / name).write_bytes(body)
        else:
            (root / name).write_text(body, encoding="utf-8-sig", newline="")
    return root


class TestSkipsCleanly:
    def test_returns_zero_when_unset(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=None
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)
        assert main() == 0

    def test_returns_zero_when_directory_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=missing
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)
        assert main() == 0

    def test_returns_zero_when_archive_has_no_crawl_folders(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty_archive = tmp_path / "archive"
        empty_archive.mkdir()
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=empty_archive
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)
        assert main() == 0


class TestReadRaeStyleIssue:
    def test_unions_address_source_and_destination(self, tmp_path: Path) -> None:
        # Row duplicated so the file clears the 100-byte floor without
        # introducing a third URL into the expected set.
        text = csv_text(
            ["Source", "Destination"],
            ("https://example.com/a/", "https://example.com/b/"),
            ("https://example.com/a/", "https://example.com/b/"),
        )
        write_crawl_folder(tmp_path, {"http_urls_inlinks.csv": text})
        assert (tmp_path / "http_urls_inlinks.csv").stat().st_size >= 100
        result = read_rae_style_issue(tmp_path, ("http_urls_inlinks.csv",), identity)
        assert result.urls == frozenset({"https://example.com/a/", "https://example.com/b/"})
        assert result.has_destination_column is True
        assert result.skipped_small_file is False

    def test_skips_a_file_under_100_bytes(self, tmp_path: Path) -> None:
        write_crawl_folder(tmp_path, {"url_uppercase.csv": csv_text(["Address"], ("x",))})
        assert (tmp_path / "url_uppercase.csv").stat().st_size < 100
        result = read_rae_style_issue(tmp_path, ("url_uppercase.csv",), identity)
        assert result.urls == frozenset()
        assert result.skipped_small_file is True

    def test_absent_file_is_not_a_skip(self, tmp_path: Path) -> None:
        result = read_rae_style_issue(tmp_path, ("does_not_exist.csv",), identity)
        assert result.urls == frozenset()
        assert result.skipped_small_file is False


class TestDiffDatasetAgainstRae:
    """One synthetic crawl folder covering the diff cases.

    Exercises all three suppressible categories plus one genuine (uncovered)
    divergence, and asserts the first three never appear in `.differences`
    while the fourth always does.
    """

    @pytest.fixture
    def crawl_dir(self, tmp_path: Path) -> Path:
        home = "https://example.com/"
        upper = "https://example.com/UPPER/"
        h1_missing_url = "https://example.com/no-h1/"
        hsts_url = "https://example.com/insecure/"

        files: dict[str, str | bytes] = {
            # Spine: every URL our adapter will admit into an issue set.
            "internal_all.csv": spine_text(home, upper, h1_missing_url, hsts_url),
            # (1) Inlinks-style: RAE unions Source+Destination, we read Source
            # only. Destination is deliberately outside the spine — the
            # adapter never sees it, only the oracle reader does. Row
            # duplicated to clear the 100-byte floor (case 2 is what tests
            # that floor, not this file).
            "http_urls_inlinks.csv": csv_text(
                ["Source", "Destination"],
                (home, "https://example.com/OUTSIDE-SPINE/"),
                (home, "https://example.com/OUTSIDE-SPINE/"),
            ),
            # (2) Under 100 bytes: RAE skips, we do not.
            "url_underscores.csv": csv_text(["Address"], (upper,)),
            # (3) Unwired-by-RAE Security file: real data, RAE's table never
            # pointed at it (D3).
            "security_missing_hsts_header.csv": csv_text(
                ["Address", "Status Code"], (hsts_url, "200"), (home, "200")
            ),
            # (4) Genuine, undocumented divergence: header carries both
            # Address and Source. Our adapter deterministically prefers
            # Address; RAE-style reading unions both, with no Destination
            # column present, so none of the three known categories apply.
            # Row duplicated to clear the 100-byte floor.
            "h1_missing.csv": csv_text(
                ["Address", "Source"],
                (h1_missing_url, "https://example.com/ALSO-OUTSIDE/"),
                (h1_missing_url, "https://example.com/ALSO-OUTSIDE/"),
            ),
        }
        write_crawl_folder(tmp_path, files)
        # url_underscores.csv must land under 100 bytes to exercise case (2);
        # http_urls_inlinks.csv and h1_missing.csv must not, or they would
        # land in that same category instead of the one each is meant to
        # exercise. security_missing_hsts_header.csv's size is irrelevant:
        # an unwired-security issue skips the oracle read entirely.
        assert (tmp_path / "url_underscores.csv").stat().st_size < 100
        assert (tmp_path / "http_urls_inlinks.csv").stat().st_size >= 100
        assert (tmp_path / "h1_missing.csv").stat().st_size >= 100
        return tmp_path

    def test_known_differences_suppressed_and_unexpected_reported(self, crawl_dir: Path) -> None:
        dataset = load_screaming_frog_bundle(crawl_dir, normalize=identity, produced_at=PRODUCED_AT)
        report = diff_dataset_against_rae(dataset, crawl_dir, normalize=identity)

        reported_ids = {diff.issue_id for diff in report.differences}
        known_ids = {suppressed.issue_id for suppressed in report.known}

        # (1), (2), (3): known, suppressed, never counted as regressions.
        assert IssueId.INTERNAL_LINKS_SECURITY_HTTP_URLS_INLINKS not in reported_ids
        assert IssueId.INTERNAL_LINKS_SECURITY_HTTP_URLS_INLINKS in known_ids
        assert IssueId.URL_UNDERSCORES not in reported_ids
        assert IssueId.URL_UNDERSCORES in known_ids
        assert IssueId.SECURITY_MISSING_HSTS_HEADER not in reported_ids
        assert IssueId.SECURITY_MISSING_HSTS_HEADER in known_ids

        # (4): not explained by any known category - a real regression.
        assert IssueId.H1_MISSING in reported_ids
        h1_diff = next(d for d in report.differences if d.issue_id is IssueId.H1_MISSING)
        assert h1_diff.oracle_only == frozenset({"https://example.com/ALSO-OUTSIDE/"})
        assert h1_diff.our_only == frozenset()

    def test_unwired_security_ids_are_exactly_the_documented_ten(self) -> None:
        assert len(UNWIRED_SECURITY_ISSUES) == 10
        assert IssueId.SECURITY_HTTP_URLS not in UNWIRED_SECURITY_ISSUES
        assert IssueId.SECURITY_MIXED_CONTENT not in UNWIRED_SECURITY_ISSUES
        assert IssueId.SECURITY_MISSING_HSTS_HEADER in UNWIRED_SECURITY_ISSUES


class TestMainEndToEnd:
    def test_reports_regression_exit_code_and_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        archive = tmp_path / "archive"
        crawl = archive / "crawl-one"
        home = "https://example.com/"
        h1_missing_url = "https://example.com/no-h1/"
        write_crawl_folder(
            crawl,
            {
                "internal_all.csv": spine_text(home, h1_missing_url),
                # Row duplicated so the file clears the 100-byte floor -
                # otherwise it would land in the known 100-byte-skip
                # category instead of demonstrating a real regression.
                "h1_missing.csv": csv_text(
                    ["Address", "Source"],
                    (h1_missing_url, "https://example.com/ALSO-OUTSIDE/"),
                    (h1_missing_url, "https://example.com/ALSO-OUTSIDE/"),
                ),
            },
        )
        assert (crawl / "h1_missing.csv").stat().st_size >= 100
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=archive
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)

        exit_code = main()
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "crawl-one" in out
        assert "UNEXPECTED" in out
        assert "H1_MISSING" in out

    def test_clean_archive_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        archive = tmp_path / "archive"
        crawl = archive / "crawl-clean"
        home = "https://example.com/"
        write_crawl_folder(crawl, {"internal_all.csv": spine_text(home)})
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=archive
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)

        exit_code = main()
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "OK - matches RAE issue membership" in out

    def test_adapter_refusal_is_skipped_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        archive = tmp_path / "archive"
        broken = archive / "no-spine"
        broken.mkdir(parents=True)
        settings = Settings(
            _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=archive
        )
        monkeypatch.setattr(diff_against_rae, "get_settings", lambda: settings)

        exit_code = main()
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "SKIPPED" in out


def test_settings_field_defaults_to_none(tmp_path: Path) -> None:
    """`Settings.rae_archive_dir` is optional and unset by default (plan §6 Q8)."""
    reset_settings_cache()
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    assert settings.rae_archive_dir is None


def test_settings_field_accepts_a_path(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, audit_log_path=tmp_path / "a.jsonl", rae_archive_dir=tmp_path
    )
    assert settings.rae_archive_dir == tmp_path
