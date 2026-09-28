"""Worker templates carry a description, and count what they had to skip.

Revision ID: 005
Revises: 004
Create Date: 2026-09-28

A `.seospiderconfig` is an opaque Java-serialised blob: nothing in this
system can open one and report what it does. The operator picking a template
from a dropdown was therefore choosing on a slug alone. Migration 0003's
`template_names` column held exactly that — a JSON array of bare strings —
so there was nowhere for a human-authored note to live. This revision
reshapes it.

Three changes, all on `workers`:

* `template_names` is renamed to `templates` and its JSON array of strings
  is rewritten in place as an array of `{"name", "description"}` objects.
  The rename is deliberate rather than cosmetic: a column still called
  `template_names` holding objects would be read as names by the next person
  to write a query against it. Existing rows get `""` for every description,
  which is the same thing a fresh worker reports before anyone writes a
  sidecar note, so no row needs special handling afterwards.
* `unrecognised_template_count` is added. A config saved from the Screaming
  Frog GUI is named `SEO Spider Config - Basic.seospiderconfig` by default,
  which fails `TEMPLATE_NAME_PATTERN`; the registry filtered those out
  *silently*, so an operator with a full template directory saw an empty
  dropdown and no reason for it. This column carries the number so the
  dashboard can say so. `NOT NULL DEFAULT 0` because "no report yet" and
  "nothing skipped" want the same, non-alarming rendering.

**A worker daemon must be updated in lockstep with the API.** The heartbeat
body changed shape at the same time (`template_names: [str]` became
`templates: [{name, description}]`), and `StrictModel` forbids extras, so an
old daemon's heartbeat is refused with a 422. It keeps polling, keeps
running jobs, and keeps its liveness — only its reported template list stops
refreshing until the daemon is upgraded. That was judged better than
accepting both shapes forever: the daemon ships from this repository.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMES_TO_OBJECTS = """
UPDATE workers SET templates = COALESCE(
    (
        SELECT json_agg(json_build_object('name', entry.value, 'description', ''))::text
        FROM json_array_elements_text(templates::json) AS entry(value)
    ),
    '[]'
)
"""
"""Rewrite `["a","b"]` as `[{"name":"a","description":""}, ...]`.

`COALESCE` covers the empty array, for which `json_agg` returns `NULL`
rather than `[]` — without it every worker that had reported no templates
would end up with a `NULL` in a `NOT NULL` column."""

_OBJECTS_TO_NAMES = """
UPDATE workers SET templates = COALESCE(
    (
        SELECT json_agg(entry.value ->> 'name')::text
        FROM json_array_elements(templates::json) AS entry(value)
    ),
    '[]'
)
"""
"""The downgrade's inverse. Descriptions are dropped, because the column
they are going back into has no room for them — that loss is the point of
recording it here rather than discovering it later."""


def upgrade() -> None:
    """Reshape the template column and add the skipped-file count."""
    op.alter_column("workers", "template_names", new_column_name="templates")
    op.execute(_NAMES_TO_OBJECTS)
    op.add_column(
        "workers",
        sa.Column(
            "unrecognised_template_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Flatten the objects back to names and drop the count. Lossy by nature."""
    op.drop_column("workers", "unrecognised_template_count")
    op.execute(_OBJECTS_TO_NAMES)
    op.alter_column("workers", "templates", new_column_name="template_names")
