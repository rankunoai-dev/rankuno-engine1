"""Tests for the `--crawl-list` generator (ADR 0023).

Two classes of claim are pinned here, and they fail differently:

* The **counts**, because a UI renders them as prose an operator cannot
  check — "Excluded 18 external URLs" is a statement about data they will
  never see. Every stage is asserted, and so is the identity that they sum
  to the kept total.
* The **refusals**, because both of them (empty after filtering, over the
  ceiling) are deliberate choices to stop rather than to silently produce
  less. A regression that turned either into a quiet trim would still pass
  a test that only checked the happy path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from src.core.url_safety import SafeUrl, UrlSafetyPolicy
from src.modules.seo.screaming_frog_control.url_list import (
    LIST_ENCODING,
    LIST_LINE_ENDING,
    EmptyUrlListError,
    UrlListManifest,
    UrlListSource,
    UrlListTooLargeError,
    build_url_list,
    fingerprint,
    read_url_list_file,
    render_url_list,
)

PUBLIC_IP = "93.184.216.34"
BASE = "https://example.com/"


def _policy(resolver=None) -> UrlSafetyPolicy:
    return UrlSafetyPolicy(resolver=resolver or (lambda _host: [PUBLIC_IP]))


def _build(
    urls, *, source=UrlListSource.ALL, max_urls=10_000, base=BASE, policy=None
) -> tuple[UrlListManifest, bytes]:
    return build_url_list(
        urls,
        source=source,
        source_job_id="job-1",
        source_label="Crawl: example.com",
        base_url=base,
        max_urls=max_urls,
        policy=policy or _policy(),
    )


class TestRendering:
    def test_lines_are_crlf_terminated_utf8_without_a_bom(self):
        body = render_url_list(["https://example.com/a", "https://example.com/b"])
        assert body == b"https://example.com/a\r\nhttps://example.com/b\r\n"
        assert not body.startswith(b"\xef\xbb\xbf")
        assert LIST_LINE_ENDING == "\r\n"
        assert LIST_ENCODING == "utf-8"

    def test_a_non_ascii_url_round_trips(self):
        body = render_url_list(["https://example.com/café"])
        assert read_url_list_file(body) == ("https://example.com/café",)

    def test_a_bom_is_stripped_on_read(self):
        """An operator who re-saved the file from Notepad must not lose a row."""
        body = b"\xef\xbb\xbf" + render_url_list(["https://example.com/a"])
        assert read_url_list_file(body) == ("https://example.com/a",)

    def test_bare_lf_and_blank_lines_are_tolerated_on_read(self):
        assert read_url_list_file(b"https://a/\n\nhttps://b/\n") == ("https://a/", "https://b/")

    def test_fingerprint_is_sha256_of_the_exact_bytes(self):
        body = render_url_list(["https://example.com/a"])
        assert fingerprint(body) == hashlib.sha256(body).hexdigest()

    def test_the_same_urls_rendered_with_lf_hash_differently(self):
        """Line endings are inside what is signed, deliberately.

        A worker that re-rendered the approved URLs its own way would produce
        a different digest and be refused — correct, because that file is not
        the file that was approved.
        """
        crlf = render_url_list(["https://example.com/a"])
        lf = b"https://example.com/a\n"
        assert fingerprint(crlf) != fingerprint(lf)


class TestFiltering:
    def test_a_clean_list_keeps_everything(self):
        manifest, body = _build(["https://example.com/a", "https://example.com/b"])
        assert manifest.url_count == 2
        assert manifest.counts.kept == 2
        assert manifest.sha256 == fingerprint(body)

    def test_duplicates_are_dropped_and_counted(self):
        manifest, _ = _build(["https://example.com/a", "https://example.com/a"])
        assert manifest.url_count == 1
        assert manifest.counts.duplicates_dropped == 1

    def test_fragments_collapse_to_one_page(self):
        """Two anchors on one page are one fetch, not two of a licensed seat."""
        manifest, body = _build(["https://example.com/a#pricing", "https://example.com/a#contact"])
        assert manifest.url_count == 1
        assert read_url_list_file(body) == ("https://example.com/a",)
        assert manifest.counts.duplicates_dropped == 1

    def test_query_string_variants_are_kept_apart(self):
        """`?page=2` is a different resource; collapsing it would drop real pages."""
        manifest, _ = _build(["https://example.com/a?page=1", "https://example.com/a?page=2"])
        assert manifest.url_count == 2
        assert manifest.counts.duplicates_dropped == 0

    def test_non_http_schemes_are_dropped_and_counted(self):
        manifest, _ = _build(
            ["https://example.com/a", "mailto:x@example.com", "tel:+1", "ftp://example.com/f"]
        )
        assert manifest.url_count == 1
        assert manifest.counts.non_http_dropped == 3

    def test_off_domain_urls_are_dropped_and_counted_not_refused(self):
        urls = ["https://example.com/a", *[f"https://other{n}.com/x" for n in range(18)]]
        manifest, _ = _build(urls)
        assert manifest.url_count == 1
        assert manifest.counts.off_domain_dropped == 18
        assert manifest.registrable_domain == "example.com"

    def test_a_subdomain_of_the_same_registrable_domain_is_kept(self):
        manifest, _ = _build(["https://blog.example.com/a", "https://www.example.com/b"])
        assert manifest.url_count == 2
        assert manifest.counts.off_domain_dropped == 0

    def test_every_stage_reconciles_to_the_kept_total(self):
        manifest, _ = _build(
            [
                "https://example.com/a",
                "https://example.com/a",
                "mailto:x@example.com",
                "https://other.com/x",
                "https://example.com/b#frag",
            ]
        )
        c = manifest.counts
        assert (
            c.source_rows
            - c.duplicates_dropped
            - c.non_http_dropped
            - c.off_domain_dropped
            - c.unsafe_host_dropped
            == c.kept
        )

    def test_an_unparseable_base_url_disables_the_domain_filter(self):
        """Visible in the counts, rather than silently emptying the list."""
        manifest, _ = _build(["https://example.com/a", "https://other.com/b"], base="")
        assert manifest.url_count == 2
        assert manifest.counts.off_domain_dropped == 0
        assert manifest.registrable_domain == ""


class TestHostSafety:
    def test_a_host_failing_the_ssrf_check_is_dropped(self):
        def resolver(host: str) -> list[str]:
            return ["127.0.0.1"] if host == "internal.example.com" else [PUBLIC_IP]

        manifest, _ = _build(
            ["https://example.com/a", "https://internal.example.com/secret"],
            policy=_policy(resolver),
        )
        assert manifest.url_count == 1
        assert manifest.counts.unsafe_host_dropped == 1

    def test_each_unique_host_is_resolved_exactly_once(self):
        """50,000 URLs must not become 50,000 uncached `getaddrinfo` calls."""
        seen: list[str] = []

        def resolver(host: str) -> list[str]:
            seen.append(host)
            return [PUBLIC_IP]

        urls = [f"https://example.com/{n}" for n in range(500)]
        urls += [f"https://blog.example.com/{n}" for n in range(500)]
        manifest, _ = _build(urls, policy=_policy(resolver))
        assert manifest.url_count == 1000
        assert sorted(seen) == ["blog.example.com", "example.com"]

    def test_the_policy_never_sees_a_url_path(self):
        """One hostile path must not be able to poison a host every URL shares."""
        checked: list[str] = []

        class _Recording(UrlSafetyPolicy):
            def validate(self, url) -> SafeUrl:
                checked.append(url)
                return super().validate(url)

        _build(
            ["https://example.com/a", "https://example.com/b"],
            policy=_Recording(resolver=lambda _h: [PUBLIC_IP]),
        )
        assert checked == ["https://example.com/"]


class TestRefusals:
    def test_an_empty_source_refuses_with_the_counts(self):
        with pytest.raises(EmptyUrlListError) as excinfo:
            _build([])
        assert excinfo.value.counts.source_rows == 0

    def test_a_list_that_is_entirely_off_domain_refuses_rather_than_dispatching_nothing(self):
        with pytest.raises(EmptyUrlListError) as excinfo:
            _build(["https://other.com/a", "https://elsewhere.com/b"])
        assert excinfo.value.counts.off_domain_dropped == 2
        assert "outside the crawl's own domain" in str(excinfo.value)

    def test_a_one_url_list_is_allowed(self):
        manifest, body = _build(["https://example.com/only"])
        assert manifest.url_count == 1
        assert manifest.sample == ("https://example.com/only",)
        assert read_url_list_file(body) == ("https://example.com/only",)

    def test_exceeding_the_ceiling_refuses_and_does_not_trim(self):
        urls = [f"https://example.com/{n}" for n in range(11)]
        with pytest.raises(UrlListTooLargeError) as excinfo:
            _build(urls, max_urls=10)
        assert excinfo.value.url_count == 11
        assert excinfo.value.ceiling == 10
        assert "not silently substituted" in str(excinfo.value)

    def test_the_refusal_points_at_orphans_when_all_was_asked_for(self):
        with pytest.raises(UrlListTooLargeError) as excinfo:
            _build([f"https://example.com/{n}" for n in range(3)], max_urls=2)
        assert "Orphans Only" in str(excinfo.value)

    def test_the_refusal_does_not_point_at_orphans_when_orphans_was_asked_for(self):
        with pytest.raises(UrlListTooLargeError) as excinfo:
            _build(
                [f"https://example.com/{n}" for n in range(3)],
                max_urls=2,
                source=UrlListSource.ORPHANS,
            )
        assert "Orphans Only" not in str(excinfo.value)

    def test_exactly_the_ceiling_is_allowed(self):
        manifest, _ = _build([f"https://example.com/{n}" for n in range(10)], max_urls=10)
        assert manifest.url_count == 10


class TestManifest:
    def test_the_sample_is_the_first_three_in_order(self):
        manifest, _ = _build([f"https://example.com/{n}" for n in range(9)])
        assert manifest.sample == (
            "https://example.com/0",
            "https://example.com/1",
            "https://example.com/2",
        )

    def test_the_manifest_records_the_source_and_the_crawl(self):
        manifest, _ = _build(["https://example.com/a"], source=UrlListSource.ORPHANS)
        assert manifest.source is UrlListSource.ORPHANS
        assert manifest.source_job_id == "job-1"
        assert manifest.source_label == "Crawl: example.com"

    def test_two_different_lists_have_different_fingerprints(self):
        first, _ = _build(["https://example.com/a"])
        second, _ = _build(["https://example.com/b"])
        assert first.sha256 != second.sha256

    def test_the_same_urls_in_the_same_order_are_stable(self):
        first, _ = _build(["https://example.com/a", "https://example.com/b"])
        second, _ = _build(["https://example.com/a", "https://example.com/b"])
        assert first.sha256 == second.sha256

    def test_reordering_changes_the_fingerprint(self):
        """Order is part of the file, so it is part of what was approved."""
        first, _ = _build(["https://example.com/a", "https://example.com/b"])
        second, _ = _build(["https://example.com/b", "https://example.com/a"])
        assert first.sha256 != second.sha256

    def test_the_source_is_consumed_lazily(self):
        """A caller streaming a 93 MB result must not have it materialised."""
        consumed = 0

        def _source() -> Iterator[str]:
            nonlocal consumed
            for n in range(5):
                consumed += 1
                yield f"https://example.com/{n}"

        generator = _source()
        assert consumed == 0
        manifest, _ = _build(generator)
        assert manifest.url_count == 5
