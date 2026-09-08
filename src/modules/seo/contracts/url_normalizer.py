"""The URL-normaliser seam shared by every producer of an `AuditDataset`.

`AuditPage.url` is a normalised key, and two datasets for one site are only
comparable if both were keyed by the same function. The engine adapter and the
Screaming Frog adapter therefore take the normaliser as a parameter rather than
importing one: `deliverables` may not import `page_classifier` (ADR 0011 d.1),
and the contract package may import neither. In production both are handed
`page_classifier.url_rules.normalize_url`, whose extra parameters are
keyword-only with defaults, so it satisfies this positional-only protocol
without a wrapper.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["UrlNormalizer"]


class UrlNormalizer(Protocol):
    """Reduce a URL to the key a dataset uses for identity.

    Positional-only so any function `(str) -> str` qualifies regardless of how
    it names its argument. Implementations must be idempotent: an adapter
    self-tests that property on entry and refuses a normaliser that fails it.
    """

    def __call__(self, url: str, /) -> str:
        """Return the normalised form of `url`."""
        ...
