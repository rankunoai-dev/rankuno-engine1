"""End-to-end tests for `scripts/build_deliverable.py` (Step 6, ADR 0011).

Imported as `scripts.build_deliverable`, matching `test_diff_against_rae.py`'s
stance toward a `scripts/` module: it is exercised as code, not shelled out
to, so a failure points straight at a line number instead of a subprocess
transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest
import scripts.build_deliverable as build_deliverable
from src.modules.seo.deliverables.rulebook import RULEBOOK_SHEET_NAME
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

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "deliverables" / "sf_bundle"
BASE = "https://www.e.com/"


def profile(url: str) -> FullPageIntelligenceProfile:
    """A minimal valid profile, built in full so the model validates it."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.BLOG_ARTICLE,
        depth_from_l0=1,
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


def crawl_result() -> PageClassificationOutput:
    pages = (profile("https://www.e.com/a/"), profile("https://www.e.com/b/"))
    return PageClassificationOutput(
        base_url=BASE,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport(profile_name="default", detected_profile_name="default"),
        discovery=DiscoveryReport(base_url=BASE, total_urls=2, orphans=0),
        summary=CrawlSummary(pages_classified=2, llm_spend_usd=1.25),
        pages=pages,
    )


def write_rulebook_xlsx(path: Path) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = RULEBOOK_SHEET_NAME
    sheet.append(
        ("URL Pattern", "Rule Type", "Theme 1", "Theme 2", "Language", "Business Priority")
    )
    sheet.append(("/a/", "CONTAINS", "Content", "Blog", "en", "High"))
    book.save(path)
    return path


class TestSfBundleEndToEnd:
    def test_builds_a_real_workbook_from_the_fixture_bundle(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = build_deliverable.main(
            ["sf-bundle", str(FIXTURES), "--output-dir", str(tmp_path)]
        )
        out = capsys.readouterr().out

        assert exit_code == 0
        written = Path(out.strip().removeprefix("wrote "))
        assert written.is_file()
        assert written.suffix == ".xlsx"
        openpyxl.load_workbook(written)  # does not raise: a real workbook


class TestEngineCrawlEndToEnd:
    def test_direct_result_file_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result_path = tmp_path / "result.json"
        result_path.write_text(json.dumps(crawl_result().model_dump(mode="json")), encoding="utf-8")

        exit_code = build_deliverable.main(
            ["engine-crawl", str(result_path), "--output-dir", str(tmp_path / "out")]
        )
        out = capsys.readouterr().out

        assert exit_code == 0
        written = Path(out.strip().removeprefix("wrote "))
        assert written.is_file()

    def test_job_id_under_dot_jobs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        jobs_dir = tmp_path / ".jobs"
        jobs_dir.mkdir()
        (jobs_dir / "abc123.result.json").write_text(
            json.dumps(crawl_result().model_dump(mode="json")), encoding="utf-8"
        )
        monkeypatch.setattr(build_deliverable, "JOBS_DIR", jobs_dir)

        exit_code = build_deliverable.main(
            ["engine-crawl", "abc123", "--output-dir", str(tmp_path / "out")]
        )
        out = capsys.readouterr().out

        assert exit_code == 0
        written = Path(out.strip().removeprefix("wrote "))
        assert written.is_file()


class TestBadPaths:
    """Bad-path exits use `SystemExit(message)`, not `SystemExit(1)`.

    Matches `reconcile_screaming_frog.py`'s `_load_result` convention:
    `.code` carries the message string, which Python's interpreter turns
    into exit code 1 (message to stderr) when this runs as `__main__` - the
    same contract `reconcile_screaming_frog.py`'s own callers rely on.
    """

    def test_missing_bundle_path_exits_1(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            build_deliverable.main(
                ["sf-bundle", str(tmp_path / "no-such-bundle"), "--output-dir", str(tmp_path)]
            )
        assert isinstance(excinfo.value.code, str) and excinfo.value.code

    def test_missing_job_id_exits_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(build_deliverable, "JOBS_DIR", tmp_path / ".jobs")
        with pytest.raises(SystemExit) as excinfo:
            build_deliverable.main(["engine-crawl", "no-such-job", "--output-dir", str(tmp_path)])
        assert isinstance(excinfo.value.code, str) and excinfo.value.code


class TestRulebookHandling:
    def test_missing_rulebook_strict_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "no-such-rulebook.xlsx"

        exit_code = build_deliverable.main(
            [
                "sf-bundle",
                str(FIXTURES),
                "--rulebook",
                str(missing),
                "--output-dir",
                str(tmp_path),
            ]
        )
        out = capsys.readouterr().out

        assert exit_code == 1
        assert "ERROR" in out

    def test_missing_rulebook_lenient_exits_0_and_still_writes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "no-such-rulebook.xlsx"

        exit_code = build_deliverable.main(
            [
                "sf-bundle",
                str(FIXTURES),
                "--rulebook",
                str(missing),
                "--lenient-rulebook",
                "--output-dir",
                str(tmp_path),
            ]
        )
        out = capsys.readouterr().out

        assert exit_code == 0
        written = Path(out.strip().removeprefix("wrote "))
        assert written.is_file()

    def test_rulebook_applied_end_to_end(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rulebook_path = write_rulebook_xlsx(tmp_path / "rulebook.xlsx")

        exit_code = build_deliverable.main(
            [
                "sf-bundle",
                str(FIXTURES),
                "--rulebook",
                str(rulebook_path),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        out = capsys.readouterr().out

        assert exit_code == 0
        written = Path(out.strip().removeprefix("wrote "))
        assert written.is_file()


class TestMainReturnCode:
    def test_main_returns_int_directly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = build_deliverable.main(["sf-bundle", str(FIXTURES), "--output-dir", str(tmp_path)])
        capsys.readouterr()
        assert code == 0
        assert isinstance(code, int)
