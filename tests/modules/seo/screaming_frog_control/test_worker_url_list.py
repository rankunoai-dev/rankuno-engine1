"""The worker's own check on the list it was handed (ADR 0023).

This is the last gate of the four, and the only one that runs on the machine
that will actually execute the crawl. Its whole job is to refuse bytes that
are not the bytes a human approved, so the tests that matter are the ones
where the download is wrong rather than the one where it is right.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.core.errors import IntegrationError
from src.core.worker_dispatch_schemas import DispatchAssignmentClaims, WorkerJobKind
from src.modules.seo.screaming_frog_control.url_list import fingerprint, render_url_list
from src.modules.seo.screaming_frog_control.worker_url_list import (
    URL_LIST_FILENAME,
    EmptyApprovedListError,
    UrlListIntegrityError,
    prepare_url_list,
)

URLS = ("https://example.com/a", "https://example.com/b", "https://example.com/c")
BODY = render_url_list(URLS)
DIGEST = fingerprint(BODY)


class _FakeClient:
    """Returns a fixed body, or raises. Stands in for `WorkerCloudClient`."""

    def __init__(self, body: bytes | None = None, error: Exception | None = None) -> None:
        self._body = body
        self._error = error
        self.calls: list[str] = []

    def fetch_url_list(self, job_id: str) -> bytes:
        self.calls.append(job_id)
        if self._error is not None:
            raise self._error
        assert self._body is not None
        return self._body


def _claims(sha256: str | None = DIGEST) -> DispatchAssignmentClaims:
    now = datetime.now(UTC)
    return DispatchAssignmentClaims(
        job_id="job-1",
        worker_id="wkr-1",
        org_id="default",
        kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
        seed_url="https://example.com/",
        template_name=None,
        correlation_id="c1",
        url_list_sha256=sha256,
        jti="j1",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


class TestHappyPath:
    def test_writes_the_file_under_the_jobs_own_output_directory(self, tmp_path):
        client = _FakeClient(BODY)

        invocation = prepare_url_list(
            client, _claims(), output_root=tmp_path, seed_url="https://example.com/"
        )

        assert invocation.path == tmp_path / "job-1" / URL_LIST_FILENAME
        assert invocation.path.exists()
        assert client.calls == ["job-1"]

    def test_the_written_file_is_crlf_utf8_without_a_bom(self, tmp_path):
        """What a Windows desktop Java application reads without surprises."""
        invocation = prepare_url_list(
            _FakeClient(BODY), _claims(), output_root=tmp_path, seed_url="https://example.com/"
        )

        written = invocation.path.read_bytes()
        assert written == BODY
        assert b"\r\n" in written
        assert not written.startswith(b"\xef\xbb\xbf")

    def test_the_count_comes_from_the_bytes_on_disk(self, tmp_path):
        invocation = prepare_url_list(
            _FakeClient(BODY), _claims(), output_root=tmp_path, seed_url="https://example.com/"
        )
        assert invocation.url_count == 3
        assert invocation.sample == URLS

    def test_a_bom_in_the_download_is_normalised_away(self, tmp_path):
        """The digest is checked on the raw bytes, so this cannot launder one."""
        body = b"\xef\xbb\xbf" + BODY
        claims = _claims(fingerprint(body))

        invocation = prepare_url_list(
            _FakeClient(body), claims, output_root=tmp_path, seed_url="https://example.com/"
        )

        assert not invocation.path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert invocation.url_count == 3

    def test_a_one_url_list_is_accepted(self, tmp_path):
        body = render_url_list(["https://example.com/only"])
        invocation = prepare_url_list(
            _FakeClient(body),
            _claims(fingerprint(body)),
            output_root=tmp_path,
            seed_url="https://example.com/",
        )
        assert invocation.url_count == 1


class TestRefusals:
    def test_one_mutated_url_is_refused(self, tmp_path):
        """The whole point: a single altered character breaks the binding."""
        tampered = render_url_list(
            ("https://example.com/a", "https://example.com/EVIL", "https://example.com/c")
        )

        with pytest.raises(UrlListIntegrityError) as excinfo:
            prepare_url_list(
                _FakeClient(tampered),
                _claims(),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )

        assert excinfo.value.expected == DIGEST
        assert excinfo.value.actual == fingerprint(tampered)

    def test_an_appended_url_is_refused(self, tmp_path):
        """Preview three, deliver four. This is the attack the hash exists for."""
        extended = render_url_list((*URLS, "https://example.com/extra"))

        with pytest.raises(UrlListIntegrityError):
            prepare_url_list(
                _FakeClient(extended),
                _claims(),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )

    def test_the_refusal_says_nothing_was_crawled_and_is_not_transient(self, tmp_path):
        with pytest.raises(UrlListIntegrityError) as excinfo:
            prepare_url_list(
                _FakeClient(b"different\r\n"),
                _claims(),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )

        message = str(excinfo.value)
        assert "Nothing was crawled" in message
        assert "not a transient failure" in message

    def test_nothing_is_written_when_the_digest_does_not_match(self, tmp_path):
        with pytest.raises(UrlListIntegrityError):
            prepare_url_list(
                _FakeClient(b"different\r\n"),
                _claims(),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )
        assert not (tmp_path / "job-1" / URL_LIST_FILENAME).exists()

    def test_claims_carrying_no_digest_are_refused_rather_than_trusted(self, tmp_path):
        """Reaching here without a digest is a bug, and must not run a crawl."""
        with pytest.raises(UrlListIntegrityError):
            prepare_url_list(
                _FakeClient(BODY),
                _claims(None),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )

    def test_an_empty_but_correctly_hashed_list_gets_its_own_error(self, tmp_path):
        """Saying "fingerprint mismatch" here would send someone hunting an attacker."""
        body = b""
        with pytest.raises(EmptyApprovedListError) as excinfo:
            prepare_url_list(
                _FakeClient(body),
                _claims(fingerprint(body)),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )
        assert "contains no URLs" in str(excinfo.value)

    def test_a_fetch_failure_propagates_rather_than_running_a_crawl(self, tmp_path):
        with pytest.raises(IntegrationError):
            prepare_url_list(
                _FakeClient(error=IntegrationError("rankuno.worker_cloud", "cloud unreachable")),
                _claims(),
                output_root=tmp_path,
                seed_url="https://example.com/",
            )
