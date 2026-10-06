"""The job bundle contract and its URL audit (ADR 0034, audit conditions 2 and 9)."""

from __future__ import annotations

import typing
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from src.modules.seo.page_classifier.job_bundle import (
    CANONICAL_URL_FIELDS,
    MAX_BUNDLE_HOMEPAGE_BYTES,
    NOT_A_LINK_URL_FIELDS,
    STRICT_URL_FIELDS,
    JobImportBundle,
    audit_url_schemes,
    url_scheme,
)
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationOutput

from tests.modules.seo.job_bundle_factory import BASE, bundle_dict

HOSTILE = (
    "javascript:alert(1)",
    " JavaScript:alert(1)",
    "java\tscript:alert(1)",
    "\x00javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
)


def _validated(**overrides: Any) -> JobImportBundle:
    return JobImportBundle.model_validate(bundle_dict(**overrides))


class TestUrlScheme:
    @pytest.mark.parametrize(
        ("value", "scheme"),
        [
            ("https://example.com/", "https"),
            ("HTTP://example.com/", "http"),
            ("java\tscript:alert(1)", "javascript"),
            ("java\nscript:alert(1)", "javascript"),
            ("  \x01javascript:x", "javascript"),
            ("www.http://infosys.com/a", "www.http"),
            ("/relative/path", None),
            ("no-colon-at-all", None),
            ("1http://x", None),
        ],
    )
    def test_reads_the_scheme_a_browser_would(self, value: str, scheme: str | None) -> None:
        assert url_scheme(value) == scheme


class TestAuditPassesRealShapes:
    def test_a_clean_bundle_has_no_failures(self) -> None:
        assert audit_url_schemes(_validated()) == []

    def test_a_scheme_less_dotted_canonical_from_a_real_crawl_is_accepted(self) -> None:
        # 10 of 1,333 local results carry exactly this shape (the site's own claim).
        data = bundle_dict()
        data["result"]["pages"][0]["canonical_url"] = (
            "www.http://infosys.com/confluence/2026/apac/live-blog.html"
        )
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == []

    def test_a_relative_canonical_is_accepted_as_text(self) -> None:
        data = bundle_dict()
        data["result"]["pages"][0]["canonical_url"] = "/page-0"
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == []

    def test_an_sc_domain_gsc_property_is_not_walked(self) -> None:
        data = bundle_dict()
        data["request"]["gsc_property_url"] = "sc-domain:example.com"
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == []


def _poison(data: dict[str, Any], location: str, value: str) -> None:
    result = data["result"]
    request = data["request"]
    targets = {
        "request.base_url": lambda: request.__setitem__("base_url", value),
        "request.seed_urls[0]": lambda: request.__setitem__("seed_urls", [value]),
        "request.exclude_urls[0]": lambda: request.__setitem__("exclude_urls", [value]),
        "result.base_url": lambda: result.__setitem__("base_url", value),
        "result.discovery.base_url": lambda: result["discovery"].__setitem__("base_url", value),
        "result.pages[1].url": lambda: result["pages"][1].__setitem__("url", value),
        "result.pages[1].canonical_url": lambda: result["pages"][1].__setitem__(
            "canonical_url", value
        ),
        "result.pages[1].final_url": lambda: result["pages"][1].__setitem__("final_url", value),
        "result.pages[1].redirect_chain[1]": lambda: result["pages"][1][
            "redirect_chain"
        ].__setitem__(1, value),
        "result.pages[1].nav_parent_url": lambda: result["pages"][1].__setitem__(
            "nav_parent_url", value
        ),
        "result.navigation.roots[0].url": lambda: result["navigation"]["roots"][0].__setitem__(
            "url", value
        ),
        "result.navigation.roots[0].children[0].url": lambda: result["navigation"]["roots"][0][
            "children"
        ][0].__setitem__("url", value),
    }
    targets[location]()


ALL_LOCATIONS = (
    "request.base_url",
    "request.seed_urls[0]",
    "request.exclude_urls[0]",
    "result.base_url",
    "result.discovery.base_url",
    "result.pages[1].url",
    "result.pages[1].canonical_url",
    "result.pages[1].final_url",
    "result.pages[1].redirect_chain[1]",
    "result.pages[1].nav_parent_url",
    "result.navigation.roots[0].url",
    "result.navigation.roots[0].children[0].url",
)


class TestAuditRejects:
    @pytest.mark.parametrize("location", ALL_LOCATIONS)
    def test_a_javascript_url_in_every_walked_field_is_reported(self, location: str) -> None:
        data = bundle_dict()
        _poison(data, location, "javascript:alert(document.cookie)")
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == [location]

    @pytest.mark.parametrize("value", HOSTILE)
    def test_every_hostile_scheme_is_refused_as_a_canonical(self, value: str) -> None:
        data = bundle_dict()
        _poison(data, "result.pages[1].canonical_url", value)
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == [
            "result.pages[1].canonical_url"
        ]

    @pytest.mark.parametrize(
        "value", ["www.http://infosys.com/x", "/relative", "http:///no-host", "ftp://example.com/"]
    )
    def test_strict_fields_need_http_and_a_host(self, value: str) -> None:
        data = bundle_dict()
        _poison(data, "result.pages[1].url", value)
        assert audit_url_schemes(JobImportBundle.model_validate(data)) == ["result.pages[1].url"]

    def test_failures_are_locations_never_values(self) -> None:
        data = bundle_dict()
        _poison(data, "result.pages[1].url", "javascript:SECRET_MARKER")
        assert "SECRET_MARKER" not in repr(audit_url_schemes(JobImportBundle.model_validate(data)))


def _holds_str(annotation: object) -> bool:
    """True for `str`, `str | None`, `tuple[str, ...]`, `list[str]`: text, not a count."""
    if annotation is str:
        return True
    return any(_holds_str(arg) for arg in typing.get_args(annotation))


def _url_named_fields(model: type[BaseModel], path: str, seen: set[type]) -> set[str]:
    if model in seen:
        return set()
    found: set[str] = set()
    for name, field in model.model_fields.items():
        here = f"{path}.{name}"
        if ("url" in name or "href" in name or name == "redirect_chain") and _holds_str(
            field.annotation
        ):
            found.add(here)
        for arg in (field.annotation, *typing.get_args(field.annotation)):
            for candidate in (arg, *typing.get_args(arg)):
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    found |= _url_named_fields(candidate, here, seen | {model})
    return found


class TestEveryUrlFieldIsClassified:
    def test_no_url_named_field_escapes_the_audit(self) -> None:
        """A new URL field must be added to one of the three sets, or this fails.

        The walk is explicit by design; this test is what keeps it complete.
        """
        found = _url_named_fields(PageClassificationOutput, "result", set()) | _url_named_fields(
            PageClassificationInput, "request", set()
        )
        found.discard("result.navigation.roots.children")  # the recursion, already walked
        classified = STRICT_URL_FIELDS | CANONICAL_URL_FIELDS | NOT_A_LINK_URL_FIELDS
        assert found - classified == set()


class TestEnvelope:
    @pytest.mark.parametrize("field", ["org_id", "id", "job_id", "has_result", "telemetry"])
    def test_server_decided_fields_are_forbidden(self, field: str) -> None:
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(**{field: "x"}))

    @pytest.mark.parametrize("status", ["failed", "queued", "running", "SUCCEEDED"])
    def test_only_finished_outcomes_import(self, status: str) -> None:
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(status=status))

    def test_wrong_format_or_version_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(format="other"))
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(version=2))

    def test_a_finish_before_the_start_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="before started_at"):
            JobImportBundle.model_validate(bundle_dict(finished_at="2026-10-06T17:00:00+00:00"))

    def test_a_finish_in_the_future_is_refused(self) -> None:
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        with pytest.raises(ValidationError, match="in the future"):
            JobImportBundle.model_validate(bundle_dict(finished_at=future))

    def test_a_naive_timestamp_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(started_at="2026-10-06T17:00:00"))

    def test_an_oversized_homepage_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="5 MiB"):
            JobImportBundle.model_validate(
                bundle_dict(homepage_html="x" * (MAX_BUNDLE_HOMEPAGE_BYTES + 1))
            )

    def test_source_ids_cannot_carry_a_path(self) -> None:
        for source in (
            {"source_instance_id": "../../etc", "source_job_id": "0" * 32},
            {"source_instance_id": "li-ok-instance", "source_job_id": "../" + "0" * 29},
            {"source_instance_id": "LI-UPPER-CASE", "source_job_id": "0" * 32},
        ):
            with pytest.raises(ValidationError):
                JobImportBundle.model_validate(bundle_dict(source=source))

    def test_the_label_and_error_are_bounded(self) -> None:
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(label="x" * 201))
        with pytest.raises(ValidationError):
            JobImportBundle.model_validate(bundle_dict(status="partial", error="x" * 2001))

    def test_the_base_url_fixture_is_what_the_audit_sees(self) -> None:
        assert _validated().result.base_url == BASE
