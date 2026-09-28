"""The shape of what a worker daemon reports about its own config templates.

Split out of `worker_auth.py` rather than added to it for two reasons. The
first is size (that module is already at this codebase's 400-line target).
The second matters more: these types are consumed by three layers that have
no business importing worker *identity* — the HTTP wire models in
`src.api.worker_schemas`, the daemon-side registry in
`src.modules.seo.screaming_frog_control.template_registry`, and the
persistence in `src.core.postgres_worker_store`. A shared value object with
no dependency on password hashing is the honest home for them.

**Why a description exists at all.** A `.seospiderconfig` is a Java
`ObjectInputStream`-serialised blob. Nothing in this system can open one and
say what it does — not the cloud API, not the daemon, not a reviewer. An
operator choosing `advance-with-url-parameter` from a dropdown is therefore
guessing unless a human wrote down what it captures. The description is that
sentence, authored beside the config on the machine that holds it and
carried up on the heartbeat. It is documentation, never configuration:
nothing reads it to decide how a crawl runs.

**Why it is treated as hostile.** A worker daemon is a machine on someone's
desk, outside this system's trust boundary (`src.api.worker_schemas` states
the same stance for the name). The description is a free-text string that
originates there and ends up inside an operator's browser, so it is capped,
refused if it carries control, zero-width or bidirectional-override
characters, and never interpolated into an error message or a log line. The
rejection message below deliberately does not echo the offending value.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, Field

from src.core.schemas import StrictModel

__all__ = [
    "MAX_REPORTED_TEMPLATES",
    "MAX_TEMPLATE_DESCRIPTION_CHARS",
    "TEMPLATE_NAME_PATTERN",
    "TemplateDescription",
    "WorkerTemplate",
    "WorkerTemplateReport",
    "normalise_description",
]

TEMPLATE_NAME_PATTERN = r"^[a-z0-9_-]{1,128}$"
"""Must stay identical to `screaming_frog_control.template_registry.
TEMPLATE_NAME_PATTERN`, which is the rule that actually decides whether a
name can become a path component. It is restated there rather than imported
because that module compiles it, and a test asserts the two literals agree,
so a change to one that forgets the other fails loudly instead of opening a
traversal hole in the worker-reported half."""

MAX_REPORTED_TEMPLATES = 200
"""Ceiling on how many templates one worker may report about itself.

A worker is *untrusted input* on this path — it is a machine on someone's
desk, not part of the trust boundary — so the number of entries it can make
the cloud store is bounded, the same way `upload_manifest.MAX_ZIP_MEMBERS`
bounds what it can make the cloud unzip. With the description cap below,
this also bounds one heartbeat body at roughly 130 KB."""

MAX_TEMPLATE_DESCRIPTION_CHARS = 500
"""Ceiling on one description. Matches `ScreamingFrogTemplate.description`,
which imports this constant so the two cannot drift."""

_FORBIDDEN_DESCRIPTION_CHARS = re.compile("[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]")
"""C0/C1 controls, zero-width characters, and the bidirectional overrides.

Not cosmetic. `U+202E RIGHT-TO-LEFT OVERRIDE` reverses the rendering of
everything after it, which is how a benign-looking string is made to read as
a different one in a browser; zero-width characters hide content inside what
looks like a short label; C0 controls corrupt a log line. React escapes HTML
for us, so this class is not the XSS defence — it is the defence against a
description that renders as something other than what it contains.

Expressed as a compiled Python pattern behind an `AfterValidator` rather
than as a Pydantic `pattern=`, because `pattern=` is handed to the Rust
regex engine and `^...$` there (and in Python's `re`) still matches a string
with a trailing newline. An explicit `search` for what is forbidden has no
such edge."""


def _reject_control_characters(value: str) -> str:
    """Refuse a description carrying anything from `_FORBIDDEN_DESCRIPTION_CHARS`.

    Raises:
        ValueError: If the value contains a control, zero-width or
            bidirectional-override character. The message names the class of
            problem and never echoes the value — an error string built from
            untrusted input is the second place that input gets rendered.
    """
    if _FORBIDDEN_DESCRIPTION_CHARS.search(value):
        msg = "template description contains a control, zero-width or bidi-override character"
        raise ValueError(msg)
    return value


_WHITESPACE_RUN = re.compile(r"\s+")


def normalise_description(value: str) -> str:
    """Make free text from a worker's disk safe to store, ship and render.

    Applied on the worker, before a description is ever sent, so that a
    sidecar file with a stray tab or a trailing newline yields a usable
    sentence instead of failing the cloud's validation and taking the whole
    heartbeat — and every other template's description — down with it. The
    validator above remains the authority: this function is a courtesy to a
    well-meaning author, not the defence against a hostile one.

    Deliberately does **not** truncate. The caller knows which template it is
    reading and can say so in the log line; a silent truncation inside a
    normaliser would be the same class of silence this cycle exists to fix.

    Args:
        value: Raw text, typically the whole contents of a sidecar file.

    Returns:
        The text with every run of whitespace collapsed to one space, ends
        stripped, and control, zero-width and bidirectional-override
        characters removed.

    Note:
        Whitespace is collapsed *first*, and the order is load-bearing:
        newlines and tabs are themselves C0 controls, so deleting the
        forbidden set first would splice a two-line note into one word.
    """
    return _FORBIDDEN_DESCRIPTION_CHARS.sub("", _WHITESPACE_RUN.sub(" ", value)).strip()


TemplateDescription = Annotated[
    str,
    Field(max_length=MAX_TEMPLATE_DESCRIPTION_CHARS),
    AfterValidator(_reject_control_characters),
]
"""A worker-authored, operator-facing sentence about one config template."""


class WorkerTemplate(StrictModel):
    """One `.seospiderconfig` a worker reported it holds, with its note.

    Attributes:
        name: The config file's stem. Constrained by `TEMPLATE_NAME_PATTERN`
            because this value becomes a path component on the worker.
        description: What a human wrote beside the config about what it
            captures. Empty is normal and means "no sidecar note was
            written", never "this template does nothing".
    """

    name: str = Field(pattern=TEMPLATE_NAME_PATTERN)
    description: TemplateDescription = ""


class WorkerTemplateReport(StrictModel):
    """One worker's whole statement about its template directory.

    The two fields travel together because they are one observation of one
    directory at one instant. Splitting them would let a store update the
    list without the count and leave the dashboard claiming files were
    skipped that no longer exist.

    Attributes:
        templates: Every file whose name passed `TEMPLATE_NAME_PATTERN`.
        unrecognised_count: How many `.seospiderconfig` files in the same
            directory did *not*, and were therefore left out of `templates`.
            This exists because those files used to vanish in silence: a
            config saved from the Screaming Frog GUI is named
            `SEO Spider Config - Basic.seospiderconfig` by default, which
            fails the pattern, so an operator with a full directory saw an
            empty dropdown and no reason for it. A count, not the names:
            the names are attacker-controlled arbitrary filenames and are
            already logged on the machine whose directory it is, which is
            the only place a human can act on them. Saturates at
            `MAX_REPORTED_TEMPLATES`.
    """

    templates: tuple[WorkerTemplate, ...] = Field(default=(), max_length=MAX_REPORTED_TEMPLATES)
    unrecognised_count: int = Field(default=0, ge=0, le=MAX_REPORTED_TEMPLATES)
