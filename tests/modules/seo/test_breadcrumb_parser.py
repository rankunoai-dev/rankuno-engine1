"""Tests for breadcrumb extraction.

Every JSON-LD fixture below is the shape of a real site, sampled live: Yoast on
highradius.com, plain `BreadcrumbList` on gep.com, and AEM on infosys.com. All
three are valid Schema.org and all three differ, which is the whole difficulty —
reading one shape returns an empty trail for the others, and an empty trail is
indistinguishable from "this site publishes no breadcrumbs".

The DOM fixtures are equally real: caeliusconsulting.com (React/Tailwind) and
allbirds.com (Shopify) publish no structured data at all, only an accessible
`aria-label`. A JSON-LD-only implementation is blind to both.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.breadcrumb_parser import (
    MAX_BREADCRUMB_STEPS,
    extract_breadcrumb,
    is_breadcrumb_container,
)

BASE = "https://e.com/services/cloud/"

# Yoast: `item` is a string, and the list is buried in an `@graph`.
YOAST = """
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebPage","@id":"https://e.com/#webpage"},
  {"@type":"BreadcrumbList","@id":"https://e.com/#breadcrumb","itemListElement":[
    {"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"},
    {"@type":"ListItem","position":2,"name":"Services","item":"https://e.com/services/"},
    {"@type":"ListItem","position":3,"name":"Cloud"}
  ]}
]}
</script>
"""

# AEM: `item` is an object, the name lives *inside* it, and there is no Home.
AEM = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
  {"@type":"ListItem","position":1,"item":{"@id":"https://e.com/services.html","name":"Services"}},
  {"@type":"ListItem","position":2,"item":{"@id":"https://e.com/services/cloud.html","name":"Cobalt"}}
]}
</script>
"""

# Shopify/React: no structured data, an accessible label, single-quoted attrs,
# and `breadcrumbs` in the plural.
SHOPIFY_DOM = """
<nav role='navigation' aria-label='breadcrumbs'>
  <ol>
    <li><a href='/' title='Home'>Home</a></li>
    <li><span class='sep'>/</span><a href='/collections/mens'>Men&#39;s Shoes</a></li>
  </ol>
</nav>
"""


class TestJsonLdShapes:
    """One extractor has to read every shape, because all of them are valid."""

    def test_yoast_string_item(self):
        trail = extract_breadcrumb(YOAST, BASE)
        assert trail.source == "jsonld"
        assert trail.labels == ("Home", "Services", "Cloud")
        assert trail.steps[0].url == "https://e.com/"

    def test_a_final_unlinked_crumb_is_kept(self):
        """The current page is normally the one crumb with no link."""
        trail = extract_breadcrumb(YOAST, BASE)
        assert trail.steps[-1].label == "Cloud"
        assert trail.steps[-1].url is None

    def test_aem_object_item_with_nested_name(self):
        """`name` is inside `item` here and absent from the `ListItem`."""
        trail = extract_breadcrumb(AEM, BASE)
        assert trail.labels == ("Services", "Cobalt")
        assert trail.steps[0].url == "https://e.com/services.html"

    def test_a_trail_that_does_not_start_at_home(self):
        """A trail need not begin at the homepage.

        Infosys starts at `Services`. Assuming index 0 is the homepage
        mis-levels every page on that site by one.
        """
        trail = extract_breadcrumb(AEM, BASE)
        assert trail.labels[0] != "Home"
        assert trail.depth == 1

    def test_depth_excludes_the_page_itself(self):
        """`Home > Services > Cloud` puts the page two levels below the root."""
        assert extract_breadcrumb(YOAST, BASE).depth == 2

    def test_escaped_slashes_resolve(self):
        r"""GEP publishes `https:\/\/`, which some encoders leave literal."""
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":1,"name":"HOME","item":"https:\\/\\/e.com\\/"}]}
        </script>"""
        trail = extract_breadcrumb(html, BASE)
        assert trail.steps[0].url == "https://e.com/"

    def test_labels_are_not_retitled(self):
        """Labels are stored exactly as published.

        GEP publishes `HOME`. Rewriting a client's own labels puts words in
        their mouth in a report they will read.
        """
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":1,"name":"CAREERS AT GEP","item":"https://e.com/c"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("CAREERS AT GEP",)

    def test_type_may_be_a_list(self):
        """`"@type": ["BreadcrumbList"]` is valid JSON-LD."""
        html = """<script type="application/ld+json">
        {"@type":["BreadcrumbList"],"itemListElement":[
          {"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("Home",)

    def test_position_orders_a_shuffled_list(self):
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":3,"name":"Third","item":"https://e.com/3"},
          {"@type":"ListItem","position":1,"name":"First","item":"https://e.com/1"},
          {"@type":"ListItem","position":2,"name":"Second","item":"https://e.com/2"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("First", "Second", "Third")

    def test_partial_positions_keep_document_order(self):
        """Mixing declared and document order silently reorders a correct trail."""
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","name":"First","item":"https://e.com/1"},
          {"@type":"ListItem","position":9,"name":"Second","item":"https://e.com/2"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("First", "Second")

    def test_the_longest_of_several_lists_wins(self):
        """A product in several categories emits one list per category."""
        html = """<script type="application/ld+json">
        [{"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"}]},
         {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"},
            {"@type":"ListItem","position":2,"name":"Shoes","item":"https://e.com/s"}]}]
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("Home", "Shoes")


class TestDomFallback:
    """Half the sample publishes no structured data at all."""

    def test_shopify_accessible_markup(self):
        trail = extract_breadcrumb(SHOPIFY_DOM, "https://e.com/products/x")
        assert trail.source == "dom"
        assert trail.labels == ("Home", "Men's Shoes")

    def test_separators_are_not_crumbs(self):
        """`/`, `›` and `»` are elements in their own right in this markup."""
        assert "/" not in extract_breadcrumb(SHOPIFY_DOM, BASE).labels

    def test_relative_hrefs_resolve(self):
        trail = extract_breadcrumb(SHOPIFY_DOM, "https://e.com/products/x")
        assert trail.steps[1].url == "https://e.com/collections/mens"

    def test_a_class_named_breadcrumb_is_enough(self):
        html = """<div class="breadcrumb-trail">
          <a href="/">Home</a> <a href="/blog">Blog</a></div>"""
        assert extract_breadcrumb(html, BASE).labels == ("Home", "Blog")

    def test_structured_data_outranks_the_dom(self):
        """A `BreadcrumbList` asserts a trail; a CSS class only suggests one."""
        trail = extract_breadcrumb(YOAST + SHOPIFY_DOM, BASE)
        assert trail.source == "jsonld"

    def test_a_nested_anchor_does_not_duplicate_a_crumb(self):
        html = '<nav aria-label="Breadcrumb"><a href="/"><span>Home</span></a></nav>'
        assert extract_breadcrumb(html, BASE).labels == ("Home",)


class TestAbsenceAndHostileInput:
    """An absent breadcrumb is a fact about the page, not a failure."""

    def test_a_page_without_one_reports_none(self):
        assert extract_breadcrumb("<html><body><p>Hi</p></body></html>", BASE).source == "none"

    def test_empty_html(self):
        assert extract_breadcrumb("", BASE).is_empty is True

    def test_malformed_json_does_not_lose_the_valid_block(self):
        html = '<script type="application/ld+json">{not json</script>' + YOAST
        assert extract_breadcrumb(html, BASE).labels == ("Home", "Services", "Cloud")

    def test_item_list_element_may_be_a_single_object(self):
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":
          {"@type":"ListItem","position":1,"name":"Home","item":"https://e.com/"}}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("Home",)

    def test_a_nameless_item_is_skipped_not_blank(self):
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":1,"item":"https://e.com/"},
          {"@type":"ListItem","position":2,"name":"Real","item":"https://e.com/r"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("Real",)

    def test_a_very_long_trail_is_capped(self):
        items = ",".join(
            f'{{"@type":"ListItem","position":{i},"name":"L{i}","item":"https://e.com/{i}"}}'
            for i in range(1, 60)
        )
        html = (
            '<script type="application/ld+json">'
            f'{{"@type":"BreadcrumbList","itemListElement":[{items}]}}'
            "</script>"
        )
        assert len(extract_breadcrumb(html, BASE).steps) <= MAX_BREADCRUMB_STEPS

    def test_an_unparseable_crumb_url_does_not_abort_the_trail(self):
        html = """<script type="application/ld+json">
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":1,"name":"Bad","item":"http://[abc"},
          {"@type":"ListItem","position":2,"name":"Good","item":"https://e.com/g"}]}
        </script>"""
        assert extract_breadcrumb(html, BASE).labels == ("Bad", "Good")


class TestBreadcrumbContainerDetection:
    """The header-menu parser needs this too.

    A breadcrumb commonly carries `role="navigation"`, which made it
    indistinguishable from the site menu: allbirds.com's `Home` and `Men's
    Shoes` were parsed as top-level tabs beside the real ones.
    """

    @pytest.mark.parametrize(
        "attributes",
        [
            {"aria-label": "Breadcrumb"},
            {"aria-label": "breadcrumbs"},
            {"class": "breadcrumb-trail"},
            {"class": "site-Breadcrumbs"},
            {"id": "breadcrumbs"},
            {"itemtype": "https://schema.org/BreadcrumbList"},
        ],
    )
    def test_recognised(self, attributes):
        assert is_breadcrumb_container(attributes) is True

    @pytest.mark.parametrize(
        "attributes",
        [{"aria-label": "Primary"}, {"class": "nav_links_wrap"}, {}, {"role": "navigation"}],
    )
    def test_a_real_menu_is_not_mistaken_for_one(self, attributes):
        assert is_breadcrumb_container(attributes) is False
