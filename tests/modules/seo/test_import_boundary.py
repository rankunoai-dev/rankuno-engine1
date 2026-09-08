"""The ADR 0011 seam, enforced by parsing imports (plan P0-6).

`page_classifier` and `deliverables` both import `contracts`; neither imports
the other, and `contracts` imports neither. Checked with `ast` over every
module in the three packages so a new file cannot slip through, and the
detector is self-tested against a violating source so a green run cannot mean
"nothing was scanned". The one-direction check that used to live in
`test_screaming_frog_adapter.py` moved here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SEO = Path(__file__).resolve().parents[3] / "src" / "modules" / "seo"
PAGE_CLASSIFIER = "src.modules.seo.page_classifier"
DELIVERABLES = "src.modules.seo.deliverables"
CONTRACTS = "src.modules.seo.contracts"


def imports_in(source: str, *, package: str = "") -> set[str]:
    """Every module name a source file imports, relative imports resolved."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package.rsplit(".", node.level - 1)[0] if node.level else ""
            names.add(".".join(part for part in (base, node.module or "") if part))
    return names


def modules_of(package: str) -> list[Path]:
    files = sorted((SEO / package).rglob("*.py"))
    assert files, f"no modules found under {package}"
    return files


def violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in modules_of(package):
        names = imports_in(path.read_text(encoding="utf-8"), package=f"src.modules.seo.{package}")
        for name in sorted(names):
            if any(name == bad or name.startswith(bad + ".") for bad in forbidden):
                found.append(f"{path.name} imports {name}")
    return found


def test_every_package_has_the_modules_this_test_exists_for():
    packages = ("page_classifier", "deliverables", "contracts")
    names = {p.name for pkg in packages for p in modules_of(pkg)}
    assert {"audit_export.py", "screaming_frog_adapter.py", "_bundle.py", "audit.py"} <= names


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("page_classifier", (DELIVERABLES,)),
        ("deliverables", (PAGE_CLASSIFIER,)),
        ("contracts", (PAGE_CLASSIFIER, DELIVERABLES)),
    ],
)
def test_no_import_crosses_the_seam(package: str, forbidden: tuple[str, ...]):
    assert violations(package, forbidden) == []


def test_the_seam_packages_import_contracts():
    """Both sides really are joined by the contract, not merely kept apart."""
    for package in ("page_classifier", "deliverables"):
        joined = {
            name
            for path in modules_of(package)
            for name in imports_in(path.read_text(encoding="utf-8"))
            if name.startswith(CONTRACTS)
        }
        assert joined, f"{package} never imports contracts"


@pytest.mark.parametrize(
    "source",
    [
        "import src.modules.seo.deliverables\n",
        "from src.modules.seo.deliverables import load_screaming_frog_bundle\n",
        "from src.modules.seo.deliverables.screaming_frog_adapter import SPINE_FILE\n",
        "from ..deliverables import x\n",
    ],
)
def test_detector_catches_a_violation(source: str):
    names = imports_in(source, package=PAGE_CLASSIFIER)
    assert any(name == DELIVERABLES or name.startswith(DELIVERABLES + ".") for name in names)
