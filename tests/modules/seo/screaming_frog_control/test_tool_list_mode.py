"""`ScreamingFrogControlTool` in `--crawl-list` list mode (ADR 0022).

A separate file from `test_tool.py`, which was already at this codebase's
length target and covers the `--crawl` path it has always covered. The fakes
are imported from there rather than copied, so the two files cannot drift
apart about what a supervised launch looks like.

Three properties are load-bearing here and each fails differently:

* The **argv branch** — exactly one start mode is ever emitted, and
  `--headless` keeps `argv[1]` (the documented anti-hang invariant).
* The **approval text** — `describe_invocation` is what a human reads before
  approving. A bare SHA-256 is not approvable, so the count, the crawl name
  and a real sample must all be in it.
* The **truncation check** — the first thing in this codebase that can tell a
  crawl which stopped early from a site that is simply that size.
"""

from __future__ import annotations

import pytest
from src.core.errors import UnsafeUrlError
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.screaming_frog_control.schemas import (
    ScreamingFrogJobInput,
    UrlListInvocation,
)
from src.modules.seo.screaming_frog_control.tool import ScreamingFrogLicenceError
from tests.modules.seo.screaming_frog_control.test_tool import (
    _ACTIVE_LICENCE_LINE,
    _PUBLIC_IP,
    _allow_all,
    _build_tool,
    _install_fake_launch,
)


@pytest.fixture
def fake_launch(tmp_path, monkeypatch) -> list[list[str]]:
    """A run that completes instantly with an active licence.

    Re-declared here rather than imported: a pytest fixture is registered by
    the module that defines it, so importing the function object would not
    make the name resolvable in this file. The body is one call into the
    shared helper, so there is no duplicated behaviour to drift.
    """
    return _install_fake_launch(tmp_path, monkeypatch)


def _completed(urls: int) -> str:
    return (
        f"INFO  - Completed the spider of https://e.com/ in 0 hrs 0 mins 1 secs (1), "
        f"null, crawled {urls} urls\n"
    )


def _url_list(tmp_path, *, count: int = 12_431) -> UrlListInvocation:
    """A list invocation whose file really exists, as the worker would leave it."""
    path = tmp_path / "output" / "job-1" / "url-list.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"https://e.com/a\r\n")
    return UrlListInvocation(
        path=path,
        url_count=count,
        sha256="a" * 64,
        source_label="Postman full crawl",
        source="orphans",
        sample=("https://e.com/a", "https://e.com/b", "https://e.com/c"),
    )


class TestListModeArgv:
    def test_crawl_list_replaces_crawl_and_names_the_file(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())
        url_list = _url_list(tmp_path)

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/", url_list=url_list))

        argv = fake_launch[0]
        assert "--crawl-list" in argv
        assert argv[argv.index("--crawl-list") + 1] == str(url_list.path)

    def test_crawl_is_never_emitted_alongside_crawl_list(self, tmp_path, fake_launch) -> None:
        """Two start modes would ask Screaming Frog to start twice."""
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path)))

        assert "--crawl" not in fake_launch[0]

    def test_headless_stays_at_index_one_in_list_mode(self, tmp_path, fake_launch) -> None:
        """The anti-hang invariant is not relaxed by the new branch."""
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path)))

        assert fake_launch[0][1] == "--headless"

    def test_the_seed_url_is_still_validated_in_list_mode(self, tmp_path, monkeypatch) -> None:
        """List mode does not become a way around the SSRF gate."""
        _install_fake_launch(tmp_path, monkeypatch)
        tool = _build_tool(tmp_path, guardrails=_allow_all())
        tool._url_policy = UrlSafetyPolicy(resolver=lambda _host: ["127.0.0.1"])  # noqa: SLF001

        with pytest.raises(UnsafeUrlError):
            tool.execute(
                ScreamingFrogJobInput(
                    seed_url="http://internal.example/", url_list=_url_list(tmp_path)
                )
            )

    def test_the_exports_and_output_folder_are_unchanged(self, tmp_path, fake_launch) -> None:
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path)))

        argv = fake_launch[0]
        assert "--output-folder" in argv
        assert "--export-tabs" in argv
        assert "--bulk-export" in argv

    def test_a_crawl_run_is_unaffected(self, tmp_path, fake_launch) -> None:
        """The path every pre-ADR-0022 caller takes must be byte-identical."""
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        argv = fake_launch[0]
        assert argv[1:4] == ["--headless", "--crawl", "https://e.com/"]
        assert "--crawl-list" not in argv


class TestListModeApprovalText:
    """`describe_invocation` is what a human reads. A bare hash is unapprovable."""

    def test_a_crawl_run_is_described_as_before(self, tmp_path) -> None:
        tool = _build_tool(tmp_path)
        text = tool.describe_invocation(ScreamingFrogJobInput(seed_url="https://e.com/"))
        assert text.startswith("Launch Screaming Frog CLI (headless) against https://e.com/")
        assert "LIST MODE" not in text

    def test_a_list_run_names_the_crawl_the_count_and_a_sample(self, tmp_path) -> None:
        tool = _build_tool(tmp_path)
        text = tool.describe_invocation(
            ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path))
        )
        assert "12,431 URLs" in text
        assert "Postman full crawl" in text
        assert "https://e.com/a, https://e.com/b, https://e.com/c" in text

    def test_a_list_run_carries_the_fingerprint_alongside_not_instead(self, tmp_path) -> None:
        tool = _build_tool(tmp_path)
        text = tool.describe_invocation(
            ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path))
        )
        assert f"sha256:{'a' * 64}" in text
        # The digest must not be the only identifying content in the string.
        assert text.index("12,431") < text.index("sha256:")

    def test_a_list_run_says_it_does_not_spider_outward(self, tmp_path) -> None:
        """An operator reading "crawl" expects a site crawl. This is not one."""
        tool = _build_tool(tmp_path)
        text = tool.describe_invocation(
            ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path))
        )
        assert "LIST MODE" in text
        assert "does not follow links outward" in text


class TestListModeTruncationDetection:
    """The first check in this codebase that can see a short crawl (ADR 0022)."""

    def test_a_complete_list_run_reports_no_shortfall(self, tmp_path, monkeypatch) -> None:
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(3)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        output = tool.execute(
            ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path, count=3))
        )

        assert output.licence.expected_url_count == 3
        assert output.licence.shortfall == 0

    def test_a_short_run_is_reported_not_raised(self, tmp_path, monkeypatch) -> None:
        """The export is real and worth keeping; the operator decides."""
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(2)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        output = tool.execute(
            ScreamingFrogJobInput(seed_url="https://e.com/", url_list=_url_list(tmp_path, count=10))
        )

        assert output.licence.shortfall == 8

    def test_a_crawl_run_can_never_report_a_shortfall(self, tmp_path, monkeypatch) -> None:
        """Absence is a different claim from "nothing missing"."""
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(2)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        output = tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))

        assert output.licence.expected_url_count is None
        assert output.licence.shortfall is None

    def test_exactly_five_hundred_of_five_hundred_is_not_reported_as_capped(
        self, tmp_path, monkeypatch
    ) -> None:
        """The pre-ADR-0022 false positive, closed by knowing the list length."""
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(500)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        output = tool.execute(
            ScreamingFrogJobInput(
                seed_url="https://e.com/", url_list=_url_list(tmp_path, count=500)
            )
        )

        assert output.licence.free_tier_capped is False
        assert output.licence.shortfall == 0

    def test_five_hundred_of_a_longer_list_still_raises_as_capped(
        self, tmp_path, monkeypatch
    ) -> None:
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(500)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        with pytest.raises(ScreamingFrogLicenceError):
            tool.execute(
                ScreamingFrogJobInput(
                    seed_url="https://e.com/", url_list=_url_list(tmp_path, count=900)
                )
            )

    def test_a_crawl_run_crawling_exactly_five_hundred_still_raises(
        self, tmp_path, monkeypatch
    ) -> None:
        """The accepted false positive on the `--crawl` path is not quietly removed."""
        _install_fake_launch(
            tmp_path, monkeypatch, trace_content=_ACTIVE_LICENCE_LINE + _completed(500)
        )
        tool = _build_tool(tmp_path, guardrails=_allow_all())

        with pytest.raises(ScreamingFrogLicenceError):
            tool.execute(ScreamingFrogJobInput(seed_url="https://e.com/"))


def test_the_public_ip_fixture_is_shared_not_redefined() -> None:
    """Guards the import above: a copied constant is a constant that drifts."""
    assert _PUBLIC_IP == "93.184.216.34"
