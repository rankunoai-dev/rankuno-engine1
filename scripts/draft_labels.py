"""Crawl a site and emit a draft labelling worksheet for human review.

The worksheet is **not** a corpus. Every row carries the engine's suggestion and
an empty `expected_*` pair; nothing enters the corpus until a human fills those
in and sets `reviewed`. See `corpus_drafts.py` for why that gate is mechanical.

Usage:
    python scripts/draft_labels.py https://shop.example.com --archetype ECOMMERCE
    python scripts/draft_labels.py https://example.com --archetype FLAT_URL --max-pages 150

Rows are ordered hardest-first — lowest engine confidence at the top — because
that is where a reviewer's time is worth most.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.schemas import ExecutionStatus  # noqa: E402
from src.modules.seo.page_classifier.corpus import SiteArchetype  # noqa: E402
from src.modules.seo.page_classifier.corpus_drafts import (  # noqa: E402
    draft_rows_from_profiles,
    write_draft_csv,
)
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
)

DRAFTS_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus" / "drafts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="draft_labels",
        description="Crawl a site and emit a draft labelling worksheet for human review.",
    )
    parser.add_argument("url", help="Site root")
    parser.add_argument(
        "--archetype",
        required=True,
        choices=[member.value for member in SiteArchetype],
        help="Which archetype this site represents",
    )
    parser.add_argument("--max-pages", type=int, default=150, help="Node ceiling")
    parser.add_argument("--depth", type=int, default=2, help="Link depth")
    parser.add_argument("--concurrency", type=int, default=4, help="Simultaneous requests")
    parser.add_argument("--dom-reserve", type=float, default=0.4, help="DOM budget reserve")
    parser.add_argument("--out", default="", help="Worksheet path (default: drafts/<host>.csv)")
    parser.add_argument(
        "--limit", type=int, default=120, help="Maximum worksheet rows (hardest first)"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    print(f"Crawling {args.url} for a {args.archetype} worksheet...")
    tool = PageClassificationTool()
    result = tool.run(
        PageClassificationInput(
            base_url=args.url,
            max_pages=args.max_pages,
            max_depth=args.depth,
            concurrency=args.concurrency,
            dom_reserve_fraction=args.dom_reserve,
        )
    )

    if result.status is not ExecutionStatus.SUCCESS or not isinstance(
        result.data, PageClassificationOutput
    ):
        print(f"FAILED [{result.status}]: {result.error}")
        return 1

    output = result.data
    print(f"  detected platform  {output.site_profile.cms_family}")
    print(f"  pages classified   {output.summary.pages_classified}")
    print(f"  low confidence     {output.summary.low_confidence_pages}")
    print(f"  from CMS API       {output.discovery.from_cms}")

    rows = draft_rows_from_profiles(output.pages)[: args.limit]
    host = args.url.split("://")[-1].split("/")[0].replace(":", "_")
    destination = Path(args.out) if args.out else DRAFTS_DIR / f"{host}.csv"
    written = write_draft_csv(rows, destination)

    print(f"\nWorksheet: {destination.resolve()}")
    print(f"  {written} rows, lowest confidence first")
    print("\nThis is NOT a corpus. To use it:")
    print("  1. Fill expected_level and expected_page_type for each row.")
    print("  2. Set reviewed=y on the rows you have checked.")
    print("  3. Load with corpus_drafts.load_reviewed_csv - unreviewed rows are ignored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
