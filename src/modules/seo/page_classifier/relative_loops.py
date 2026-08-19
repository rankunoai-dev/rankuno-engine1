"""Detect URLs fabricated by a relative link resolved against every parent.

The defect this finds
---------------------
A template emits `href="software/b2b-payments/credit-card-surcharge/"` with no
leading slash. Every page that renders the template resolves it against its own
address, so one real page acquires an address under every parent on the site —
and each of those is itself a page that renders the template again. On
highradius.com this produced 23,641 distinct URLs for one page in a single
crawl, and 46,103 across the stored corpus.

Why the existing trap rules cannot see it
-----------------------------------------
`is_spider_trap` inspects one URL and looks for a segment repeated *within* it.
That catches the second and later generations, where `software` finally appears
twice — 3,214 refusals on one crawl. It cannot catch the first generation,
because `/resources/value-creation/software/b2b-payments/credit-card-surcharge/`
is a perfectly well-formed path with no repetition in it at all. 2,652 of those
sailed through, and Screaming Frog's independent crawl of the same site
confirmed they are not pages.

The loop is only visible across the corpus: the same tail appearing under many
unrelated parents. That makes this a whole-crawl pass rather than a per-URL
predicate, which is why it lives here and not in `url_rules`.

Repetition alone is not the signal — this is the whole design
-------------------------------------------------------------
The obvious rule is "refuse a tail that repeats often". Measured across 65
stored crawls and 392,835 URLs, that rule is **wrong**: 19 distinct tails repeat
25 times or more, and most of them are legitimate.

* `stripe.com/…/newsroom/news/stripe-and-uber` — 77 times, one real page under
  77 locale prefixes. Locales are deliberately kept as distinct URLs
  (`normalize_url(strip_locale=False)`), so every one is a page we mean to hold.
* `infosys.com/…/documents/transcripts/press-conference.pdf` — 78 times, real
  files under different year and quarter folders.
* `kinsta.com/…/jp/signup/wp`, `gep.com/…/strategy/category/procurement-strategy`
  — the same shape again.

A count threshold alone would have deleted thousands of real pages.

**Depth spread is what separates them.** A locale or date prefix is a fixed
shape, so every copy sits at the *same* path depth: all 19 legitimate tails
appear at exactly **one** distinct depth. A relative-href loop grows by
appending to whatever page rendered it, so its copies pile up across many
depths: the real loops span 5, 6, 7, 18, 25 and 43 distinct depths.

The two populations do not overlap, and the rule is drawn through the gap.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.url_rules import safe_split

__all__ = [
    "MIN_DEPTH_SPREAD",
    "MIN_LOOP_URLS",
    "TAIL_SEGMENTS",
    "LoopReport",
    "LoopSignature",
    "LoopWatcher",
    "find_relative_loops",
]

_logger = get_logger("modules.seo.relative_loops")

TAIL_SEGMENTS = 3
"""Path segments compared when looking for a repeated tail.

Two is too weak: `/product/x/overview` legitimately repeats under every product
on a catalogue. Three is the shortest tail that was unambiguous across the
stored corpus.
"""

MIN_LOOP_URLS = 25
"""Copies of a tail before it is worth examining at all.

A cheap pre-filter, not the decision — `MIN_DEPTH_SPREAD` makes that. Set above
the largest legitimate cluster that is *not* already excluded by depth, so the
expensive check runs on a handful of candidates rather than every tail on the
site.
"""

MIN_DEPTH_SPREAD = 4
"""Distinct path depths a repeated tail must span to be called a loop.

The measured separation, with a wide margin on both sides. Across 65 crawls
every legitimate repeated tail appeared at exactly **1** depth; every genuine
loop spanned at least **5**. Four sits in the empty gap between them.

It is deliberately not lower. A site that publishes both `/blog/post` and
`/en-gb/blog/post` gives one tail two depths honestly, and a threshold of 2
would refuse a real page to catch nothing.

The cost of the margin is stated rather than hidden: one small loop on
highradius.com — 27 URLs across 3 depths — is left in. Refusing it would mean
moving the threshold onto the same value legitimate locale pairs produce, and a
report that keeps 27 artefacts is better than one that deletes real pages.
"""


class LoopSignature(StrictModel):
    """One tail that behaves like a relative-href loop.

    Attributes:
        tail: The repeated path ending, without a leading slash.
        url_count: URLs sharing it.
        depth_count: Distinct path depths they sit at. This is the number that
            decided the verdict.
    """

    tail: str = Field(min_length=1)
    url_count: int = Field(ge=0)
    depth_count: int = Field(ge=0)


class LoopReport(StrictModel):
    """Loops found in one crawl, and the URLs they account for.

    Attributes:
        signatures: One entry per detected loop, largest first.
        urls: Every URL belonging to a detected loop. These are artefacts of a
            broken relative link, not pages.
    """

    signatures: tuple[LoopSignature, ...] = ()
    urls: tuple[str, ...] = ()

    @property
    def url_count(self) -> int:
        """How many URLs the loops account for."""
        return len(self.urls)


def _tail_of(url: str) -> tuple[str, int] | None:
    """The last `TAIL_SEGMENTS` path segments, and the full path depth.

    Returns `None` for a path too short to have a tail, which cannot be a loop:
    a loop needs a prefix to attach to — and for a URL that will not parse.

    `safe_split` rather than `urlsplit`, because `urlsplit` *raises* on input a
    crawl really produces: `http://[` is an unterminated IPv6 literal and throws
    `ValueError`. This runs over every URL in the crawl, so one malformed
    address would take the whole pass down.
    """
    parts = safe_split(url)
    if parts is None:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < TAIL_SEGMENTS:
        return None
    return "/".join(segments[-TAIL_SEGMENTS:]), len(segments)


def find_relative_loops(urls: tuple[str, ...]) -> LoopReport:
    """Find URLs fabricated by a relative link resolved against many parents.

    A whole-crawl pass, because the evidence does not exist in a single URL —
    every fabricated address is individually well-formed.

    Args:
        urls: Every URL in the crawl.

    Returns:
        The loops found and the URLs they account for. Empty on the vast
        majority of sites: across 65 stored crawls this fired on one.
    """
    by_tail: defaultdict[str, list[str]] = defaultdict(list)
    depths: defaultdict[str, set[int]] = defaultdict(set)

    for url in urls:
        found = _tail_of(url)
        if found is None:
            continue
        tail, depth = found
        by_tail[tail].append(url)
        depths[tail].add(depth)

    signatures: list[LoopSignature] = []
    caught: list[str] = []
    for tail, members in by_tail.items():
        # Count first: it is a dictionary lookup, and it rules out almost every
        # tail on a normal site before the depth set is examined.
        if len(members) < MIN_LOOP_URLS:
            continue
        spread = len(depths[tail])
        if spread < MIN_DEPTH_SPREAD:
            continue
        signatures.append(LoopSignature(tail=tail, url_count=len(members), depth_count=spread))
        caught.extend(members)

    signatures.sort(key=lambda signature: signature.url_count, reverse=True)
    if signatures:
        _logger.warning(
            "relative_loops_found",
            extra={"loops": len(signatures), "urls": len(caught)},
        )
    return LoopReport(signatures=tuple(signatures), urls=tuple(sorted(caught)))


class LoopWatcher:
    """Confirms loops as a crawl runs, so they stop costing fetches.

    `find_relative_loops` needs the finished corpus. A crawl cannot wait for
    that: on highradius.com the loop is 35.9% of every URL discovered, and
    fetching them is most of the crawl's wasted time. This decides as it goes.

    The awkward part, stated plainly
    --------------------------------
    A loop is not provable until enough of it exists. The evidence *is* the
    repetition, so the first members are admitted before there is any reason to
    refuse them. Rather than leave them in the graph, confirming a tail also
    names every URL already let through under it, and the caller evicts them.
    The tail is refused for the rest of the crawl.

    That makes the count exact — all 46,103 rather than the ~46,080 a
    forward-only rule would catch — at the cost of an eviction step the caller
    has to honour. `SiteGraph.add` is the only caller and it does.

    Memory is one entry per URL with a long enough path, holding the normalised
    key that the graph already stores. On a 500,000-URL crawl that is the
    largest single structure this class owns, and it is bounded by the crawl.
    """

    __slots__ = ("_confirmed", "_depths", "_keys")

    def __init__(self) -> None:
        """Start with nothing confirmed and no tails seen."""
        self._keys: defaultdict[str, list[str]] = defaultdict(list)
        """Normalised keys admitted under each tail, until it is confirmed."""
        self._depths: defaultdict[str, set[int]] = defaultdict(set)
        self._confirmed: set[str] = set()

    def observe(self, url: str, key: str) -> tuple[bool, tuple[str, ...]]:
        """Judge one URL as it is discovered.

        Args:
            url: The absolute URL.
            key: Its normalised graph key, used for eviction.

        Returns:
            `(refuse, evict)`. `refuse` means do not admit this URL. `evict`
            names keys admitted earlier under a tail that has just been
            confirmed, and is empty except on the single call that confirms it.
        """
        found = _tail_of(url)
        if found is None:
            return False, ()
        tail, depth = found

        if tail in self._confirmed:
            return True, ()

        self._keys[tail].append(key)
        self._depths[tail].add(depth)
        if len(self._keys[tail]) < MIN_LOOP_URLS or len(self._depths[tail]) < MIN_DEPTH_SPREAD:
            return False, ()

        self._confirmed.add(tail)
        evict = tuple(self._keys.pop(tail))
        self._depths.pop(tail, None)
        _logger.warning(
            "relative_loop_confirmed",
            extra={"tail": tail, "evicted": len(evict)},
        )
        return True, evict
