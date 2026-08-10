"""Tests for draft labelling worksheets.

The rejection tests carry the weight here. A worksheet's whole purpose is to be
*inert* until a human has worked on it, so the checks that keep unreviewed
suggestions out of the corpus are the ones that must never quietly relax.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.errors import ConfigurationError
from src.modules.seo.page_classifier.corpus import (
    SiteArchetype,
    load_corpus_dir,
)
from src.modules.seo.page_classifier.corpus_drafts import (
    DRAFT_COLUMNS,
    DraftRow,
    draft_rows_from_profiles,
    load_reviewed_csv,
    write_draft_csv,
)
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)

CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "corpus"
DRAFTS_DIR = CORPUS_DIR / "drafts"


def profile(
    url: str = "https://e.com/a/",
    confidence: float = 0.9,
    page_type: PrimaryPageType = PrimaryPageType.BLOG_ARTICLE,
) -> FullPageIntelligenceProfile:
    """A classified page."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=page_type,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=page_type,
                confidence=confidence,
            ),
        ),
        final_confidence_score=confidence,
        consensus_method=ConsensusMethod.WEIGHTED_CONSENSUS,
    )


def write_rows(path: Path, *rows: DraftRow) -> Path:
    """Write rows to a worksheet and return the path."""
    write_draft_csv(rows, path)
    return path


class TestWorksheetGeneration:
    def test_suggestions_are_carried_but_expectations_are_empty(self):
        """The core contract: a suggestion is not a label."""
        rows = draft_rows_from_profiles([profile()])
        assert rows[0].suggested_page_type == "BLOG_ARTICLE"
        assert rows[0].expected_level == ""
        assert rows[0].expected_page_type == ""
        assert rows[0].reviewed == ""

    def test_hardest_rows_come_first(self):
        """A reviewer's time is worth most where the engine is least sure."""
        rows = draft_rows_from_profiles(
            [profile("https://e.com/sure/", 0.95), profile("https://e.com/unsure/", 0.2)]
        )
        assert rows[0].url.endswith("/unsure/")

    def test_ordering_can_be_disabled(self):
        rows = draft_rows_from_profiles(
            [profile("https://e.com/a/", 0.95), profile("https://e.com/b/", 0.2)],
            hardest_first=False,
        )
        assert rows[0].url.endswith("/a/")

    def test_records_which_signals_fired(self):
        """A reviewer deciding whether to trust a suggestion needs its evidence."""
        assert draft_rows_from_profiles([profile()])[0].signals == "SITEMAP_INDEX"

    def test_empty_input_yields_no_rows(self):
        assert draft_rows_from_profiles([]) == ()


class TestRoundTrip:
    def test_written_worksheet_has_the_expected_columns(self, tmp_path):
        path = write_rows(tmp_path / "w.csv", *draft_rows_from_profiles([profile()]))
        header = path.read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",") == list(DRAFT_COLUMNS)

    def test_reviewed_rows_become_corpus_entries(self, tmp_path):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed="y",
                expected_level="L1_PRIMARY_NAV_HUB",
                expected_page_type="PRODUCT_CATEGORY_HUB",
                notes="top-level collection",
            ),
        )
        site, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.ECOMMERCE
        )
        assert stats.admitted == 1
        assert site.entries[0].expected_page_type is PrimaryPageType.PRODUCT_CATEGORY_HUB
        assert site.entries[0].expected_level is HierarchyLevel.L1_PRIMARY_NAV_HUB

    def test_expected_values_are_case_insensitive(self, tmp_path):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed="Y",
                expected_level="l3_leaf_page",
                expected_page_type="blog_article",
            ),
        )
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.admitted == 1

    @pytest.mark.parametrize("flag", ["y", "yes", "true", "1", "ok", "done", "DONE"])
    def test_review_flag_spellings(self, tmp_path, flag):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed=flag,
                expected_level="L3_LEAF_PAGE",
                expected_page_type="BLOG_ARTICLE",
            ),
        )
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.admitted == 1


class TestRejection:
    """A worksheet must be inert until a human has worked on it."""

    def test_unreviewed_suggestions_never_enter_the_corpus(self, tmp_path):
        """The rule the fixture README states: predictions are not ground truth."""
        path = write_rows(tmp_path / "w.csv", *draft_rows_from_profiles([profile()]))
        site, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert site.entries == ()
        assert stats.total_rows == 1
        assert stats.admitted == 0

    def test_a_row_ticked_without_answers_is_refused(self, tmp_path):
        """Ticking the box without filling it in is the likeliest sloppy review."""
        path = write_rows(tmp_path / "w.csv", DraftRow(url="https://e.com/p/", reviewed="y"))
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.reviewed == 1
        assert stats.admitted == 0
        assert stats.marked_but_unusable == 1

    def test_an_invalid_taxonomy_value_is_refused(self, tmp_path):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed="y",
                expected_level="L3_LEAF_PAGE",
                expected_page_type="NOT_A_REAL_TYPE",
            ),
        )
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.admitted == 0
        assert stats.marked_but_unusable == 1

    @pytest.mark.parametrize("flag", ["", "n", "no", "later", "maybe", "0"])
    def test_anything_but_an_affirmative_means_unreviewed(self, tmp_path, flag):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed=flag,
                expected_level="L3_LEAF_PAGE",
                expected_page_type="BLOG_ARTICLE",
            ),
        )
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.admitted == 0

    def test_suggestion_columns_are_never_used_as_the_answer(self, tmp_path):
        """Even reviewed, an empty expectation must not fall back to the guess."""
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                suggested_level="L0_HOMEPAGE",
                suggested_page_type="HOMEPAGE",
                reviewed="y",
            ),
        )
        site, _ = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert site.entries == ()


class TestReviewStats:
    def test_reports_progress(self, tmp_path):
        rows = [
            DraftRow(
                url=f"https://e.com/{i}/",
                reviewed="y" if i < 2 else "",
                expected_level="L3_LEAF_PAGE",
                expected_page_type="BLOG_ARTICLE",
            )
            for i in range(4)
        ]
        path = write_rows(tmp_path / "w.csv", *rows)
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.progress == pytest.approx(0.5)
        assert "2/4 rows admitted" in stats.summary_line()

    def test_warns_about_sloppy_reviews(self, tmp_path):
        path = write_rows(tmp_path / "w.csv", DraftRow(url="https://e.com/p/", reviewed="y"))
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert "WARNING" in stats.summary_line()

    def test_provenance_is_recorded(self, tmp_path):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed="y",
                expected_level="L3_LEAF_PAGE",
                expected_page_type="BLOG_ARTICLE",
            ),
        )
        site, _ = load_reviewed_csv(
            path,
            name="s",
            base_url="https://e.com",
            archetype=SiteArchetype.B2B_SAAS,
            labelled_by="A Reviewer",
        )
        assert site.labelled_by == "A Reviewer"
        assert "human review" in site.entries[0].source

    def test_an_unattributed_review_is_marked_as_such(self, tmp_path):
        path = write_rows(
            tmp_path / "w.csv",
            DraftRow(
                url="https://e.com/p/",
                reviewed="y",
                expected_level="L3_LEAF_PAGE",
                expected_page_type="BLOG_ARTICLE",
            ),
        )
        site, _ = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert site.labelled_by == "unrecorded reviewer"


class TestMalformedInput:
    def test_missing_file_is_a_hard_failure(self, tmp_path):
        with pytest.raises(ConfigurationError, match="could not be read"):
            load_reviewed_csv(
                tmp_path / "nope.csv",
                name="s",
                base_url="https://e.com",
                archetype=SiteArchetype.B2B_SAAS,
            )

    def test_a_file_without_a_url_column_is_rejected(self, tmp_path):
        path = tmp_path / "w.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="no 'url' column"):
            load_reviewed_csv(
                path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
            )

    def test_blank_rows_are_skipped(self, tmp_path):
        path = tmp_path / "w.csv"
        path.write_text("url,reviewed\n,y\nhttps://e.com/p/,\n", encoding="utf-8")
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.total_rows == 1

    def test_a_junk_confidence_cell_does_not_break_the_load(self, tmp_path):
        path = tmp_path / "w.csv"
        path.write_text(
            "url,confidence,reviewed,expected_level,expected_page_type\n"
            "https://e.com/p/,not-a-number,y,L3_LEAF_PAGE,BLOG_ARTICLE\n",
            encoding="utf-8",
        )
        _, stats = load_reviewed_csv(
            path, name="s", base_url="https://e.com", archetype=SiteArchetype.B2B_SAAS
        )
        assert stats.admitted == 1


class TestCorpusIsolation:
    """Drafts must not leak into the corpus by being in the same tree."""

    def test_the_shipped_drafts_exist(self):
        assert DRAFTS_DIR.is_dir()
        assert list(DRAFTS_DIR.glob("*.csv")), "cycle 0010 generated worksheets"

    def test_drafts_are_not_loaded_as_corpus(self):
        """`load_corpus_dir` globs *.json at one level; drafts are .csv, nested."""
        corpus = load_corpus_dir(CORPUS_DIR)
        assert {site.name for site in corpus.sites} == {"highradius"}

    def test_the_corpus_is_still_only_human_labelled(self):
        corpus = load_corpus_dir(CORPUS_DIR)
        assert all("Rankuno" in site.labelled_by for site in corpus.sites)

    def test_shipped_drafts_are_entirely_unreviewed(self):
        """Until a human works on them, they must contribute nothing."""
        for worksheet in DRAFTS_DIR.glob("*.csv"):
            _, stats = load_reviewed_csv(
                worksheet,
                name=worksheet.stem,
                base_url="https://example.com",
                archetype=SiteArchetype.ECOMMERCE,
            )
            assert stats.admitted == 0, f"{worksheet.name} must be inert until reviewed"
            assert stats.total_rows > 0
