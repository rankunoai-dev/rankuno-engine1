"""Tests for the golden corpus contracts, loader and coverage reporting.

The coverage tests matter most. This module's main job is preventing a figure
computed over a handful of labels from being quoted as evidence, so the checks
that enforce that are the ones worth breaking loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.errors import ConfigurationError
from src.modules.seo.page_classifier.corpus import (
    MIN_ENTRIES_PER_ARCHETYPE,
    CorpusEntry,
    CorpusSite,
    GoldenCorpus,
    SiteArchetype,
    load_corpus,
    load_corpus_dir,
    summarise_gaps,
)
from src.modules.seo.page_classifier.schemas import HierarchyLevel, PrimaryPageType

CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "corpus"


def entry(url: str = "https://e.com/a/") -> CorpusEntry:
    """A minimal labelled entry."""
    return CorpusEntry(
        url=url,
        expected_level=HierarchyLevel.L3_LEAF_PAGE,
        expected_page_type=PrimaryPageType.BLOG_ARTICLE,
        source="test",
    )


def site(
    name: str = "example",
    archetype: SiteArchetype = SiteArchetype.B2B_SAAS,
    count: int = 1,
) -> CorpusSite:
    """A site with `count` labelled entries."""
    return CorpusSite(
        name=name,
        base_url="https://e.com",
        archetype=archetype,
        entries=tuple(entry(f"https://e.com/p{i}/") for i in range(count)),
    )


class TestContracts:
    def test_entry_requires_both_axes(self):
        with pytest.raises(ValueError):
            CorpusEntry(url="https://e.com/", expected_level=HierarchyLevel.L0_HOMEPAGE)

    def test_entry_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            CorpusEntry(
                url="https://e.com/",
                expected_level=HierarchyLevel.L0_HOMEPAGE,
                expected_page_type=PrimaryPageType.HOMEPAGE,
                confidence=0.9,
            )

    def test_archetypes_are_distinct_and_upper_snake(self):
        for member in SiteArchetype:
            assert member.value == member.name == member.value.upper()

    def test_six_archetypes(self):
        """Each must justify itself by a code path the others do not reach."""
        assert len(SiteArchetype) == 6


class TestQueries:
    def test_entries_spans_every_site(self):
        corpus = GoldenCorpus(sites=(site("a", count=2), site("b", count=3)))
        assert len(corpus.entries()) == 5

    def test_by_archetype_filters(self):
        corpus = GoldenCorpus(
            sites=(
                site("a", SiteArchetype.B2B_SAAS, 2),
                site("b", SiteArchetype.ECOMMERCE, 3),
            )
        )
        assert len(corpus.by_archetype(SiteArchetype.ECOMMERCE)) == 3
        assert corpus.by_archetype(SiteArchetype.HEADLESS_SPA) == ()

    def test_archetype_of_maps_urls(self):
        corpus = GoldenCorpus(sites=(site("a", SiteArchetype.FLAT_URL, 1),))
        mapping = corpus.archetype_of()
        assert mapping["https://e.com/p0/"] is SiteArchetype.FLAT_URL

    def test_merging_prefers_the_later_site_on_a_name_clash(self):
        first = GoldenCorpus(sites=(site("dup", count=1),))
        second = GoldenCorpus(sites=(site("dup", count=5),))
        assert len(first.merged_with(second).entries()) == 5


class TestCoverage:
    def test_reports_every_archetype_including_empty_ones(self):
        """An archetype with zero labels is the most important thing to show."""
        coverage = GoldenCorpus(sites=(site(count=1),)).coverage()
        assert len(coverage.per_archetype) == len(SiteArchetype)
        empty = [item for item in coverage.per_archetype if item.entries == 0]
        assert len(empty) == len(SiteArchetype) - 1

    def test_a_thin_archetype_is_not_sufficient(self):
        coverage = GoldenCorpus(sites=(site(count=3),)).coverage()
        b2b = next(i for i in coverage.per_archetype if i.archetype is SiteArchetype.B2B_SAAS)
        assert b2b.sufficient is False
        assert b2b.shortfall == MIN_ENTRIES_PER_ARCHETYPE - 3

    def test_a_full_archetype_is_sufficient(self):
        coverage = GoldenCorpus(sites=(site(count=MIN_ENTRIES_PER_ARCHETYPE),)).coverage()
        b2b = next(i for i in coverage.per_archetype if i.archetype is SiteArchetype.B2B_SAAS)
        assert b2b.sufficient is True
        assert b2b.shortfall == 0

    def test_not_publishable_until_every_archetype_is_covered(self):
        """One well-sampled archetype is not evidence about the engine."""
        coverage = GoldenCorpus(sites=(site(count=500),)).coverage()
        assert coverage.is_publishable is False

    def test_publishable_when_all_archetypes_are_covered(self):
        sites = tuple(site(f"s-{a.value}", a, MIN_ENTRIES_PER_ARCHETYPE) for a in SiteArchetype)
        assert GoldenCorpus(sites=sites).coverage().is_publishable is True

    def test_empty_corpus_reports_cleanly(self):
        coverage = GoldenCorpus().coverage()
        assert coverage.total_entries == 0
        assert coverage.is_publishable is False

    def test_summary_line_states_the_verdict(self):
        line = GoldenCorpus(sites=(site(count=3),)).coverage().summary_line()
        assert "NOT publishable" in line

    def test_gaps_are_listed_worst_first(self):
        """Entirely unlabelled archetypes lead, then partial ones by shortfall."""
        corpus = GoldenCorpus(
            sites=(site("a", SiteArchetype.B2B_SAAS, 40), site("b", SiteArchetype.ECOMMERCE, 5))
        )
        gaps = summarise_gaps(corpus.coverage())

        # Four archetypes have zero labels, so they share the largest shortfall
        # and come first. Among the sampled ones, ECOMMERCE (45 short) must
        # precede B2B_SAAS (10 short).
        joined = " | ".join(gaps)
        assert joined.index("ECOMMERCE") < joined.index("B2B_SAAS")
        assert all("0/50" in line for line in gaps[:4]), "unlabelled archetypes lead"

    def test_no_gaps_when_publishable(self):
        sites = tuple(site(f"s-{a.value}", a, MIN_ENTRIES_PER_ARCHETYPE) for a in SiteArchetype)
        assert summarise_gaps(GoldenCorpus(sites=sites).coverage()) == ()


class TestLoading:
    def test_loads_a_single_site_document(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text(site(count=2).model_dump_json(), encoding="utf-8")
        assert len(load_corpus(path).entries()) == 2

    def test_loads_a_list_of_sites(self, tmp_path):
        path = tmp_path / "s.json"
        payload = [
            site("a", count=1).model_dump(mode="json"),
            site("b", count=2).model_dump(mode="json"),
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert len(load_corpus(path).sites) == 2

    def test_missing_file_is_a_hard_failure(self, tmp_path):
        """The corpus is the yardstick; a missing one must not be skipped past."""
        with pytest.raises(ConfigurationError, match="could not be read"):
            load_corpus(tmp_path / "nope.json")

    def test_malformed_json_is_a_hard_failure(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="not valid JSON"):
            load_corpus(path)

    def test_schema_violation_is_a_hard_failure(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
        with pytest.raises(ConfigurationError, match="does not match the schema"):
            load_corpus(path)

    def test_unknown_archetype_is_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(
            json.dumps(
                {"name": "x", "base_url": "https://e.com", "archetype": "MYSTERY", "entries": []}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError):
            load_corpus(path)

    def test_directory_load_merges_files(self, tmp_path):
        (tmp_path / "a.json").write_text(site("a", count=2).model_dump_json(), encoding="utf-8")
        (tmp_path / "b.json").write_text(site("b", count=3).model_dump_json(), encoding="utf-8")
        assert len(load_corpus_dir(tmp_path).entries()) == 5

    def test_empty_directory_is_valid(self, tmp_path):
        """An empty corpus is a state to report on, not an error."""
        assert load_corpus_dir(tmp_path).entries() == ()

    def test_missing_directory_is_a_hard_failure(self, tmp_path):
        with pytest.raises(ConfigurationError, match="does not exist"):
            load_corpus_dir(tmp_path / "nope")


class TestShippedFixtures:
    """The real corpus, as committed."""

    def test_the_shipped_corpus_loads(self):
        assert load_corpus_dir(CORPUS_DIR).entries()

    def test_highradius_labels_are_human_sourced(self):
        """Machine-generated labels would make the yardstick self-referential."""
        corpus = load_corpus_dir(CORPUS_DIR)
        highradius = next(s for s in corpus.sites if s.name == "highradius")
        assert "Rankuno" in highradius.labelled_by
        assert all(item.source for item in highradius.entries), "every label needs provenance"

    def test_the_shipped_corpus_is_not_yet_publishable(self):
        """Guards against quoting an accuracy figure over 13 labels."""
        coverage = load_corpus_dir(CORPUS_DIR).coverage()
        assert coverage.is_publishable is False
        assert coverage.usable_archetypes == ()

    def test_the_documented_gaps_are_real(self):
        gaps = summarise_gaps(load_corpus_dir(CORPUS_DIR).coverage())
        joined = " ".join(gaps)
        assert "ECOMMERCE" in joined
        assert "FLAT_URL" in joined

    def test_includes_the_sitemap_omitted_pages(self):
        """The pages the 3-path pipeline exists to find must be labelled."""
        urls = {item.url for item in load_corpus_dir(CORPUS_DIR).entries()}
        assert "https://www.highradius.com/code-of-ethics/" in urls
        assert "https://www.highradius.com/glossary/" in urls
