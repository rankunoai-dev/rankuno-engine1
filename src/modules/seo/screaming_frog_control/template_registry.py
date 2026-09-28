"""Reads pre-authored `.seospiderconfig` files by name. Never writes one.

ADR 0013 condition 5's field mapping: crawl-form fields do not map onto
Screaming Frog CLI flags (verified: none of max_pages, max_depth,
respect_robots, user_agent, JS rendering, speed or exclude has a CLI
counterpart), so the mapping is `template name -> config file path` instead,
resolved here. `.seospiderconfig` is a Java `ObjectInputStream`-serialised
file (confirmed against a real crash log's "invalid stream header" error);
this module cannot author one, validate its contents, or fabricate a
placeholder that Screaming Frog would accept. Populating the template
directory is an operator action performed once inside the real Screaming
Frog GUI (File > Configuration > Save As) — not something a later cycle can
automate without a governance exception of its own.

Two consequences of that opacity are handled here.

**Descriptions come from a sidecar file, `<name>.md`, never from inside the
config.** Since the binary cannot be read back, the only description of a
template that can exist is one a human wrote down. A per-template Markdown
file was chosen over a single `descriptions.json` for the directory because
the failure modes are not comparable: one unparseable JSON file blanks every
description at once, and an operator editing it by hand has to get commas
and escaping right, whereas a missing, empty or unreadable `.md` costs
exactly the one template it belongs to. It also keeps a template atomic —
adding one is two files copied into a folder, with nothing else to remember
to edit — and the sidecar path is derived from a stem that already passed
`TEMPLATE_NAME_PATTERN`, so it opens no path surface the config itself did
not already open. The file is read as plain text; nothing renders it as
Markdown. The extension only tells the human writing it that prose goes
there.

**Files whose names are not slugs are reported, not silently dropped.**
`TEMPLATE_NAME_PATTERN` guards a path component and is not negotiable, but a
config saved from the Screaming Frog GUI is called
`SEO Spider Config - Basic.seospiderconfig` by default — spaces, capitals —
so the common case was for a full template directory to produce an empty
dropdown with no reason given anywhere. `scan()` returns those names
alongside the recognised templates and logs them, so the answer ("rename
them to lower-case slugs") is reachable from the machine that holds them.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.worker_templates import MAX_TEMPLATE_DESCRIPTION_CHARS, normalise_description
from src.modules.seo.screaming_frog_control.schemas import ScreamingFrogTemplate

__all__ = [
    "TEMPLATE_NAME_PATTERN",
    "TemplateNotFoundError",
    "TemplateRegistry",
    "TemplateScan",
]

_logger = get_logger(__name__)

_SUFFIX = ".seospiderconfig"

_DESCRIPTION_SUFFIX = ".md"
"""Sidecar extension. See the module docstring for why this is one file per
template rather than one JSON file per directory."""

_MAX_SIDECAR_BYTES = 16 * 1024
"""Bound on how much of a sidecar is read before it is normalised.

A description is a sentence or two; 16 KiB is generous for that and small
enough that a sidecar someone pointed at a 2 GB file cannot be pulled into
memory. Whatever survives is truncated to `MAX_TEMPLATE_DESCRIPTION_CHARS`
anyway — this cap bounds the read, not the result."""

_MAX_LOGGED_NAME_CHARS = 128
"""Clamp on an unrecognised filename before it reaches a log line."""

TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$")
"""Also blocks path-traversal names (`../../secrets`): a name that does not
match this can never become a `Path` component escaping the template dir."""


class TemplateNotFoundError(RankunoError):
    """No `.seospiderconfig` exists under this name in the template directory."""


class TemplateScan(StrictModel):
    """One reading of the template directory, including what it could not use.

    Attributes:
        templates: Every config whose filename is a usable slug, sorted by
            name, each carrying its sidecar description (`""` when no
            sidecar exists).
        unrecognised: The filenames of every other `.seospiderconfig` in the
            directory — the ones `TEMPLATE_NAME_PATTERN` refuses. Carried so
            the operator can be told they exist; only the *count* of these
            ever leaves the machine, because a filename here is arbitrary
            text this engine did not choose, and the machine holding the
            folder is the only place the names can be acted on anyway.
    """

    templates: tuple[ScreamingFrogTemplate, ...] = ()
    unrecognised: tuple[str, ...] = ()


class TemplateRegistry:
    """Operator-facing catalogue of pre-authored Screaming Frog configs.

    Deliberately does not open, parse, or validate the *contents* of a
    `.seospiderconfig` — see the module docstring for why it cannot. This
    class only maps an operator-chosen name to a path on disk and confirms
    the file exists before handing that path to `--config`.
    """

    def __init__(self, template_dir: Path) -> None:
        """Build a registry rooted at `template_dir`.

        Args:
            template_dir: Directory of `*.seospiderconfig` files. Absent or
                empty is a valid state, not an error (see `list_templates`).
        """
        self._dir = template_dir

    def list_templates(self) -> tuple[ScreamingFrogTemplate, ...]:
        """Every usable `.seospiderconfig` in the template directory, name-sorted.

        Returns an empty tuple, not an error, when the directory is absent or
        holds nothing — that is the true out-of-the-box state until an
        operator saves a real config into it from the Screaming Frog GUI. A
        caller that needs to *explain* an empty list wants `scan()`, which
        also reports the files this one had to leave out.
        """
        return self.scan().templates

    def scan(self) -> TemplateScan:
        """Read the template directory: descriptions and skipped files alike.

        Returns:
            A `TemplateScan`. `templates` is name-sorted and carries each
            sidecar description; `unrecognised` holds every other
            `.seospiderconfig` in the same directory, so a caller can say why
            the list is shorter than the folder.
        """
        if not self._dir.is_dir():
            return TemplateScan()

        recognised: list[str] = []
        rejected: list[str] = []
        for candidate in self._dir.glob(f"*{_SUFFIX}"):
            if not candidate.is_file():
                continue
            if TEMPLATE_NAME_PATTERN.fullmatch(candidate.stem):
                recognised.append(candidate.stem)
            else:
                rejected.append(normalise_description(candidate.name)[:_MAX_LOGGED_NAME_CHARS])

        unrecognised = tuple(sorted(rejected))
        if unrecognised:
            # Warning level, with the names: this machine is the one place a
            # human can act on them, and the action is to rename the files.
            _logger.warning(
                "sf_template_files_unrecognised",
                extra={"count": len(unrecognised), "files": list(unrecognised)},
            )
        return TemplateScan(
            templates=tuple(
                ScreamingFrogTemplate(name=name, description=self._describe(name))
                for name in sorted(recognised)
            ),
            unrecognised=unrecognised,
        )

    def _describe(self, name: str) -> str:
        """The sidecar note for one template, or `""` when there is none.

        A missing sidecar is the normal case and is not logged: most
        templates will never have one, and a line per template per scan would
        bury the ones that matter. An *unreadable* sidecar is logged — a file
        that exists and cannot be read is a mistake someone can fix.

        Args:
            name: A stem that has already passed `TEMPLATE_NAME_PATTERN`, so
                it cannot escape the template directory.
        """
        sidecar = self._dir / f"{name}{_DESCRIPTION_SUFFIX}"
        try:
            raw = sidecar.read_bytes()[:_MAX_SIDECAR_BYTES]
        except FileNotFoundError:
            return ""
        except OSError:
            # The exception text is deliberately not logged: it embeds a
            # filesystem path this process has no reason to republish.
            _logger.warning("sf_template_description_unreadable", extra={"template": name})
            return ""
        text = normalise_description(raw.decode("utf-8", errors="replace"))
        if len(text) > MAX_TEMPLATE_DESCRIPTION_CHARS:
            _logger.warning(
                "sf_template_description_truncated",
                extra={"template": name, "chars": len(text)},
            )
            text = text[:MAX_TEMPLATE_DESCRIPTION_CHARS]
        return text

    def resolve(self, name: str) -> Path:
        """The on-disk path for a template name.

        Args:
            name: Operator-chosen template name, as returned by
                `list_templates()`.

        Returns:
            The `.seospiderconfig` path, confirmed to exist and to resolve
            inside `template_dir`.

        Raises:
            TemplateNotFoundError: `name` fails `TEMPLATE_NAME_PATTERN`, the
                resolved path escapes `template_dir`, or no such file exists.
        """
        if not TEMPLATE_NAME_PATTERN.fullmatch(name):
            msg = f"invalid Screaming Frog template name '{name}'"
            raise TemplateNotFoundError(msg)

        root = self._dir.resolve()
        candidate = (self._dir / f"{name}{_SUFFIX}").resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            _logger.warning("sf_template_path_escape", extra={"name": name})
            msg = f"Screaming Frog template '{name}' does not resolve inside the template directory"
            raise TemplateNotFoundError(msg) from exc

        if not candidate.is_file():
            msg = f"unknown Screaming Frog template '{name}'"
            raise TemplateNotFoundError(msg)
        return candidate
