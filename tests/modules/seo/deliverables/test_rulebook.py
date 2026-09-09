"""Tests for the rulebook engine (plan P1-1 through P1-4, ADR 0011).

No rulebook-shaped `.xlsx` is committed to the repository: every workbook here
is written by `openpyxl` into `tmp_path`, the same stance `test_diff_against_rae.py`
takes toward SF fixtures - the bytes belong to this test, not to a client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
import pytest
from pydantic import ValidationError
from src.modules.seo.contracts.audit import AuditDataset, AuditPage, AuditSource, Coverage
from src.modules.seo.contracts.catalogue import IssueId
from src.modules.seo.deliverables.rulebook import (
    OTHERS_THEME,
    PRIORITY_NOT_APPLICABLE,
    RULEBOOK_SHEET_NAME,
    Classification,
    Rule,
    Rulebook,
    RulebookError,
    RulebookMissingError,
    RuleType,
    apply_rulebook,
)

PRODUCED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def identity(url: str) -> str:
    """`UrlNormalizer` stand-in that changes nothing, for tests that don't care."""
    return url


def strip_www(url: str) -> str:
    """`UrlNormalizer` stand-in that only strips a `www.` host prefix."""
    return url.replace("://www.", "://")


def full_coverage() -> dict[IssueId, Coverage]:
    return dict.fromkeys(IssueId, Coverage.NOT_MEASURED)


def make_dataset(pages: tuple[AuditPage, ...], **overrides: object) -> AuditDataset:
    base: dict[str, object] = {
        "source": AuditSource.ENGINE,
        "site": "example.com",
        "produced_at": PRODUCED_AT,
        "pages": pages,
        "issues": {},
        "coverage": full_coverage(),
    }
    base.update(overrides)
    return AuditDataset.model_validate(base)


def write_rulebook_xlsx(
    path: Path,
    *,
    header: tuple[str, ...] = (
        "URL Pattern",
        "Rule Type",
        "Theme 1",
        "Theme 2",
        "Language",
        "Business Priority",
    ),
    header_row: int = 1,
    rows: tuple[tuple[object, ...], ...] = (),
    sheet_name: str = RULEBOOK_SHEET_NAME,
) -> Path:
    """Write a synthetic rulebook workbook, header padded to `header_row`."""
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = sheet_name
    for _ in range(header_row - 1):
        sheet.append(("filler",))
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


# ---------------------------------------------------------------------------
# P1-1: models
# ---------------------------------------------------------------------------


class TestRuleModel:
    def test_bad_regex_raises_at_construction(self) -> None:
        with pytest.raises(ValidationError, match="invalid regex pattern"):
            Rule(rule_type=RuleType.REGEX, pattern="(unclosed")

    def test_valid_regex_compiles(self) -> None:
        rule = Rule(rule_type=RuleType.REGEX, pattern=r"^/blog/\d+$")
        assert rule.pattern == r"^/blog/\d+$"

    def test_fallback_rejects_a_nonempty_pattern(self) -> None:
        with pytest.raises(ValidationError, match="FALLBACK"):
            Rule(rule_type=RuleType.FALLBACK, pattern="/anything")

    def test_non_fallback_rejects_an_empty_pattern(self) -> None:
        with pytest.raises(ValidationError, match="non-empty pattern"):
            Rule(rule_type=RuleType.CONTAINS, pattern="")

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Rule.model_validate({"rule_type": "CONTAINS", "pattern": "/x", "bogus": 1})


class TestRulebookModel:
    def test_compiles_regex_rules_built_by_hand(self) -> None:
        rulebook = Rulebook(rules=(Rule(rule_type=RuleType.REGEX, pattern=r"^/blog/"),))
        assert r"^/blog/" in rulebook._compiled  # noqa: SLF001 - white-box on the compile cache

    def test_rejects_two_fallback_rows(self) -> None:
        with pytest.raises(ValidationError, match="at most one FALLBACK"):
            Rulebook(
                rules=(
                    Rule(rule_type=RuleType.FALLBACK, pattern="", theme_1="A"),
                    Rule(rule_type=RuleType.FALLBACK, pattern="", theme_1="B"),
                )
            )

    def test_empty_rulebook_is_valid(self) -> None:
        assert Rulebook().rules == ()


# ---------------------------------------------------------------------------
# P1-2: loader - header detection, tolerant Language spellings, fallback rows
# ---------------------------------------------------------------------------


class TestFromXlsxMissing:
    def test_missing_file_raises_by_default(self, tmp_path: Path) -> None:
        with pytest.raises(RulebookMissingError, match="not found"):
            Rulebook.from_xlsx(tmp_path / "absent.xlsx")

    def test_missing_file_lenient_returns_empty_and_flags_itself(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.xlsx"
        rulebook = Rulebook.from_xlsx(path, lenient=True)
        assert rulebook.rules == ()
        assert rulebook.empty_due_to_missing_file is True
        assert rulebook.source_path == str(path)


class TestFromXlsxMalformedAlwaysRaises:
    """A present-but-malformed workbook raises even with lenient=True (approved point 4)."""

    def test_no_rulebook_sheet(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(tmp_path / "r.xlsx", sheet_name="NotRulebook")
        with pytest.raises(RulebookError, match="no 'Rulebook' sheet"):
            Rulebook.from_xlsx(path)
        with pytest.raises(RulebookError, match="no 'Rulebook' sheet"):
            Rulebook.from_xlsx(path, lenient=True)

    def test_no_header_row_in_first_five_rows(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(tmp_path / "r.xlsx", header_row=6)
        with pytest.raises(RulebookError, match="no header row"):
            Rulebook.from_xlsx(path)
        with pytest.raises(RulebookError, match="no header row"):
            Rulebook.from_xlsx(path, lenient=True)

    def test_no_rule_type_column(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", header=("URL Pattern", "Theme 1"), rows=(("/x", "X"),)
        )
        with pytest.raises(RulebookError, match="Rule Type"):
            Rulebook.from_xlsx(path)

    def test_unknown_rule_type_text(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", rows=(("/x", "Sorta Like", "X", "", "", ""),)
        )
        with pytest.raises(RulebookError, match="unknown rule type"):
            Rulebook.from_xlsx(path)

    def test_bad_regex_in_sheet(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", rows=(("(unclosed", "Regex", "X", "", "", ""),)
        )
        with pytest.raises(RulebookError, match="row 2"):
            Rulebook.from_xlsx(path)


class TestFromXlsxHeaderDetection:
    @pytest.mark.parametrize("header_row", [1, 2, 3, 4, 5])
    def test_header_found_anywhere_in_first_five_rows(
        self, tmp_path: Path, header_row: int
    ) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx",
            header_row=header_row,
            rows=(("/services", "Starts With", "Services", "", "", "Medium"),),
        )
        rulebook = Rulebook.from_xlsx(path)
        assert len(rulebook.rules) == 1
        assert rulebook.rules[0].theme_1 == "Services"

    @pytest.mark.parametrize("spelling", ["Language", "Languuage", "Lang"])
    def test_language_header_variants(self, tmp_path: Path, spelling: str) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx",
            header=(
                "URL Pattern",
                "Rule Type",
                "Theme 1",
                "Theme 2",
                spelling,
                "Business Priority",
            ),
            rows=(("/fr/", "Contains", "French", "", "French", "High"),),
        )
        rulebook = Rulebook.from_xlsx(path)
        assert rulebook.rules[0].language == "French"

    def test_missing_optional_columns_default_to_none(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", header=("URL Pattern", "Rule Type"), rows=(("/x", "Contains"),)
        )
        rulebook = Rulebook.from_xlsx(path)
        rule = rulebook.rules[0]
        assert (rule.theme_1, rule.theme_2, rule.language, rule.business_priority) == (
            None,
            None,
            None,
            None,
        )

    def test_blank_row_is_skipped(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx",
            rows=(
                ("/a", "Contains", "A", "", "", ""),
                (None, None, None, None, None, None),
                ("/b", "Contains", "B", "", "", ""),
            ),
        )
        rulebook = Rulebook.from_xlsx(path)
        assert len(rulebook.rules) == 2


class TestFromXlsxFallbackDetection:
    @pytest.mark.parametrize("marker", ["—", "-", "Fallback", "FALLBACK", "fallback"])
    def test_fallback_by_rule_type_marker(self, tmp_path: Path, marker: str) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", rows=((marker, marker, "Others", "", "", "N/A"),)
        )
        rulebook = Rulebook.from_xlsx(path)
        assert len(rulebook.rules) == 1
        assert rulebook.rules[0].rule_type is RuleType.FALLBACK
        assert rulebook.rules[0].theme_1 == "Others"

    @pytest.mark.parametrize("marker", ["No match", "no match", "NO MATCH"])
    def test_fallback_by_pattern_marker(self, tmp_path: Path, marker: str) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx", rows=((marker, "", "Others", "", "", "N/A"),)
        )
        rulebook = Rulebook.from_xlsx(path)
        assert rulebook.rules[0].rule_type is RuleType.FALLBACK


# ---------------------------------------------------------------------------
# P1-3: classify() precedence
# ---------------------------------------------------------------------------


class TestClassifyPrecedence:
    def test_exact_wins_over_a_longer_non_exact_pattern(self) -> None:
        rulebook = Rulebook(
            rules=(
                Rule(
                    rule_type=RuleType.CONTAINS,
                    pattern="/services/annotation-services",
                    theme_1="Contains",
                ),
                Rule(rule_type=RuleType.EXACT, pattern="/services", theme_1="Exact"),
            )
        )
        result = rulebook.classify("https://example.com/services")
        assert result.theme_1 == "Exact"

    def test_shadowing_case_longest_pattern_wins_regardless_of_row_order(self) -> None:
        """The documented case: `/services` must not beat `/services/annotation-services`.

        A page under the more specific "annotation services" section starts
        with both patterns; the 30-character pattern must win over the
        9-character one no matter which rule was authored first.
        """
        services = Rule(rule_type=RuleType.STARTS_WITH, pattern="/services", theme_1="Services")
        annotation = Rule(
            rule_type=RuleType.STARTS_WITH,
            pattern="/services/annotation-services",
            theme_1="Annotation Services",
        )
        url = "https://example.com/services/annotation-services/nlp-tagging"

        forward = Rulebook(rules=(services, annotation))
        reversed_order = Rulebook(rules=(annotation, services))

        assert forward.classify(url).theme_1 == "Annotation Services"
        assert reversed_order.classify(url).theme_1 == "Annotation Services"

    def test_case_insensitive_for_non_regex_types(self) -> None:
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.STARTS_WITH, pattern="/SERVICES", theme_1="Services"),)
        )
        assert rulebook.classify("https://example.com/services/x").theme_1 == "Services"

    def test_regex_is_case_sensitive(self) -> None:
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.REGEX, pattern=r"^/Blog/", theme_1="Blog"),)
        )
        assert rulebook.classify("https://example.com/blog/post").theme_1 == OTHERS_THEME
        assert rulebook.classify("https://example.com/Blog/post").theme_1 == "Blog"

    def test_unmatched_with_fallback_row_uses_it(self) -> None:
        rulebook = Rulebook(
            rules=(
                Rule(rule_type=RuleType.STARTS_WITH, pattern="/blog", theme_1="Blog"),
                Rule(
                    rule_type=RuleType.FALLBACK,
                    pattern="",
                    theme_1="Others",
                    business_priority="N/A",
                ),
            )
        )
        result = rulebook.classify("https://example.com/unknown-page")
        assert result == Classification(theme_1="Others", business_priority="N/A")

    def test_unmatched_without_fallback_row_is_others_and_not_low(self) -> None:
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.STARTS_WITH, pattern="/blog", theme_1="Blog"),)
        )
        result = rulebook.classify("https://example.com/unknown-page")
        assert result.theme_1 == OTHERS_THEME
        assert result.business_priority == PRIORITY_NOT_APPLICABLE
        assert result.business_priority != "Low"

    def test_empty_rulebook_is_others_not_low(self) -> None:
        result = Rulebook().classify("https://example.com/anything")
        assert result.theme_1 == OTHERS_THEME
        assert result.business_priority == PRIORITY_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# P1-4: apply_rulebook()
# ---------------------------------------------------------------------------


class TestApplyRulebook:
    def test_returns_a_new_dataset_object_original_untouched(self) -> None:
        pages = (AuditPage(url="https://example.com/blog/post"),)
        dataset = make_dataset(pages)
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.STARTS_WITH, pattern="/blog", theme_1="Blog"),)
        )

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        assert result is not dataset
        assert dataset.pages[0].theme_1 is None
        assert result.pages[0].theme_1 == "Blog"

    def test_matched_page_gets_full_classification(self) -> None:
        pages = (AuditPage(url="https://example.com/blog/post"),)
        dataset = make_dataset(pages)
        rulebook = Rulebook(
            rules=(
                Rule(
                    rule_type=RuleType.STARTS_WITH,
                    pattern="/blog",
                    theme_1="Blog",
                    theme_2="Content",
                    language="English",
                    business_priority="High",
                ),
            )
        )

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        page = result.pages[0]
        assert (page.theme_1, page.theme_2, page.language, page.business_priority) == (
            "Blog",
            "Content",
            "English",
            "High",
        )

    def test_unmatched_page_without_fallback_gets_others_n_a(self) -> None:
        pages = (AuditPage(url="https://example.com/mystery"),)
        dataset = make_dataset(pages)
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.STARTS_WITH, pattern="/blog", theme_1="Blog"),)
        )

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        page = result.pages[0]
        assert page.theme_1 == OTHERS_THEME
        assert page.business_priority == PRIORITY_NOT_APPLICABLE

    def test_lenient_empty_rulebook_appends_a_note(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.xlsx"
        rulebook = Rulebook.from_xlsx(path, lenient=True)
        pages = (AuditPage(url="https://example.com/anything"),)
        dataset = make_dataset(pages)

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        assert any("lenient mode applied" in note for note in result.notes)
        assert result.pages[0].theme_1 == OTHERS_THEME

    def test_non_lenient_rulebook_appends_no_note(self) -> None:
        pages = (AuditPage(url="https://example.com/anything"),)
        dataset = make_dataset(pages)
        rulebook = Rulebook()

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        assert result.notes == dataset.notes

    def test_normalize_is_applied_before_classification(self) -> None:
        pages = (AuditPage(url="https://www.example.com/services/x"),)
        dataset = make_dataset(pages)
        rulebook = Rulebook(
            rules=(Rule(rule_type=RuleType.STARTS_WITH, pattern="/services", theme_1="Services"),)
        )

        result = apply_rulebook(dataset, rulebook, normalize=strip_www)

        assert result.pages[0].theme_1 == "Services"
        # The page's own url key is untouched; only the lookup was normalised.
        assert result.pages[0].url == "https://www.example.com/services/x"

    def test_end_to_end_from_xlsx(self, tmp_path: Path) -> None:
        path = write_rulebook_xlsx(
            tmp_path / "r.xlsx",
            rows=(
                ("/services", "Starts With", "Services", "", "English", "Medium"),
                (
                    "/services/annotation-services",
                    "Starts With",
                    "Annotation Services",
                    "AI",
                    "English",
                    "High",
                ),
                ("—", "—", "Others", "", "", "N/A"),
            ),
        )
        rulebook = Rulebook.from_xlsx(path)
        pages = (
            AuditPage(url="https://example.com/services/annotation-services/tagging"),
            AuditPage(url="https://example.com/services/consulting"),
            AuditPage(url="https://example.com/about"),
        )
        dataset = make_dataset(pages)

        result = apply_rulebook(dataset, rulebook, normalize=identity)

        by_url = {page.url: page for page in result.pages}
        assert by_url["https://example.com/services/annotation-services/tagging"].theme_1 == (
            "Annotation Services"
        )
        assert by_url["https://example.com/services/consulting"].theme_1 == "Services"
        assert by_url["https://example.com/about"].theme_1 == "Others"
