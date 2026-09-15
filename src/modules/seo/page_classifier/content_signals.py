"""Native extraction of the title, meta description and H1 at crawl time.

Before this module, `FullPageIntelligenceProfile` carried a resolved canonical
URL and an indexability verdict but nothing about a page's own title, meta
description or H1 — so the seventeen `PAGE_TITLES` / `META_DESCRIPTION` / `H1`
catalogue issues in `audit_export.py` were all `NOT_MEASURED`, not because
nobody had written the rules, but because nothing upstream ever read the three
elements those rules need. This module is what closes that gap.

A pure function over already-fetched content, exactly like `signal_parsers`
(see its module docstring): nothing here opens a socket, which is what makes
the tokenising rules below exhaustively testable offline.

Design choices worth stating rather than discovering by reading the code:

* **`html.parser`, not a DOM.** No tree is built, so "inside `<head>`" cannot
  be read off an ancestor chain. It is tracked instead as a one-way flip —
  `_closed_head` — set the first time a start tag arrives whose name is not
  one of the handful legitimately found in or before `<head>`. That is a
  heuristic for malformed and no-`<head>` documents alike, not a claim about
  DOM structure, and it is why a document with no `<head>` tag at all still
  classifies a leading `<title>` as inside it.
* **`<noscript>` is excluded by a depth counter**, not a flag, because it can
  nest. Its usual content is a tracking-pixel fallback for when JavaScript is
  disabled, and a `<title>` or `<meta name="description">` inside one would be
  a false positive for a page that never actually declares it — so nothing
  inside a `<noscript>` is counted, captured, or allowed to flip
  `_closed_head`.
* **HTML comments need no special handling.** `html.parser`'s tokenizer never
  emits `handle_starttag` for markup inside `<!-- -->`, including an
  unterminated comment that runs to end of document — a test in the mirror
  file pins this rather than assuming it.
* **Count and text are independent.** The first occurrence of an element wins
  the *text* (matching `document.title` semantics in a real browser), but
  every occurrence — including a duplicate, and including a malformed nested
  one — increments the *count*. `PAGE_TITLES_MULTIPLE` reads the count, never
  whether two occurrences' text happens to match.
* **Truncation, not exception, is the runaway-tag defence.** An unterminated
  `<title>` would otherwise accumulate the rest of the document before any
  cap could apply. `_accumulate` stops appending once a field reaches its
  `max_length`, so the field is honestly truncated rather than dropped — and
  `cascading_pipeline`'s "never raises for an unclassifiable page" contract
  holds even for a document that never closes its own tags.
"""

from __future__ import annotations

from html.parser import HTMLParser

from pydantic import Field

from src.core.schemas import StrictModel

__all__ = [
    "H1_MAX_LENGTH",
    "META_DESCRIPTION_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "ContentSignals",
    "extract_content_signals",
]

TITLE_MAX_LENGTH = 500
"""Cap on captured `<title>` text. Bounds memory against an unterminated tag;
well past any title a client would actually write."""

META_DESCRIPTION_MAX_LENGTH = 500
"""Cap on captured meta description text. Same rationale as `TITLE_MAX_LENGTH`."""

H1_MAX_LENGTH = 1000
"""Cap on captured `<h1>` text. Wider than the title caps because an `<h1>`
legitimately holds more than a title does — a product name plus a strapline is
common — while still bounding a runaway or unterminated tag."""

# Tags legitimately seen in or before `<head>`. The first start tag whose name
# is *not* in this set flips `_closed_head` permanently — a heuristic for
# malformed markup, not a read of actual DOM ancestry (`html.parser` builds no
# tree to read).
_HEAD_ALLOWED_TAGS: frozenset[str] = frozenset(
    {"head", "title", "meta", "link", "base", "style", "script", "noscript", "html"}
)


class ContentSignals(StrictModel):
    """Title, meta description and H1, as natively read from one page's HTML.

    Attributes:
        page_title: Text of the first `<title>` element encountered, matching
            DOM `document.title` semantics. `""` when the page declares none.
        page_title_count: Every `<title>` start tag seen, including duplicates
            and malformed nesting. Independent of `page_title`: two titles
            with identical text still count as two.
        page_title_outside_head: Whether any `<title>` occurrence — winning or
            not — appeared after `_closed_head` had already flipped.
        meta_description: `content` of the first `<meta name="description">`,
            matched case-insensitively on `name`'s value. `""` when absent.
        meta_description_count: Every matching `<meta>` start tag seen.
        meta_description_outside_head: As `page_title_outside_head`, for the
            meta description.
        h1_text: Text of the first `<h1>` element encountered. `""` when the
            page has none. No `h1_outside_head` field exists: the catalogue
            has no `H1_OUTSIDE_HEAD` issue, since an `<h1>` belongs in the
            body by definition.
        h1_count: Every `<h1>` start tag seen, including malformed nesting.
    """

    page_title: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    page_title_count: int = Field(default=0, ge=0)
    page_title_outside_head: bool = False

    meta_description: str = Field(default="", max_length=META_DESCRIPTION_MAX_LENGTH)
    meta_description_count: int = Field(default=0, ge=0)
    meta_description_outside_head: bool = False

    h1_text: str = Field(default="", max_length=H1_MAX_LENGTH)
    h1_count: int = Field(default=0, ge=0)


def _accumulate(buffer: list[str], chunk: str, limit: int) -> None:
    """Append `chunk` to `buffer` without letting its joined length pass `limit`.

    The entire defence against a runaway or unterminated tag: without this, an
    unclosed `<title>` would copy the rest of the document into memory, once
    per page, for the life of a crawl, before truncation ever ran.
    """
    used = sum(len(piece) for piece in buffer)
    if used >= limit:
        return
    buffer.append(chunk[: limit - used])


class _ContentSignalsExtractor(HTMLParser):
    """Tokenise a document for its title, meta description and H1, once each."""

    def __init__(self) -> None:
        """Start inside no landmark, with the head still open."""
        super().__init__(convert_charrefs=True)
        self.page_title = ""
        self.page_title_count = 0
        self.page_title_outside_head = False
        self.meta_description = ""
        self.meta_description_count = 0
        self.meta_description_outside_head = False
        self.h1_text = ""
        self.h1_count = 0

        self._closed_head = False
        self._noscript_depth = 0

        self._title_depth = 0
        self._title_buffer: list[str] = []
        self._title_captured = False

        self._h1_depth = 0
        self._h1_buffer: list[str] = []
        self._h1_captured = False

        self._meta_captured = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Count an occurrence, capture a winning value, and track head/noscript state."""
        if tag == "noscript":
            self._noscript_depth += 1
            return
        if self._noscript_depth > 0:
            return

        if tag == "title":
            self.page_title_count += 1
            if self._closed_head:
                self.page_title_outside_head = True
            if self._title_depth == 0:
                self._title_buffer = []
            self._title_depth += 1
        elif tag == "meta":
            attributes = {name.lower(): (value or "") for name, value in attrs}
            if attributes.get("name", "").lower() == "description":
                self.meta_description_count += 1
                if self._closed_head:
                    self.meta_description_outside_head = True
                if not self._meta_captured:
                    content = attributes.get("content", "")
                    self.meta_description = content[:META_DESCRIPTION_MAX_LENGTH]
                    self._meta_captured = True
        elif tag == "h1":
            self.h1_count += 1
            if self._h1_depth == 0:
                self._h1_buffer = []
            self._h1_depth += 1

        if not self._closed_head and tag not in _HEAD_ALLOWED_TAGS:
            self._closed_head = True

    def handle_endtag(self, tag: str) -> None:
        """Close a landmark, or finalise a winning element's accumulated text."""
        if tag == "noscript":
            if self._noscript_depth > 0:
                self._noscript_depth -= 1
            return
        if self._noscript_depth > 0:
            return

        if tag == "title" and self._title_depth > 0:
            self._title_depth -= 1
            if self._title_depth == 0:
                self._finish_title()
        elif tag == "h1" and self._h1_depth > 0:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                self._finish_h1()

    def handle_data(self, data: str) -> None:
        """Accumulate text for whichever tracked element is currently open."""
        if self._noscript_depth > 0:
            return
        if self._title_depth > 0:
            _accumulate(self._title_buffer, data, TITLE_MAX_LENGTH)
        if self._h1_depth > 0:
            _accumulate(self._h1_buffer, data, H1_MAX_LENGTH)

    def close(self) -> None:
        """Finalise any element still open at end of document.

        An unclosed `<title>` or `<h1>` is truncated markup, not an absent
        one — the bytes were fetched, and a real browser would render
        whatever text preceded the cutoff. Dropping it here would
        under-report a page that genuinely has one.
        """
        super().close()
        if self._title_depth > 0:
            self._title_depth = 0
            self._finish_title()
        if self._h1_depth > 0:
            self._h1_depth = 0
            self._finish_h1()

    def _finish_title(self) -> None:
        if not self._title_captured:
            self.page_title = "".join(self._title_buffer)
            self._title_captured = True

    def _finish_h1(self) -> None:
        if not self._h1_captured:
            self.h1_text = "".join(self._h1_buffer)
            self._h1_captured = True


def extract_content_signals(html: str) -> ContentSignals:
    """Read the title, meta description and H1 a page declares about itself.

    Args:
        html: Raw page HTML, as fetched.

    Returns:
        `ContentSignals` with `""` / `0` / `False` defaults for anything the
        page omits. Never raises: malformed markup yields whatever was
        collected before the parser gave up, matching `extract_nav_links`'s
        contract in `signal_parsers`.
    """
    parser = _ContentSignalsExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not abort a crawl
        return _signals_from(parser)
    return _signals_from(parser)


def _signals_from(parser: _ContentSignalsExtractor) -> ContentSignals:
    """Project the tokenizer's accumulated state onto the public contract."""
    return ContentSignals(
        page_title=parser.page_title,
        page_title_count=parser.page_title_count,
        page_title_outside_head=parser.page_title_outside_head,
        meta_description=parser.meta_description,
        meta_description_count=parser.meta_description_count,
        meta_description_outside_head=parser.meta_description_outside_head,
        h1_text=parser.h1_text,
        h1_count=parser.h1_count,
    )
