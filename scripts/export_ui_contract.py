"""Generate the frontend's TypeScript contract from the Pydantic models.

The UI and the engine must agree on shapes. Hand-written TypeScript is how that
agreement quietly breaks: a field is renamed in `schemas.py`, the frontend keeps
compiling against the old name, and the mismatch surfaces only when real data
replaces mock data. Generating the types removes the possibility.

Two outputs, both committed:

* `rankuno-ui/src/types/schema.ts` — interfaces and string-literal unions.
* `rankuno-ui/src/constants/colors.ts` — badge colours from the single
  `PAGE_TYPE_COLOURS` map, which is already pinned to the specification by test.

`tests/test_ui_contract.py` regenerates both and fails if the committed files
differ, so a model change that is not re-exported breaks the Python gate rather
than the frontend build.

Field names are **not** camel-cased. They stay exactly as the API emits them, so
there is no transformation layer to get wrong and no ambiguity about which name
is authoritative.

Usage:
    python scripts/export_ui_contract.py            # write the files
    python scripts/export_ui_contract.py --check    # exit 1 if they are stale
"""

from __future__ import annotations

import argparse
import json
import sys
import types
import typing
from datetime import datetime
from enum import EnumMeta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pydantic import BaseModel  # noqa: E402
from src.core.state_store import JobTelemetry  # noqa: E402
from src.modules.seo.page_classifier.discovery import (  # noqa: E402
    DiscoveredNode,
    DiscoveryReport,
    DiscoverySource,
)
from src.modules.seo.page_classifier.logical_hierarchy import (  # noqa: E402
    NavCoverageReport,
)
from src.modules.seo.page_classifier.nav_tree_parser import (  # noqa: E402
    NavigationTree,
    NavNode,
    NavSource,
)
from src.modules.seo.page_classifier.schemas import (  # noqa: E402
    ConsensusMethod,
    ConversionRole,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.signal_parsers import CmsRecord  # noqa: E402
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    CrawlSummary,
    PageClassificationInput,
    PageClassificationOutput,
)
from src.modules.seo.page_classifier.tree_visualizer import PAGE_TYPE_COLOURS  # noqa: E402
from src.modules.seo.page_classifier.weights import (  # noqa: E402
    CmsFamily,
    SiteProfile,
    WeightProfileReport,
)

# Written inside this repository. An absolute path elsewhere would mean the
# committed contract and the generator's output could silently diverge.
SCHEMA_PATH = REPO_ROOT / "rankuno-ui" / "src" / "types" / "schema.ts"
COLORS_PATH = REPO_ROOT / "rankuno-ui" / "src" / "constants" / "colors.ts"

# Order matters only for readability: a type appears before its users so the file
# reads top-down. TypeScript itself does not require it.
ENUMS: tuple[EnumMeta, ...] = (
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    ConversionRole,
    SignalSource,
    ConsensusMethod,
    CmsFamily,
)

MODELS: tuple[type[BaseModel], ...] = (
    SignalScore,
    FullPageIntelligenceProfile,
    CmsRecord,
    DiscoverySource,
    DiscoveredNode,
    DiscoveryReport,
    SiteProfile,
    WeightProfileReport,
    NavSource,
    NavNode,
    NavigationTree,
    NavCoverageReport,
    JobTelemetry,
    CrawlSummary,
    PageClassificationInput,
    PageClassificationOutput,
)

_TS_BUILTINS = frozenset({"string", "number", "boolean", "null", "unknown", "Record", "readonly"})

_SCALARS: dict[type, str] = {
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
    # Pydantic serialises a datetime to an ISO 8601 string in JSON mode, which is
    # what reaches the browser. Mapping it to `Date` would be a lie: `JSON.parse`
    # produces a string, and TypeScript would let a consumer call `.getTime()` on
    # it and fail at runtime.
    datetime: "string",
}

BANNER = (
    "// GENERATED FILE - DO NOT EDIT.\n"
    "//\n"
    "// Produced by scripts/export_ui_contract.py from the Pydantic models in\n"
    "// src/modules/seo/page_classifier/. Edit those and re-run the exporter.\n"
    "//\n"
    "// tests/test_ui_contract.py fails if this file is stale, so a model change\n"
    "// that is not re-exported breaks the Python quality gate.\n"
)


class UnmappedTypeError(TypeError):
    """A field type has no TypeScript equivalent.

    Raised rather than emitting `any`. A silent `any` would defeat the entire
    purpose of generating the contract, and would do so invisibly.
    """


def ts_type(annotation: object) -> str:
    """Render a Python annotation as a TypeScript type.

    Args:
        annotation: A resolved type annotation from `model_fields`.

    Returns:
        The TypeScript type.

    Raises:
        UnmappedTypeError: If the annotation has no known equivalent.
    """
    if annotation is None or annotation is type(None):
        return "null"

    if isinstance(annotation, type):
        if isinstance(annotation, EnumMeta):
            return annotation.__name__
        if annotation in _SCALARS:
            return _SCALARS[annotation]
        if issubclass(annotation, BaseModel):
            return annotation.__name__

    # `Annotated[int, Field(ge=0, le=15)]`, as used for a constrained member of a
    # union. The metadata is a validation constraint, which TypeScript cannot
    # express, so only the underlying type carries over. `__metadata__` is the
    # documented marker for an `Annotated` alias; checking it must come before
    # `get_origin`, which unwraps to the underlying type and loses the
    # distinction.
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        return ts_type(typing.get_args(annotation)[0])

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # `X | None` and `X | Y` both arrive here.
    if origin in (types.UnionType, typing.Union):
        return " | ".join(dict.fromkeys(ts_type(arg) for arg in args))

    if origin in (list, tuple, set, frozenset):
        # `tuple[X, ...]` and `tuple[X, Y]` are both arrays to TypeScript; the
        # models only use the homogeneous form.
        members = [arg for arg in args if arg is not Ellipsis]
        if not members:
            return "unknown[]"
        inner = ts_type(members[0])
        return f"({inner})[]" if "|" in inner else f"{inner}[]"

    if origin is dict:
        key, value = (ts_type(arg) for arg in args)
        return f"Record<{key}, {value}>"

    # `Literal["menu", "breadcrumb", "none"]` renders as the string-literal union
    # TypeScript already uses for the `StrEnum`s, so both kinds of closed set
    # reach the UI in the same shape. Inlined rather than emitted as a named
    # alias: the reference check walks identifiers in the rendered type and
    # would treat a name with no declaration as dangling, which is the guard
    # working correctly.
    if origin is typing.Literal:
        return " | ".join(dict.fromkeys(json.dumps(arg) for arg in args))

    msg = f"No TypeScript mapping for {annotation!r}"
    raise UnmappedTypeError(msg)


def render_enum(enum_cls: EnumMeta) -> str:
    """Render an enum as a string-literal union plus a values array.

    A union rather than a TypeScript `enum`: unions compare directly against the
    strings the API sends, need no import at the call site, and cannot drift from
    the wire format. The `*_VALUES` array exists because filter UIs need to
    enumerate the options at runtime, which a type alone cannot do.
    """
    members = [member.value for member in enum_cls]
    union = "\n  | ".join(f'"{value}"' for value in members)
    values = ", ".join(f'"{value}"' for value in members)
    name = enum_cls.__name__
    const = _screaming_snake(name)
    return (
        f"export type {name} =\n  | {union};\n\n"
        f"export const {const}_VALUES: readonly {name}[] = [{values}] as const;\n"
    )


def render_model(model: type[BaseModel]) -> str:
    """Render a Pydantic model as a TypeScript interface.

    Optional-with-default fields stay required in TypeScript: the API always
    emits them, because Pydantic serialises defaults. Marking them `?` would
    make consumers write needless null checks for values that are always there.
    """
    doc = (model.__doc__ or "").strip().split("\n")[0]
    lines = [f"/** {doc} */" if doc else "", f"export interface {model.__name__} {{"]

    for name, field in model.model_fields.items():
        rendered = ts_type(field.annotation)
        description = (field.description or "").strip().split("\n")[0]
        if description:
            lines.append(f"  /** {description} */")
        lines.append(f"  {name}: {rendered};")

    lines.append("}")
    return "\n".join(line for line in lines if line != "") + "\n"


def _screaming_snake(name: str) -> str:
    """Convert `PrimaryPageType` to `PRIMARY_PAGE_TYPE`."""
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(char.upper())
    return "".join(out)


def _identifiers(rendered: str) -> set[str]:
    """Extract bare type names from a rendered TypeScript type."""
    cleaned = rendered.replace("[]", " ").replace("(", " ").replace(")", " ")
    for symbol in ("|", "<", ">", ","):
        cleaned = cleaned.replace(symbol, " ")
    return {token for token in cleaned.split() if token and token[0].isalpha() and '"' not in token}


def _assert_no_dangling_references() -> None:
    """Fail if any field references a type the exporter does not emit.

    A nested model left out of `MODELS` renders as a bare identifier and the
    frontend fails to compile with an unresolved-name error far from the cause.
    `DiscoveredNode.cms_record` did exactly that on the first run. Catching it
    here reports the missing model by name instead.

    Raises:
        UnmappedTypeError: Naming the referenced type and the field that used it.
    """
    emitted = {cls.__name__ for cls in ENUMS} | {cls.__name__ for cls in MODELS}

    for model in MODELS:
        for field_name, field in model.model_fields.items():
            for token in _identifiers(ts_type(field.annotation)):
                if token not in emitted and token not in _TS_BUILTINS:
                    msg = (
                        f"{model.__name__}.{field_name} references '{token}', "
                        f"which the exporter does not emit. Add it to MODELS or ENUMS."
                    )
                    raise UnmappedTypeError(msg)


def build_schema() -> str:
    """Assemble the full `schema.ts` source."""
    _assert_no_dangling_references()
    blocks = [
        BANNER,
        "",
        "// ---------------------------------------------------------------- enums",
        "",
    ]
    blocks.extend(render_enum(enum_cls) for enum_cls in ENUMS)
    blocks.append("// ----------------------------------------------------------- data contracts")
    blocks.append("")
    blocks.extend(render_model(model) for model in MODELS)
    return "\n".join(blocks).replace("\n\n\n", "\n\n").rstrip() + "\n"


def build_colors() -> str:
    """Assemble `colors.ts` from the visualizer's colour map.

    Sourced from `tree_visualizer.PAGE_TYPE_COLOURS`, which is already pinned to
    `TREE_VISUALIZER_SPECIFICATION.md` by test. Re-declaring the palette in the
    frontend would create a second source of truth for values a specification
    already fixes.
    """
    entries = "\n".join(
        f'  {page_type.value}: "{colour}",'
        for page_type, colour in sorted(PAGE_TYPE_COLOURS.items(), key=lambda item: item[0].value)
    )
    return (
        f"{BANNER}\n"
        'import type { PrimaryPageType } from "../types/schema";\n\n'
        "/** Badge colour per page type, from TREE_VISUALIZER_SPECIFICATION.md. */\n"
        "export const PAGE_TYPE_COLORS: Record<PrimaryPageType, string> = {\n"
        f"{entries}\n"
        "};\n\n"
        "/** Swimlane accent per hierarchy level. */\n"
        "export const LEVEL_COLORS = {\n"
        '  L0_HOMEPAGE: "#f5c518",\n'
        '  L1_PRIMARY_NAV_HUB: "#7f00ff",\n'
        '  L2_SUB_NAV_HUB: "#00f2fe",\n'
        '  L3_LEAF_PAGE: "#10b981",\n'
        '  UTILITY_PAGE: "#64748b",\n'
        "} as const;\n\n"
        "/** Short badge label per hierarchy level. */\n"
        "export const LEVEL_LABELS = {\n"
        '  L0_HOMEPAGE: "L0",\n'
        '  L1_PRIMARY_NAV_HUB: "L1",\n'
        '  L2_SUB_NAV_HUB: "L2",\n'
        '  L3_LEAF_PAGE: "L3",\n'
        '  UTILITY_PAGE: "UTIL",\n'
        "} as const;\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="export_ui_contract",
        description="Generate the frontend TypeScript contract from the Pydantic models.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the committed files are stale.",
    )
    args = parser.parse_args()

    outputs = ((SCHEMA_PATH, build_schema()), (COLORS_PATH, build_colors()))

    if args.check:
        stale = [
            path
            for path, content in outputs
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            for path in stale:
                print(f"STALE: {path.relative_to(REPO_ROOT)}")
            print("\nRun: python scripts/export_ui_contract.py")
            return 1
        print("UI contract is up to date.")
        return 0

    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({len(content.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
