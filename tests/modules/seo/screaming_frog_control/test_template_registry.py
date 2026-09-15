"""Tests for `TemplateRegistry` — name-to-path resolution, nothing else.

Never authors a real `.seospiderconfig`: the format is a Java
`ObjectInputStream`-serialised file this engine cannot produce (ADR 0013).
Fixture files here are placeholder bytes, sufficient to prove path resolution
and existence checking, which is all this class does.
"""

from __future__ import annotations

import pytest
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
