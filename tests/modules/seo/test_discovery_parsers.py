"""Tests for the three discovery paths' payload parsing.

All pure functions over text. Hostile-input cases matter here more than
elsewhere: sitemaps and CMS payloads come from arbitrary third-party hosts.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.discovery_parsers import (
    SitemapKind,
    extract_page_links,
    parse_shopify_records,
    parse_sitemap,
    parse_wordpress_records,
)

SITEMAP_NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'

URLSET = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset {SITEMAP_NS}>
  <url><loc>https://e.com/a/</loc></url>
  <url><loc>https://e.com/b/</loc></url>
</urlset>"""

INDEX = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex {SITEMAP_NS}>
  <sitemap><loc>https://e.com/blog-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://e.com/product-sitemap.xml</loc></sitemap>
</sitemapindex>"""

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<urlset><url><loc>&lol3;</loc></url></urlset>"""

XXE = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<urlset><url><loc>&xxe;</loc></url></urlset>"""


class TestSitemapParsing:
    def test_parses_a_urlset(self):
        document = parse_sitemap(URLSET, "post-sitemap.xml")
        assert document.kind is SitemapKind.URLSET
        assert document.is_index is False
        assert document.locations == ("https://e.com/a/", "https://e.com/b/")
        assert document.source_name == "post-sitemap.xml"

    def test_parses_an_index(self):
        document = parse_sitemap(INDEX, "sitemap_index.xml")
        assert document.kind is SitemapKind.INDEX
        assert document.is_index is True
        assert len(document.locations) == 2

    def test_namespace_declaration_is_irrelevant(self):
        """Real sitemaps vary the namespace; parsing must not depend on it."""
        without_ns = "<urlset><url><loc>https://e.com/x/</loc></url></urlset>"
        assert parse_sitemap(without_ns).locations == ("https://e.com/x/",)

    def test_deduplicates_locations(self):
        xml = "<urlset><url><loc>https://e.com/a/</loc></url><url><loc>https://e.com/a/</loc></url></urlset>"
        assert parse_sitemap(xml).locations == ("https://e.com/a/",)

    def test_skips_empty_loc_elements(self):
        xml = "<urlset><url><loc></loc></url><url><loc>https://e.com/a/</loc></url></urlset>"
        assert parse_sitemap(xml).locations == ("https://e.com/a/",)

    @pytest.mark.parametrize("payload", ["", "   ", "not xml at all", "<urlset><unclosed>"])
    def test_unparseable_input_yields_an_empty_document(self, payload):
        """One broken sitemap must not abort discovery for the whole site."""
        document = parse_sitemap(payload)
        assert document.kind is SitemapKind.UNKNOWN
        assert document.locations == ()

    def test_unexpected_root_element_yields_nothing(self):
        assert parse_sitemap("<html><body>oops</body></html>").locations == ()


class TestSitemapHostileInput:
    """The guarantee is that no declared entity is ever expanded.

    It is upheld structurally rather than by rejecting documents: parsing starts
    at the root element, a DTD can only appear before it, so a declaration can
    never be in scope. A surviving `&ref;` is then an *undefined* entity, which
    expat reports as a parse error.
    """

    def test_billion_laughs_yields_nothing(self):
        """Entity expansion is a live DoS vector against a crawler."""
        document = parse_sitemap(BILLION_LAUGHS, "evil.xml")
        assert document.kind is SitemapKind.UNKNOWN
        assert document.locations == ()

    def test_xxe_yields_nothing(self):
        document = parse_sitemap(XXE, "evil.xml")
        assert document.locations == ()

    def test_no_declared_entity_survives_into_the_output(self):
        """The specific regression: a DTD alongside an otherwise valid urlset.

        Slicing must not carry the declaration into the parse. If it ever did,
        `/etc/passwd` would land in `locations` and be crawled.
        """
        hostile = (
            '<!DOCTYPE t [<!ENTITY p SYSTEM "file:///etc/passwd">]>'
            "<urlset><url><loc>https://e.com/a/</loc></url>"
            "<url><loc>&p;</loc></url></urlset>"
        )
        document = parse_sitemap(hostile, "evil.xml")
        assert document.locations == ()

    def test_predefined_entities_still_work(self):
        """`&amp;` is built into XML, not declared, so it must survive."""
        xml = "<urlset><url><loc>https://e.com/a/?x=1&amp;y=2</loc></url></urlset>"
        assert parse_sitemap(xml).locations == ("https://e.com/a/?x=1&y=2",)

    def test_a_plain_sitemap_still_parses(self):
        """Sanity check that the guard cannot reject valid input."""
        assert parse_sitemap(URLSET).kind is SitemapKind.URLSET


class TestWordPressWrappedSitemap:
    """Yoast and RankMath serve sitemaps inside an XHTML skin.

    The wrapper exists so the file renders as a styled page in a browser, and it
    carries a doctype. Rejecting on doctype discarded these sites' sitemaps in
    full — the entire reason this parser was rewritten (build-log 0012).
    """

    @staticmethod
    def _wrapped(inner: str) -> str:
        return (
            "<!DOCTYPE html>\n<html>\n<head>"
            '<link rel="stylesheet" href="//e.com/main-sitemap.xsl"/>'
            "</head>\n<body>\n<!-- Yoast SEO sitemap -->\n"
            f"{inner}\n</body>\n</html>"
        )

    def test_parses_every_url_from_a_wrapped_urlset(self):
        urls = [f"https://e.com/post-{index}/" for index in range(50)]
        entries = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        document = parse_sitemap(
            self._wrapped(f"<urlset {SITEMAP_NS}>{entries}</urlset>"), "post-sitemap.xml"
        )
        assert document.kind is SitemapKind.URLSET
        assert document.locations == tuple(urls)
        assert document.source_name == "post-sitemap.xml"

    def test_parses_a_wrapped_index(self):
        document = parse_sitemap(self._wrapped(INDEX.split("?>", 1)[1]), "sitemap_index.xml")
        assert document.kind is SitemapKind.INDEX
        assert len(document.locations) == 2

    def test_handles_a_namespace_prefixed_root(self):
        inner = (
            '<sm:urlset xmlns:sm="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sm:url><sm:loc>https://e.com/a/</sm:loc></sm:url></sm:urlset>"
        )
        document = parse_sitemap(self._wrapped(inner))
        assert document.kind is SitemapKind.URLSET
        assert document.locations == ("https://e.com/a/",)

    def test_markup_after_the_closing_tag_is_discarded(self):
        """The wrapper's trailing `</body></html>` must not break the parse."""
        assert parse_sitemap(self._wrapped(URLSET.split("?>", 1)[1])).locations == (
            "https://e.com/a/",
            "https://e.com/b/",
        )

    def test_an_empty_self_closing_urlset_is_recognised(self):
        """A site with nothing in a sitemap is valid, not broken."""
        document = parse_sitemap(self._wrapped(f"<urlset {SITEMAP_NS}/>"))
        assert document.kind is SitemapKind.URLSET
        assert document.locations == ()


class TestLinkExtraction:
    def test_resolves_relative_links(self):
        html = '<a href="/services/">S</a><a href="about/">A</a>'
        links = extract_page_links(html, "https://e.com/company/")
        assert "https://e.com/services/" in links
        assert "https://e.com/company/about/" in links

    def test_finds_links_outside_navigation(self):
        """Path B differs from Signal 1: every anchor counts, not just nav."""
        html = '<main><article><a href="/deep/page/">Deep</a></article></main>'
        assert extract_page_links(html, "https://e.com/") == ("https://e.com/deep/page/",)

    def test_drops_external_hosts_by_default(self):
        html = '<a href="https://other.com/x">out</a><a href="/in/">in</a>'
        assert extract_page_links(html, "https://e.com/") == ("https://e.com/in/",)

    def test_can_include_external_hosts(self):
        html = '<a href="https://other.com/x">out</a>'
        links = extract_page_links(html, "https://e.com/", same_host_only=False)
        assert links == ("https://other.com/x",)

    @pytest.mark.parametrize(
        "href", ["#section", "javascript:void(0)", "mailto:a@b.com", "tel:123", "data:text/plain,x"]
    )
    def test_skips_non_navigational_hrefs(self, href):
        assert extract_page_links(f'<a href="{href}">x</a>', "https://e.com/") == ()

    @pytest.mark.parametrize(
        "path", ["/logo.png", "/app.js", "/style.css", "/doc.zip", "/video.mp4", "/font.woff2"]
    )
    def test_skips_non_page_assets(self, path):
        """Following assets wastes budget and pollutes the graph."""
        assert extract_page_links(f'<a href="{path}">x</a>', "https://e.com/") == ()

    def test_strips_fragments(self):
        html = '<a href="/page/#section">x</a>'
        assert extract_page_links(html, "https://e.com/") == ("https://e.com/page/",)

    def test_deduplicates(self):
        html = '<a href="/a/">1</a><a href="/a/">2</a>'
        assert extract_page_links(html, "https://e.com/") == ("https://e.com/a/",)

    def test_malformed_markup_does_not_raise(self):
        assert isinstance(extract_page_links("<a href=/x>unclosed", "https://e.com/"), tuple)

    def test_empty_html_yields_nothing(self):
        assert extract_page_links("", "https://e.com/") == ()

    def test_rejects_non_http_schemes(self):
        assert extract_page_links('<a href="ftp://e.com/f">x</a>', "https://e.com/") == ()


class TestWordPressRecords:
    PAYLOAD = """[
      {"id": 1, "link": "https://e.com/services/", "parent": 0},
      {"id": 2, "link": "https://e.com/capsules/", "parent": 1},
      {"id": 3, "link": "https://e.com/about/", "parent": 0}
    ]"""

    def test_resolves_parent_urls(self):
        """The flat-URL fix: the database states hierarchy the slug cannot."""
        records = parse_wordpress_records(self.PAYLOAD)
        capsules = records["https://e.com/capsules/"]
        assert capsules.parent_id == 1
        assert capsules.parent_url == "https://e.com/services/"

    def test_marks_pages_that_have_children(self):
        records = parse_wordpress_records(self.PAYLOAD)
        assert records["https://e.com/services/"].has_children is True
        assert records["https://e.com/about/"].has_children is False

    def test_treats_parent_zero_as_root(self):
        records = parse_wordpress_records(self.PAYLOAD)
        assert records["https://e.com/services/"].parent_id is None

    def test_records_the_requested_type(self):
        records = parse_wordpress_records(self.PAYLOAD, "post")
        assert all(record.record_type == "post" for record in records.values())

    @pytest.mark.parametrize("payload", ["", "not json", "{}", '{"error": "forbidden"}'])
    def test_malformed_payload_yields_nothing(self, payload):
        assert parse_wordpress_records(payload) == {}

    def test_skips_entries_missing_required_fields(self):
        payload = '[{"id": 1}, {"link": "https://e.com/x/"}, {"id": 2, "link": "https://e.com/y/"}]'
        assert set(parse_wordpress_records(payload)) == {"https://e.com/y/"}


class TestShopifyRecords:
    def test_builds_product_urls_from_handles(self):
        payload = '{"products": [{"handle": "blue-widget"}, {"handle": "red-widget"}]}'
        records = parse_shopify_records(payload, "https://shop.com")
        assert "https://shop.com/products/blue-widget" in records
        assert records["https://shop.com/products/blue-widget"].record_type == "product"

    def test_builds_collection_urls(self):
        payload = '{"collections": [{"handle": "summer"}]}'
        records = parse_shopify_records(payload, "https://shop.com", collection="collections")
        assert records["https://shop.com/collections/summer"].record_type == "collection"
        assert records["https://shop.com/collections/summer"].has_children is True

    def test_tolerates_a_trailing_slash_on_the_base(self):
        payload = '{"products": [{"handle": "x"}]}'
        assert "https://shop.com/products/x" in parse_shopify_records(payload, "https://shop.com/")

    @pytest.mark.parametrize("payload", ["", "[]", "not json", '{"products": "nope"}'])
    def test_malformed_payload_yields_nothing(self, payload):
        assert parse_shopify_records(payload, "https://shop.com") == {}

    def test_skips_entries_without_a_handle(self):
        payload = '{"products": [{"title": "no handle"}, {"handle": "ok"}]}'
        assert set(parse_shopify_records(payload, "https://s.com")) == {"https://s.com/products/ok"}


class TestMalformedLinkIsolation:
    """One unparseable href must not cost a page its other links."""

    def test_a_bracketed_non_ip_href_is_skipped(self):
        html = '<a href="http://[invalid-ipv6]/">bad</a><a href="/good/">good</a>'
        assert extract_page_links(html, "https://e.com/") == ("https://e.com/good/",)

    def test_several_malformed_hrefs_do_not_abort_extraction(self):
        html = (
            '<a href="http://[bad]/">1</a>'
            '<a href="/keep-1/">2</a>'
            '<a href="http://[also:bad:host]/">3</a>'
            '<a href="/keep-2/">4</a>'
        )
        links = extract_page_links(html, "https://e.com/")
        assert links == ("https://e.com/keep-1/", "https://e.com/keep-2/")

    def test_a_valid_ipv6_href_is_not_discarded_as_malformed(self):
        """Only unparseable hosts are skipped, not every bracketed one."""
        links = extract_page_links(
            '<a href="http://[2001:db8::1]/x/">v6</a>', "http://[2001:db8::1]/"
        )
        assert links == ("http://[2001:db8::1]/x/",)
