"""Re-run placement over a stored crawl and print what changed.

Answers "what would this crawl look like under today's rules?" without
re-crawling. Useful after any change to the header-menu parser or the placement
rules, which is most of what this engine gets changed for.

Two modes, and the difference matters:

* **Default — no network.** The stored menu is reused as-is, so only the
  *placement* rules re-run. A change to `nav_tree_parser` has no effect, because
  a finished crawl stores no HTML to re-parse.
* **`--fetch-homepage` — one request.** Re-fetches the homepage and re-parses
  the menu with it. This is what applies a nav-parser fix to an old crawl. One
  request, not a re-crawl.

Neither mode can re-extract breadcrumbs: the page bodies they were read from are
gone. `own_breadcrumb` preserves what each page published, which is what makes
placement re-runnable at all, but the raw markup is not recoverable.

Usage:
    python scripts/reparse_crawl.py .jobs/<id>.result.json
    python scripts/reparse_crawl.py .jobs/<id>.result.json --fetch-homepage
    python scripts/reparse_crawl.py .jobs/<id>.result.json --out new.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from src.modules.seo.page_classifier.tool import PageClassificationOutput, reparse_placement


def _fetch(url: str) -> str | None:
    """Fetch one homepage. The only network this script ever does."""
    import httpx

    try:
        with httpx.Client(
            timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            return client.get(url).text
    except Exception as exc:  # noqa: BLE001 - a failed fetch degrades to no-network mode
        print(f"  homepage fetch failed ({type(exc).__name__}) — reusing the stored menu")
        return None


def _roots(result: PageClassificationOutput) -> list[str]:
    return [node.label for node in result.navigation.roots]


def _report(before: PageClassificationOutput, after: PageClassificationOutput) -> None:
    """Print the delta. Counts first, then the lists that explain them."""
    b_roots, a_roots = _roots(before), _roots(after)
    print(f"\n  roots        {len(b_roots):5d} -> {len(a_roots)}")

    b_src = Counter(page.trail_source for page in before.pages)
    a_src = Counter(page.trail_source for page in after.pages)
    for source in ("menu", "breadcrumb", "none"):
        print(f"  {source:12s} {b_src[source]:5d} -> {a_src[source]}")

    moved = sum(
        1
        for old, new in zip(before.pages, after.pages, strict=True)
        if old.breadcrumb_path != new.breadcrumb_path
    )
    print(f"  pages moved  {moved:5d} of {len(after.pages)}")

    gained = [label for label in a_roots if label not in b_roots]
    lost = [label for label in b_roots if label not in a_roots]
    if gained:
        print(f"\n  gained roots: {', '.join(gained[:12])}")
    if lost:
        print(f"  lost roots:   {', '.join(lost[:12])}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="reparse_crawl", description=__doc__)
    parser.add_argument("result", type=Path, help="path to a *.result.json")
    parser.add_argument(
        "--fetch-homepage",
        action="store_true",
        help="re-fetch the homepage (one request) so the menu itself is re-parsed",
    )
    parser.add_argument("--out", type=Path, help="write the reparsed result here")
    args = parser.parse_args()

    if not args.result.is_file():
        print(f"no such file: {args.result}", file=sys.stderr)
        return 1

    before = PageClassificationOutput.model_validate_json(args.result.read_text(encoding="utf-8"))
    print(f"{before.base_url}  ({len(before.pages):,} pages)")

    html = _fetch(before.base_url) if args.fetch_homepage else None
    if not args.fetch_homepage:
        print("  no network — stored menu reused, only placement rules re-run")

    started = time.perf_counter()
    after = reparse_placement(before, html)
    print(f"  reparsed in {(time.perf_counter() - started) * 1000:.0f}ms")

    _report(before, after)

    if args.out:
        args.out.write_text(json.dumps(after.model_dump(mode="json"), indent=2), encoding="utf-8")
        print(f"\n  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
