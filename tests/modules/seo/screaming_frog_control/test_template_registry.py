"""Tests for `TemplateRegistry` — name-to-path resolution, nothing else.

Never authors a real `.seospiderconfig`: the format is a Java
`ObjectInputStream`-serialised file this engine cannot produce (ADR 0013).
Fixture files here are placeholder bytes, sufficient to prove path resolution
and existence checking, which is all this class does.
"""

from __future__ import annotations

import pytest
from src.core.worker_templates import MAX_TEMPLATE_DESCRIPTION_CHARS
from src.modules.seo.screaming_frog_control.template_registry import (
    TemplateNotFoundError,
    TemplateRegistry,
)


@pytest.fixture
def template_dir(tmp_path):
    directory = tmp_path / "templates"
    directory.mkdir()
    (directory / "acme-standard.seospiderconfig").write_bytes(b"placeholder-not-real-sf-bytes")
    (directory / "beta-deep-crawl.seospiderconfig").write_bytes(b"placeholder-not-real-sf-bytes")
    (directory / "readme.txt").write_text("not a template")
    return directory


class TestListTemplates:
    def test_lists_only_seospiderconfig_files_sorted_by_name(self, template_dir) -> None:
        registry = TemplateRegistry(template_dir)
        names = [t.name for t in registry.list_templates()]
        assert names == ["acme-standard", "beta-deep-crawl"]

    def test_missing_directory_returns_empty_not_an_error(self, tmp_path) -> None:
        registry = TemplateRegistry(tmp_path / "does-not-exist")
        assert registry.list_templates() == ()

    def test_empty_directory_returns_empty(self, tmp_path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        registry = TemplateRegistry(empty)
        assert registry.list_templates() == ()


class TestDescriptions:
    """A `.seospiderconfig` is unreadable, so a sidecar note is all there is."""

    def test_a_sidecar_note_becomes_the_description(self, template_dir) -> None:
        (template_dir / "acme-standard.md").write_text(
            "Extracts SKU, price and stock status.", encoding="utf-8"
        )
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["acme-standard"] == "Extracts SKU, price and stock status."

    def test_a_template_without_a_sidecar_gets_an_empty_description(self, template_dir) -> None:
        """The sidecar is optional, and its absence is not an error anywhere."""
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["beta-deep-crawl"] == ""

    def test_a_multi_line_note_is_flattened_to_one_line(self, template_dir) -> None:
        (template_dir / "acme-standard.md").write_text(
            "# Acme\n\nExtracts   SKU.\n", encoding="utf-8"
        )
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["acme-standard"] == "# Acme Extracts SKU."

    def test_a_note_exactly_at_the_cap_survives_whole(self, template_dir) -> None:
        (template_dir / "acme-standard.md").write_text(
            "x" * MAX_TEMPLATE_DESCRIPTION_CHARS, encoding="utf-8"
        )
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["acme-standard"] == "x" * MAX_TEMPLATE_DESCRIPTION_CHARS

    def test_a_note_over_the_cap_is_truncated_not_dropped(self, template_dir) -> None:
        """Truncated, because a too-long note is still worth more than none."""
        (template_dir / "acme-standard.md").write_text(
            "y" * (MAX_TEMPLATE_DESCRIPTION_CHARS + 50), encoding="utf-8"
        )
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["acme-standard"] == "y" * MAX_TEMPLATE_DESCRIPTION_CHARS

    def test_a_note_carrying_a_bidi_override_is_stripped_of_it(self, template_dir) -> None:
        """Left in, the rest of the line renders reversed in a browser."""
        (template_dir / "acme-standard.md").write_text("safe‮gnp.exe", encoding="utf-8")
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name["acme-standard"] == "safegnp.exe"

    def test_an_unreadable_sidecar_costs_only_its_own_description(self, template_dir) -> None:
        """A directory where a file should be is the cheap way to make a read fail."""
        (template_dir / "acme-standard.md").mkdir()
        registry = TemplateRegistry(template_dir)
        by_name = {t.name: t.description for t in registry.list_templates()}
        assert by_name == {"acme-standard": "", "beta-deep-crawl": ""}


class TestUnrecognisedFiles:
    """The silence this cycle exists to remove."""

    def test_a_config_whose_name_is_not_a_slug_is_reported_not_dropped(self, template_dir) -> None:
        # Exactly how Screaming Frog's own File > Configuration > Save As
        # names a config: spaces, capitals, and a hyphen with spaces round it.
        (template_dir / "SEO Spider Config - Basic.seospiderconfig").write_bytes(b"x")
        scan = TemplateRegistry(template_dir).scan()
        assert [t.name for t in scan.templates] == ["acme-standard", "beta-deep-crawl"]
        assert scan.unrecognised == ("SEO Spider Config - Basic.seospiderconfig",)

    def test_nothing_unrecognised_is_an_empty_tuple_not_a_null(self, template_dir) -> None:
        assert TemplateRegistry(template_dir).scan().unrecognised == ()

    def test_list_templates_still_returns_only_the_usable_ones(self, template_dir) -> None:
        """The narrower call is unchanged for every existing caller."""
        (template_dir / "Manulife JS.seospiderconfig").write_bytes(b"x")
        registry = TemplateRegistry(template_dir)
        assert [t.name for t in registry.list_templates()] == [
            "acme-standard",
            "beta-deep-crawl",
        ]

    def test_a_missing_directory_scans_to_nothing_at_all(self, tmp_path) -> None:
        scan = TemplateRegistry(tmp_path / "does-not-exist").scan()
        assert (scan.templates, scan.unrecognised) == ((), ())


class TestResolve:
    def test_resolves_a_known_template_to_its_path(self, template_dir) -> None:
        registry = TemplateRegistry(template_dir)
        resolved = registry.resolve("acme-standard")
        assert resolved == (template_dir / "acme-standard.seospiderconfig").resolve()

    def test_unknown_name_raises(self, template_dir) -> None:
        registry = TemplateRegistry(template_dir)
        with pytest.raises(TemplateNotFoundError, match="unknown"):
            registry.resolve("does-not-exist")

    def test_invalid_name_shape_is_refused_before_touching_disk(self, template_dir) -> None:
        # `TEMPLATE_NAME_PATTERN` bans `/` and `\`, so a name shaped like a
        # path-traversal attempt is what actually protects `resolve()` — the
        # `relative_to` escape check after it is defense in depth for a
        # scenario the regex already makes unreachable in practice.
        registry = TemplateRegistry(template_dir)
        with pytest.raises(TemplateNotFoundError, match="invalid"):
            registry.resolve("../../etc/passwd")
