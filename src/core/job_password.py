"""Policy constants for the per-job deletion password (ADR 0042).

The password that protects a crawl job is set once, at creation, and every
job-scoped write checks it. The rules live here, not in `server.py`, because
three layers need the same numbers: the crawl request model (which refuses a
short password at creation), the delete request (which checks the password
against the stored hash and bounds its length), and the lock in `state_store.py`
(which counts wrong ones). The floor is not applied at deletion, so a job created
with a shorter password stays deletable.

Why a floor of twelve characters: the password is the only control between
an org member and a destructive write once a session is held. Twelve gives
the lock time to matter; a shorter one would make the lock the only thing
standing between a guesser and the job.
"""

from __future__ import annotations

MIN_DELETION_PASSWORD_LENGTH = 12
"""Shortest password accepted at job creation and at deletion (audit F4)."""

MAX_DELETION_PASSWORD_LENGTH = 256
"""Longest password accepted anywhere. Bounds the work one guess can cost."""

JOB_PASSWORD_HEADER = "X-Deletion-Password"  # noqa: S105 - a header name, not a credential
"""Request header that carries the password on non-delete job writes.

A header rather than a body because some of those routes take a raw file or
CSV body, and a query string would land in access logs.
"""
