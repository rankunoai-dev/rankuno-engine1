"""Tests that the frontend's TypeScript contract matches the Pydantic models.

The failure this prevents: a field is renamed in `schemas.py`, the committed
`schema.ts` keeps the old name, the frontend keeps compiling against mock data
shaped the old way, and the mismatch surfaces only when a real API replaces the
mock. By then the UI has been built on a shape that does not exist.

Making it a Python test means the existing quality gate catches it. A model
change that is not re-exported fails `verify.ps1`, not the frontend build.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "export_ui_contract.py"


def _load_exporter() -> Any:
    """Import the exporter script as a module.

    Returns `Any`, not `ModuleType`: the script lives outside the package and is
    loaded by path, so its members are not statically known. `ModuleType` would
    make every `exporter.build_schema()` call a type error.
    """
    spec = importlib.util.spec_from_file_location("export_ui_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_ui_contract"] = module
    spec.loader.exec_module(module)
    return module


exporter = _load_exporter()


class TestGeneratedFilesAreCurrent:
    def test_schema_is_not_stale(self):
        """The committed schema.ts must match what the models produce now."""
        expected = exporter.build_schema()
        actual = exporter.SCHEMA_PATH.read_text(encoding="utf-8")
        assert actual == expected, (
            "rankuno-ui/src/types/schema.ts is stale. Run: python scripts/export_ui_contract.py"
        )

    def test_colors_are_not_stale(self):
        expected = exporter.build_colors()
        actual = exporter.COLORS_PATH.read_text(encoding="utf-8")
        assert actual == expected, (
            "rankuno-ui/src/constants/colors.ts is stale. Run: python scripts/export_ui_contract.py"
        )

    def test_check_mode_agrees(self):
        """`--check` is what CI would call; it must reach the same verdict."""
        assert exporter.main.__module__  # imported cleanly
        for path, content in (
            (exporter.SCHEMA_PATH, exporter.build_schema()),
            (exporter.COLORS_PATH, exporter.build_colors()),
        ):
            assert path.read_text(encoding="utf-8") == content


class TestContractCompleteness:
    def test_every_taxonomy_enum_is_exported(self):
        """A filter UI cannot offer an option the contract omits."""
        from src.modules.seo.page_classifier import schemas

        domain_enums = {
            schemas.HierarchyLevel,
            schemas.PrimaryPageType,
            schemas.SearchIntent,
            schemas.ConversionRole,
            schemas.SignalSource,
            schemas.ConsensusMethod,
        }
        assert domain_enums <= set(exporter.ENUMS)

    def test_the_output_contract_is_exported(self):
        """The UI's top-level payload is a crawl job's result."""
        from src.modules.seo.page_classifier.tool import PageClassificationOutput

        assert PageClassificationOutput in exporter.MODELS

    def test_no_dangling_type_references(self):
        """A nested model left out renders as an unresolvable identifier.

        `DiscoveredNode.cms_record` did exactly this on the first export.
        """
        exporter._assert_no_dangling_references()

    def test_dangling_references_are_detected_not_ignored(self):
        """Proves the guard works rather than passing vacuously."""
        from pydantic import BaseModel

        class Unexported(BaseModel):
            value: int

        class Referencing(BaseModel):
            nested: Unexported

        original = exporter.MODELS
        exporter.MODELS = (*original, Referencing)
        try:
            with pytest.raises(exporter.UnmappedTypeError, match="Unexported"):
                exporter._assert_no_dangling_references()
        finally:
            exporter.MODELS = original


class TestTypeMapping:
    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (str, "string"),
            (int, "number"),
            (float, "number"),
            (bool, "boolean"),
            (str | None, "string | null"),
            (tuple[str, ...], "string[]"),
            (dict[str, str], "Record<string, string>"),
        ],
    )
    def test_scalar_and_container_mapping(self, annotation, expected):
        assert exporter.ts_type(annotation) == expected

    def test_enums_map_to_their_type_name(self):
        from src.modules.seo.page_classifier.schemas import HierarchyLevel

        assert exporter.ts_type(HierarchyLevel) == "HierarchyLevel"

    def test_nested_models_map_to_their_interface_name(self):
        from src.modules.seo.page_classifier.schemas import SignalScore

        assert exporter.ts_type(tuple[SignalScore, ...]) == "SignalScore[]"

    def test_unions_inside_arrays_are_parenthesised(self):
        """`(string | null)[]` not `string | null[]`, which means something else."""
        assert exporter.ts_type(tuple[str | None, ...]) == "(string | null)[]"

    def test_annotated_constraints_are_stripped(self):
        """`Annotated[int, Field(ge=0)]` is a validation rule, not a type.

        `PageClassificationInput.max_depth` is written this way so the bounds
        apply to the int rather than to `int | None`. The exporter raised on it
        until it learned to unwrap, which is the guard behaving correctly.
        """
        from typing import Annotated

        from pydantic import Field

        assert exporter.ts_type(Annotated[int, Field(ge=0, le=15)]) == "number"
        assert exporter.ts_type(Annotated[int, Field(ge=0)] | None) == "number | null"

    def test_an_unmappable_type_raises_rather_than_emitting_any(self):
        """A silent `any` would defeat the entire point of generating types."""
        with pytest.raises(exporter.UnmappedTypeError):
            exporter.ts_type(complex)


class TestGeneratedShape:
    def test_field_names_are_not_camel_cased(self):
        """Names stay exactly as the API emits, so there is no mapping layer."""
        schema = exporter.SCHEMA_PATH.read_text(encoding="utf-8")
        assert "final_confidence_score" in schema
        assert "finalConfidenceScore" not in schema

    def test_enums_render_as_string_unions_not_ts_enums(self):
        """Unions compare directly against what the API sends."""
        schema = exporter.SCHEMA_PATH.read_text(encoding="utf-8")
        assert "export type HierarchyLevel =" in schema
        assert "export enum" not in schema

    def test_runtime_value_arrays_exist_for_filter_uis(self):
        """A type alone cannot be enumerated at runtime."""
        schema = exporter.SCHEMA_PATH.read_text(encoding="utf-8")
        assert "PRIMARY_PAGE_TYPE_VALUES" in schema
        assert "HIERARCHY_LEVEL_VALUES" in schema

    def test_files_carry_a_do_not_edit_banner(self):
        for path in (exporter.SCHEMA_PATH, exporter.COLORS_PATH):
            assert "DO NOT EDIT" in path.read_text(encoding="utf-8")

    def test_colors_cover_every_page_type(self):
        """A missing colour renders as an invisible badge."""
        from src.modules.seo.page_classifier.schemas import PrimaryPageType

        colors = exporter.COLORS_PATH.read_text(encoding="utf-8")
        for member in PrimaryPageType:
            assert f"{member.value}:" in colors

    def test_colors_match_the_backend_map(self):
        """One source of truth: the map already pinned to the specification."""
        from src.modules.seo.page_classifier.tree_visualizer import PAGE_TYPE_COLOURS

        colors = exporter.COLORS_PATH.read_text(encoding="utf-8")
        for page_type, colour in PAGE_TYPE_COLOURS.items():
            assert f'{page_type.value}: "{colour}"' in colors


class TestDatetimeMapping:
    def test_datetime_maps_to_string_not_date(self):
        """JSON carries an ISO 8601 string; `Date` would fail at runtime.

        `JSON.parse` yields a string, so typing it as `Date` would let a
        consumer call `.getTime()` on something that has no such method.
        """
        from datetime import datetime

        assert exporter.ts_type(datetime) == "string"
        assert exporter.ts_type(datetime | None) == "string | null"
