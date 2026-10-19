"""The breadcrumb parent: the URL of the crumb a visitor came down from (ADR 0038).

The parent is the last step before the page. The rules that decide it are the
ones the page's own section labels already rely on, so these cases pin the
edges where a wrong answer would put a page under the wrong parent in the
export: a self-linked final crumb, an unlinked "you are here" crumb, a truncated
trail, and an unlinked middle crumb that must not be guessed at.
"""

from __future__ import annotations

import json

from src.modules.seo.page_classifier.breadcrumb_parser import (
    BreadcrumbTrail,
    breadcrumb_parent_url,
    extract_breadcrumb,
)


def _jsonld(*items: dict[str, object]) -> str:
    """A page whose only breadcrumb is a BreadcrumbList with these items."""
    payload = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, **item} for i, item in enumerate(items)
        ],
    }
    return (
        '<html><head><script type="application/ld+json">'
        f"{json.dumps(payload)}</script></head><body>x</body></html>"
    )


def _parent(html: str, page: str) -> str | None:
    return breadcrumb_parent_url(extract_breadcrumb(html, page), page)


HOME = {"name": "Home", "item": "https://e.com/"}
BLOG = {"name": "Blog", "item": "https://e.com/blog/"}


class TestTheParentIsTheLastStepBeforeThePage:
    def test_a_self_linked_final_crumb_is_skipped(self):
        html = _jsonld(HOME, BLOG, {"name": "Post", "item": "https://e.com/blog/post/"})
        assert _parent(html, "https://e.com/blog/post/") == "https://e.com/blog/"

    def test_an_unlinked_final_crumb_is_the_page_and_is_skipped(self):
        """The conventional "you are here" marker, with no href."""
        html = _jsonld(HOME, BLOG, {"name": "Post"})
        assert _parent(html, "https://e.com/blog/post/") == "https://e.com/blog/"

    def test_a_truncated_trail_keeps_its_last_real_ancestor(self):
        """`Home > Resources` on `/resources/foo/`: neither rule fires, Resources stays."""
        html = _jsonld(HOME, {"name": "Resources", "item": "https://e.com/resources/"})
        assert _parent(html, "https://e.com/resources/foo/") == "https://e.com/resources/"

    def test_the_homepage_can_be_the_parent(self):
        html = _jsonld(HOME, {"name": "About"})
        assert _parent(html, "https://e.com/about/") == "https://e.com/"


class TestBlankWhereTheParentIsNotKnown:
    def test_no_breadcrumb_gives_no_parent(self):
        assert _parent("<html><body>plain</body></html>", "https://e.com/a/") is None

    def test_an_unlinked_middle_crumb_is_not_guessed_at(self):
        """`Agents` has no href because it has no page of its own.

        The nearest linked ancestor is not put in its place: that would be a guess.
        """
        html = _jsonld(
            HOME,
            {"name": "Agents"},
            {"name": "AIG", "item": "https://e.com/agents/aig/"},
        )
        assert _parent(html, "https://e.com/agents/aig/") is None

    def test_a_trail_that_is_only_the_page_has_no_parent(self):
        html = _jsonld({"name": "Only", "item": "https://e.com/only/"})
        assert _parent(html, "https://e.com/only/") is None

    def test_an_empty_trail_object_has_no_parent(self):
        assert breadcrumb_parent_url(BreadcrumbTrail(), "https://e.com/a/") is None


class TestTheParentURLIsScreened:
    def test_an_over_long_parent_url_is_dropped(self):
        long_parent = "https://e.com/" + "a" * 2100 + "/"
        html = _jsonld({"name": "Long", "item": long_parent}, {"name": "Page"})
        assert _parent(html, "https://e.com/page/") is None

    def test_an_unparseable_parent_is_dropped(self):
        html = _jsonld({"name": "Odd", "item": "https://[bad/"}, {"name": "Page"})
        assert _parent(html, "https://e.com/page/") is None
