"""Keep only the newest tutor lessons in ``docs/learning/``.

The tutor agent writes one lesson per finished change. Lessons are private
learning notes, not project history: ``docs/learning/`` is gitignored, and the
folder is capped so it never grows into a second, unmaintained build log.

Deletion is done here, by a script, rather than by an instruction to the agent,
because "remember to delete the old ones" is exactly the kind of step an agent
skips. A script either runs or fails loudly.

Only files named ``YYYYMMDD-HHMMSS-<slug>.md`` are ever considered. The
timestamp prefix is what makes "newest" a sort rather than a guess at file
modification times, and the strict pattern means anything else that ends up in
the folder (a tour-progress file, a note the user wrote by hand) is never
touched.

Usage::

    python scripts/prune_lessons.py            # keep the newest 5
    python scripts/prune_lessons.py --keep 3
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LESSONS_DIR = REPO_ROOT / "docs" / "learning"
DEFAULT_KEEP = 5
LESSON_NAME = re.compile(r"^\d{8}-\d{6}-[a-z0-9][a-z0-9-]*\.md$")


def lesson_files(directory: Path) -> list[Path]:
    """Every lesson in ``directory``, oldest first.

    Args:
        directory: The lessons folder. A missing folder has no lessons.

    Returns:
        Lesson files sorted by name, which is chronological by construction.
    """
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and LESSON_NAME.match(p.name))


def prune(directory: Path = LESSONS_DIR, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Delete all but the newest ``keep`` lessons.

    Args:
        directory: The lessons folder.
        keep: How many of the newest lessons survive. Must be at least 1, so a
            lesson that was just written can never be deleted by its own prune.

    Returns:
        The files that were deleted, oldest first.

    Raises:
        ValueError: If ``keep`` is less than 1.
    """
    if keep < 1:
        raise ValueError(f"keep must be at least 1, got {keep}")
    lessons = lesson_files(directory)
    doomed = lessons[: max(0, len(lessons) - keep)]
    for path in doomed:
        path.unlink()
    return doomed


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument("--dir", type=Path, default=LESSONS_DIR)
    args = parser.parse_args(argv)
    deleted = prune(args.dir, args.keep)
    remaining = len(lesson_files(args.dir))
    for path in deleted:
        print(f"deleted {path.name}")
    print(f"{remaining} lesson(s) kept in {args.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
