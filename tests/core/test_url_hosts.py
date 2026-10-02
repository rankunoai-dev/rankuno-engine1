"""`src.core.url_hosts` moved out of `url_rules` for the worker (ADR 0030).

Behaviour is covered by the existing `url_rules` tests through the re-export;
these pin the re-export itself, so no caller can end up with a second copy.
"""

from __future__ import annotations

from src.core import url_hosts
from src.modules.seo.page_classifier import url_rules


def test_url_rules_re_exports_the_same_function_objects() -> None:
    assert url_rules.safe_split is url_hosts.safe_split
    assert url_rules.site_host is url_hosts.site_host
    assert url_rules.registrable_domain is url_hosts.registrable_domain


def test_the_helpers_behave_as_before() -> None:
    assert url_hosts.safe_split("http://[bad") is None
    assert url_hosts.site_host("user@WWW.Example.com:8080") == "example.com"
    assert url_hosts.registrable_domain("shop.example.co.uk") == "example.co.uk"
    assert url_hosts.registrable_domain("10.0.0.1") == "10.0.0.1"
