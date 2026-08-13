"""Architecture & Documentation Drift Detector — SDLC Step 8 quality gate.

Checks three things that documentation drift actually looks like in this repo:

1. **Broken relative links.** A documented path that resolves to nothing is a
   documentation bug of the same severity as a broken import. This is the check
   the previous version lacked, and it is the one that would have caught eleven
   dead links across README.md and docs/ARCHITECTURE.md.
2. **Undocumented domain modules.** A new `src/modules/<name>` must appear in
   README.md or docs/ARCHITECTURE.md.
3. **Empty skill directories.** A `skills/<name>/` with no SKILL.md is a
   capability that looks real in a directory listing but is not.

Matching is deliberately path-based rather than substring-based: the previous
implementation reported "seo is documented" because the string `seo` appeared
inside an unrelated link, which is the kind of false pass that makes a gate
worse than no gate.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
SKILLS_DIR = REPO_ROOT / "skills"
README_PATH = REPO_ROOT / "README.md"
ARCH_PATH = REPO_ROOT / "docs" / "ARCHITECTURE.md"

# Markdown inline links: [text](target). Excludes images and reference links.
_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")

# Link targets that are not repository paths.
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _iter_markdown_files() -> list[Path]:
    """Every **tracked** markdown file.

    Asks git rather than walking the filesystem, which is what the audit has
    always claimed to do. Walking picked up `project-standards/` — a stale copy
    of this repo that `.gitignore` excludes precisely because it is stale (see
    CLAUDE.md §7, ruling 8) — and failed the gate on broken links in documents
    nobody maintains and nothing ships.

    The filesystem walk survives as a fallback for a source tree that is not a
    git checkout, where the skip list is the best available approximation.
    """
    try:
        listed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["git", "ls-files", "-z", "*.md"],  # noqa: S607 - git resolved from PATH
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        skip = {".venv", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".git"}
        return sorted(
            path for path in REPO_ROOT.rglob("*.md") if not any(part in skip for part in path.parts)
        )

    return sorted(REPO_ROOT / name for name in listed.split("\0") if name)


def check_links() -> list[str]:
    """Report every relative markdown link that does not resolve to a real path."""
    issues: list[str] = []

    for md_file in _iter_markdown_files():
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"{md_file.relative_to(REPO_ROOT)}: unreadable ({exc})")
            continue

        for target in _LINK_RE.findall(content):
            link = target.split(" ")[0].strip()
            if not link or link.startswith(_EXTERNAL_PREFIXES):
                continue

            # Strip an anchor fragment; we verify the file, not the heading.
            path_part = link.split("#", 1)[0]
            if not path_part:
                continue

            resolved = (md_file.parent / path_part).resolve()
            if not resolved.exists():
                rel = md_file.relative_to(REPO_ROOT)
                issues.append(f"{rel}: broken link -> {link}")

    return issues


def check_modules_documented() -> list[str]:
    """Report domain modules absent from README.md and docs/ARCHITECTURE.md."""
    issues: list[str] = []
    modules_dir = SRC_DIR / "modules"
    if not modules_dir.exists():
        return issues

    readme = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
    arch = ARCH_PATH.read_text(encoding="utf-8") if ARCH_PATH.exists() else ""
    combined = readme + arch

    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or item.name.startswith(("_", ".")):
            continue
        # Require the module's path, not just its bare name. 'seo' matching the
        # string inside 'seo-engine-guide' is exactly the false pass to avoid.
        needle = f"modules/{item.name}"
        if needle not in combined and f"{item.name}/" not in combined:
            issues.append(
                f"Module 'src/modules/{item.name}' is not documented in "
                f"README.md or docs/ARCHITECTURE.md"
            )
    return issues


def check_skills_populated() -> list[str]:
    """Report skill directories that contain no SKILL.md."""
    issues: list[str] = []
    if not SKILLS_DIR.exists():
        return issues

    for item in sorted(SKILLS_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        if not (item / "SKILL.md").exists():
            issues.append(f"Skill 'skills/{item.name}/' has no SKILL.md (empty capability)")
    return issues


def check_required_docs() -> list[str]:
    """Report missing top-level documentation."""
    issues: list[str] = []
    for path, label in ((README_PATH, "README.md"), (ARCH_PATH, "docs/ARCHITECTURE.md")):
        if not path.exists():
            issues.append(f"{label} is missing!")
    return issues


def check_drift() -> int:
    """Run every drift check and report. Returns a process exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("Running Architecture & Documentation Drift Audit...")

    issues = check_required_docs()
    issues += check_links()
    issues += check_modules_documented()
    issues += check_skills_populated()

    print("\n--- Drift Audit Results ---")
    if issues:
        print(f"FAILED: {len(issues)} documentation drift issue(s) detected:\n")
        for issue in issues:
            print(f"  - {issue}")
        print("\nUpdate the documentation to reflect the verified state of the code.")
        return 1

    checked = len(_iter_markdown_files())
    print(f"PASSED: no drift detected across {checked} markdown files.")
    print("  - all relative links resolve")
    print("  - all domain modules documented")
    print("  - all skill directories populated")
    return 0


if __name__ == "__main__":
    sys.exit(check_drift())
