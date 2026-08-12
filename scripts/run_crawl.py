"""Run the Phase 1 Page Classification Engine against a live site.

The operator-facing entry point. Everything it does goes through the governed
`PageClassificationTool`, so a run here is subject to the same SSRF validation,
robots compliance, per-host throttling and audit logging as any other caller.

Usage:
    python scripts/run_crawl.py https://example.com
    python scripts/run_crawl.py https://example.com --max-pages 200 --depth 2
    python scripts/run_crawl.py http://127.0.0.1:8000 --allow-private   # fixtures

Defaults are deliberately conservative. This crawls somebody else's server, and
the polite default is a small, low-concurrency pass. Raise the limits knowingly.

`--max-pages` is what bounds a run, not `--depth`. Depth is unlimited by default
because a ceiling does not reduce how many pages are fetched — the page budget
is spent either way — it only decides whether the budget goes to a deep site's
lower levels or is left unspent.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make `src` importable when this is run directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.schemas import ExecutionStatus  # noqa: E402
from src.core.url_safety import UrlSafetyPolicy  # noqa: E402
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
)
from src.modules.seo.page_classifier.tree_visualizer import render_tree_html  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_crawl",
        description="Crawl a site and classify every page by hierarchy, type and intent.",
    )
    parser.add_argument("url", help="Site root, e.g. https://example.com")
    parser.add_argument("--max-pages", type=int, default=50, help="Node ceiling (default 50)")
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Link depth ceiling. Omit for unlimited (bounded by --max-pages).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3, help="Simultaneous requests (default 3)"
    )
    parser.add_argument("--out", default="", help="HTML report path (default <host>-tree.html)")
    parser.add_argument(
        "--user-agent", default="RankunoBot", help="Product token sent and matched against robots"
    )
    parser.add_argument(
        "--no-dom", action="store_true", help="Skip the DOM link crawl (sitemap + CMS only)"
    )
    parser.add_argument(
        "--dom-reserve",
        type=float,
        default=0.2,
        help="Share of the budget only the DOM crawl may fill (default 0.2). Raise it when "
        "the run reports the reserve exhausted.",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Permit private/loopback targets. Local fixtures only — this disables the SSRF guard.",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Ignore robots.txt. Only for a site you own.",
    )
    return parser


def _print_report(output: PageClassificationOutput, elapsed: float) -> None:
    discovery = output.discovery
    summary = output.summary
    profile = output.site_profile

    print(f"\n{'=' * 68}")
    print(f"  {output.base_url}")
    print(f"{'=' * 68}")

    print("\nSITE PROFILE")
    print(f"  platform           {profile.cms_family}")
    print(f"  client-rendered    {profile.renders_client_side}")
    print(f"  catalogue          {profile.has_catalogue}")
    print(f"  locales            {', '.join(profile.locale_prefixes) or '-'}")
    print(
        f"  weight vector      {output.weight_profile.profile_name} "
        f"(detected: {output.weight_profile.detected_profile_name})"
    )

    print("\nDISCOVERY")
    print(f"  total URLs         {discovery.total_urls}")
    print(f"  from sitemap       {discovery.from_sitemap}")
    print(f"  from DOM links     {discovery.from_dom}")
    print(f"  from CMS API       {discovery.from_cms}")
    print(f"  sitemap-only       {discovery.sitemap_only}   (orphan candidates)")
    print(f"  DOM-only           {discovery.dom_only}   (missing from sitemaps)")
    print(f"  orphans            {discovery.orphans}")
    print(f"  sitemaps parsed    {discovery.sitemaps_fetched}")
    print(f"  pages fetched      {discovery.pages_fetched}")
    print(f"  media skipped      {discovery.media_skipped}   (images/assets, not pages)")
    print(f"  truncated          {discovery.truncated}")

    exhausted = discovery.dom_reserve and discovery.dom_reserve_used >= discovery.dom_reserve
    print(f"  DOM reserve        {discovery.dom_reserve_used}/{discovery.dom_reserve} used")
    if exhausted:
        # The reserve is the only budget a sitemap-omitted page can occupy, so
        # hitting the cap means such pages are still being dropped.
        print("    ^ EXHAUSTED — sitemap-omitted pages are still being dropped.")
        print("      Raise --dom-reserve or --max-pages to capture more of them.")

    print("\nCLASSIFICATION")
    print(f"  pages classified   {summary.pages_classified}")
    print(f"  unclassified       {summary.unknown_pages}")
    print(f"  low confidence     {summary.low_confidence_pages}")
    print(f"  escalated to LLM   {summary.escalated_to_llm} ({summary.escalation_rate:.1%})")
    print(f"  LLM spend          ${summary.llm_spend_usd:.4f}")

    counts: dict[str, int] = {}
    for page in output.pages:
        counts[page.primary_page_type.value] = counts.get(page.primary_page_type.value, 0) + 1
    if counts:
        print("\nPAGE TYPES")
        for name, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {count:>5}  {name}")

    levels: dict[str, int] = {}
    for page in output.pages:
        levels[page.hierarchy_level.value] = levels.get(page.hierarchy_level.value, 0) + 1
    if levels:
        print("\nHIERARCHY")
        for name, count in sorted(levels.items()):
            print(f"  {count:>5}  {name}")

    rate = summary.pages_classified / elapsed if elapsed > 0 else 0.0
    print(f"\nTIMING\n  elapsed            {elapsed:.2f}s")
    print(f"  throughput         {rate:.1f} pages/sec")


def main() -> int:
    args = build_parser().parse_args()

    policy = UrlSafetyPolicy(allow_private_ips=args.allow_private) if args.allow_private else None
    tool = PageClassificationTool(url_policy=policy)

    payload = PageClassificationInput(
        base_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.depth,
        concurrency=args.concurrency,
        crawl_dom=not args.no_dom,
        dom_reserve_fraction=args.dom_reserve,
        respect_robots=not args.ignore_robots,
        user_agent=args.user_agent,
    )

    depth_label = "unlimited depth" if args.depth is None else f"depth {args.depth}"
    print(
        f"Crawling {args.url} (max {args.max_pages} pages, {depth_label}, "
        f"concurrency {args.concurrency})..."
    )

    started = time.perf_counter()
    result = tool.run(payload)
    elapsed = time.perf_counter() - started

    if result.status is not ExecutionStatus.SUCCESS or not isinstance(
        result.data, PageClassificationOutput
    ):
        print(f"\nFAILED [{result.status}]: {result.error}")
        return 1

    _print_report(result.data, elapsed)

    host = args.url.split("://")[-1].split("/")[0].replace(":", "_")
    destination = Path(args.out) if args.out else Path(f"{host}-tree.html")
    destination.write_text(
        render_tree_html(
            result.data.pages,
            site_name=args.url,
            subtitle=(
                f"{result.data.summary.pages_classified} pages · "
                f"{result.data.discovery.orphans} orphans · crawled in {elapsed:.1f}s"
            ),
        ),
        encoding="utf-8",
    )
    print(f"\nReport written to {destination.resolve()}")
    print(f"Trace: {result.trace_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
