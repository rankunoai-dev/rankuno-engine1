"""Tests for native title/meta description/H1 extraction.

No network and no fixtures on disk: `extract_content_signals` is a pure
function over text, matching the density of `test_signal_parsers.py`'s
`TestNavExtraction` for the same reason.
"""

from __future__ import annotations

from src.modules.seo.page_classifier.content_signals import (
    H1_MAX_LENGTH,
    META_DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    ContentSignals,
    extract_content_signals,
)


class TestTitleExtraction:
    def test_single_title_is_captured(self):
        signals = extract_content_signals("<html><head><title>Hello</title></head></html>")
        assert signals.page_title == "Hello"
        assert signals.page_title_count == 1

    def test_first_title_wins_the_text_but_count_reflects_every_occurrence(self):
        html = "<title>First</title><title>Second</title>"
        signals = extract_content_signals(html)
        assert signals.page_title == "First"
        assert signals.page_title_count == 2

    def test_duplicate_identical_titles_still_count_as_two(self):
        """Count and text are independent: identical text is not one occurrence."""
        html = "<title>Same</title><title>Same</title>"
        signals = extract_content_signals(html)
        assert signals.page_title == "Same"
        assert signals.page_title_count == 2

    def test_no_title_yields_empty_defaults(self):
        signals = extract_content_signals("<html><body>hi</body></html>")
        assert signals.page_title == ""
        assert signals.page_title_count == 0

    def test_document_with_no_head_tag_still_finds_a_leading_title(self):
        """`_closed_head` is a heuristic, not a read of literal `<head>` ancestry."""
        signals = extract_content_signals(
            "<html><title>No Head Wrapper</title><body></body></html>"
        )
        assert signals.page_title == "No Head Wrapper"
        assert signals.page_title_outside_head is False


class TestOutsideHead:
    def test_title_inside_head_is_not_flagged(self):
        html = "<html><head><title>In Head</title></head><body></body></html>"
        signals = extract_content_signals(html)
        assert signals.page_title_outside_head is False

    def test_title_after_body_is_flagged(self):
        html = "<html><head></head><body><title>Late Title</title></body></html>"
        signals = extract_content_signals(html)
        assert signals.page_title_outside_head is True

    def test_outside_head_is_recorded_even_when_that_occurrence_does_not_win_the_text(self):
        """Set the moment *any* occurrence is seen outside head, winning or not."""
        html = "<title>First</title><body><title>Second</title></body>"
        signals = extract_content_signals(html)
        assert signals.page_title == "First"
        assert signals.page_title_outside_head is True

    def test_meta_description_outside_head_is_independent_of_title(self):
        html = '<head><title>T</title></head><body><meta name="description" content="late"></body>'
        signals = extract_content_signals(html)
        assert signals.page_title_outside_head is False
        assert signals.meta_description_outside_head is True


class TestMetaDescriptionExtraction:
    def test_extracts_content(self):
        html = '<meta name="description" content="A great page">'
        signals = extract_content_signals(html)
        assert signals.meta_description == "A great page"
        assert signals.meta_description_count == 1

    def test_case_insensitive_name_value(self):
        """The attribute *value* `Description`, not just the attribute key, varies case."""
        html = '<meta name="Description" content="Mixed case name">'
        signals = extract_content_signals(html)
        assert signals.meta_description == "Mixed case name"

    def test_attribute_order_is_independent(self):
        html = '<meta content="content first" name="description">'
        signals = extract_content_signals(html)
        assert signals.meta_description == "content first"

    def test_other_meta_tags_are_ignored(self):
        html = '<meta name="viewport" content="width=device-width">'
        signals = extract_content_signals(html)
        assert signals.meta_description == ""
        assert signals.meta_description_count == 0

    def test_first_description_wins_but_every_occurrence_counts(self):
        html = '<meta name="description" content="First"><meta name="description" content="Second">'
        signals = extract_content_signals(html)
        assert signals.meta_description == "First"
        assert signals.meta_description_count == 2

    def test_self_closed_meta_is_handled(self):
        html = '<meta name="description" content="Self closed" />'
        signals = extract_content_signals(html)
        assert signals.meta_description == "Self closed"


class TestH1Extraction:
    def test_single_h1_is_captured(self):
        signals = extract_content_signals("<h1>Welcome</h1>")
        assert signals.h1_text == "Welcome"
        assert signals.h1_count == 1

    def test_multiple_h1s_increment_count_independent_of_text(self):
        signals = extract_content_signals("<h1>One</h1><h1>Two</h1>")
        assert signals.h1_text == "One"
        assert signals.h1_count == 2

    def test_malformed_nested_h1_merges_text_and_still_counts_both(self):
        """`html.parser` builds no tree; nesting is our own defined semantics."""
        html = "<h1>Outer<h1>Inner</h1>Tail</h1>"
        signals = extract_content_signals(html)
        assert signals.h1_text == "OuterInnerTail"
        assert signals.h1_count == 2

    def test_no_h1_yields_empty_defaults(self):
        signals = extract_content_signals("<p>no heading here</p>")
        assert signals.h1_text == ""
        assert signals.h1_count == 0


class TestNoscriptExclusion:
    def test_title_inside_noscript_is_not_counted_or_captured(self):
        html = "<title>Real</title><noscript><title>Fake</title></noscript>"
        signals = extract_content_signals(html)
        assert signals.page_title == "Real"
        assert signals.page_title_count == 1

    def test_meta_description_inside_noscript_is_excluded(self):
        html = '<noscript><meta name="description" content="tracking fallback"></noscript>'
        signals = extract_content_signals(html)
        assert signals.meta_description == ""
        assert signals.meta_description_count == 0

    def test_h1_inside_noscript_is_excluded(self):
        html = "<noscript><h1>Fallback Heading</h1></noscript>"
        signals = extract_content_signals(html)
        assert signals.h1_text == ""
        assert signals.h1_count == 0

    def test_a_tag_inside_noscript_does_not_flip_outside_head(self):
        """An `<img>` fallback inside `<noscript>` must not poison later head tags."""
        html = (
            "<head><noscript><img src='x'></noscript>"
            '<meta name="description" content="still in head"></head>'
        )
        signals = extract_content_signals(html)
        assert signals.meta_description_outside_head is False

    def test_nested_noscript_depth_is_tracked(self):
        html = (
            "<noscript><noscript><title>Doubly Nested</title></noscript></noscript>"
            "<title>Real</title>"
        )
        signals = extract_content_signals(html)
        assert signals.page_title == "Real"
        assert signals.page_title_count == 1


class TestCommentExclusion:
    def test_a_terminated_comment_hides_markup_inside_it(self):
        html = "<title>Real</title><!-- <title>Fake</title> -->"
        signals = extract_content_signals(html)
        assert signals.page_title == "Real"
        assert signals.page_title_count == 1

    def test_an_unterminated_comment_hides_markup_to_end_of_document(self):
        """`html.parser` never tokenises inside an open comment, terminated or not."""
        html = "<title>Real</title><!-- <title>Fake</title>"
        signals = extract_content_signals(html)
        assert signals.page_title == "Real"
        assert signals.page_title_count == 1


class TestRunawayTagTruncation:
    def test_title_truncates_at_max_length_rather_than_growing_unbounded(self):
        html = "<title>" + ("x" * (TITLE_MAX_LENGTH + 5_000))
        signals = extract_content_signals(html)
        assert len(signals.page_title) == TITLE_MAX_LENGTH

    def test_an_unterminated_title_is_still_finalised_at_end_of_document(self):
        """Truncated markup, not an absent title: the bytes were fetched."""
        signals = extract_content_signals("<title>Cut off mid")
        assert signals.page_title == "Cut off mid"
        assert signals.page_title_count == 1

    def test_an_unterminated_h1_is_finalised_too(self):
        signals = extract_content_signals("<h1>Also cut off")
        assert signals.h1_text == "Also cut off"

    def test_meta_description_truncates_at_max_length(self):
        html = f'<meta name="description" content="{"y" * (META_DESCRIPTION_MAX_LENGTH + 100)}">'
        signals = extract_content_signals(html)
        assert len(signals.meta_description) == META_DESCRIPTION_MAX_LENGTH

    def test_h1_truncates_at_its_own_wider_cap(self):
        html = "<h1>" + ("z" * (H1_MAX_LENGTH + 500))
        signals = extract_content_signals(html)
        assert len(signals.h1_text) == H1_MAX_LENGTH


class TestNeverRaises:
    def test_garbage_input_returns_defaults_rather_than_raising(self):
        signals = extract_content_signals("<<<>>>not html at all&&&")
        assert isinstance(signals, ContentSignals)

    def test_empty_string_returns_defaults(self):
        signals = extract_content_signals("")
        assert signals == ContentSignals()

    def test_deeply_unbalanced_tags_do_not_raise(self):
        html = "<title>" * 50 + "text" + "</title>" * 3
        signals = extract_content_signals(html)
        assert isinstance(signals.page_title, str)
        assert signals.page_title_count == 50
