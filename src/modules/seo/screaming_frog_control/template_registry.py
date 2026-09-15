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
"""

from __future__ import annotations

import re
from pathlib import Path

from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.modules.seo.screaming_frog_control.schemas import ScreamingFrogTemplate

__all__ = ["TEMPLATE_NAME_PATTERN", "TemplateNotFoundError", "TemplateRegistry"]

_logger = get_logger(__name__)

_SUFFIX = ".seospiderconfig"

TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$")
"""Also blocks path-traversal names (`../../secrets`): a name that does not
match this can never become a `Path` component escaping the template dir."""


class TemplateNotFoundError(RankunoError):
    """No `.seospiderconfig` exists under this name in the template directory."""


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
        """Every `.seospiderconfig` in the template directory, name-sorted.

        Returns an empty tuple, not an error, when the directory is absent or
        holds nothing — that is the true out-of-the-box state until an
        operator saves a real config into it from the Screaming Frog GUI.
        """
        if not self._dir.is_dir():
            return ()
        names = sorted(
            candidate.stem
            for candidate in self._dir.glob(f"*{_SUFFIX}")
            if candidate.is_file() and TEMPLATE_NAME_PATTERN.fullmatch(candidate.stem)
        )
        return tuple(ScreamingFrogTemplate(name=name) for name in names)

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
