"""Score the engine against the golden corpus.

Crawls each site the corpus labels, classifies every page, and reports accuracy
**per archetype** — plus the escalation curve that prices ADR 0005's confidence
threshold against real data rather than an assumption.

Usage:
    python scripts/evaluate_corpus.py
    python scripts/evaluate_corpus.py --max-pages 500 --depth 2

Refuses to print a headline accuracy figure without the caveat when the corpus
is under-sampled, which it currently is for every archetype.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.schemas import ExecutionStatus  # noqa: E402
from src.modules.seo.page_classifier.corpus import (  # noqa: E402
    load_corpus_dir,
    summarise_gaps,
)
from src.modules.seo.page_classifier.evaluation import (  # noqa: E402
    escalation_curve,
    evaluate_predictions,
)
from src.modules.seo.page_classifier.tool import (  # noqa: E402
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
)

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate_corpus",
        description="Score the classification engine against the golden corpus.",
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Corpus directory")
    parser.add_argument("--max-pages", type=int, default=300, help="Node ceiling per site")
    parser.add_argument("--depth", type=int, default=2, help="Link depth")
    parser.add_argument("--concurrency", type=int, default=5, help="Simultaneous requests")
    parser.add_argument(
        "--dom-reserve", type=float, default=0.6, help="DOM budget reserve (default 0.6)"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    corpus = load_corpus_dir(args.corpus)
    coverage = corpus.coverage()

    print("=" * 72)
    print("  GOLDEN CORPUS EVALUATION")
    print("=" * 72)
    print(f"\nCOVERAGE\n  {coverage.summary_line()}")
    for gap in summarise_gaps(coverage):
        print(f"    gap: {gap}")

    if not corpus.sites:
        print("\nNo labelled sites. Nothing to evaluate.")
        return 1

    predictions: dict[str, PageClassificationOutput] = {}
    profiles: dict[str, object] = {}

    for site in corpus.sites:
        print(f"\nCrawling {site.base_url} ({site.archetype}, {len(site.entries)} labels)...")
        tool = PageClassificationTool()
        result = tool.run(
            PageClassificationInput(
                base_url=site.base_url,
                max_pages=args.max_pages,
                max_depth=args.depth,
                concurrency=args.concurrency,
                dom_reserve_fraction=args.dom_reserve,
            )
        )
        if result.status is not ExecutionStatus.SUCCESS or not isinstance(
            result.data, PageClassificationOutput
        ):
            print(f"  FAILED [{result.status}]: {result.error}")
            continue

        predictions[site.name] = result.data
        for page in result.data.pages:
            profiles[page.url] = page
        print(f"  {result.data.summary.pages_classified} pages classified")

    if not profiles:
        print("\nNo pages classified. Nothing to score.")
        return 1

    report = evaluate_predictions(corpus, profiles)  # type: ignore[arg-type]

    print(f"\n{'=' * 72}")
    print("ACCURACY")
    print(f"  {report.summary_line()}")
    print(f"\n  evaluated          {report.overall.evaluated}")
    print(f"  not discovered     {report.overall.missing}  (recall {report.overall.recall:.1%})")
    print(f"  level correct      {report.overall.level_accuracy:.1%}")
    print(f"  type correct       {report.overall.type_accuracy:.1%}")
    print(f"  both correct       {report.overall.exact_accuracy:.1%}")
    print(f"  predicted UNKNOWN  {report.overall.unknown_predicted}")

    if report.per_archetype:
        print("\nPER ARCHETYPE  (worst first)")
        for item in report.per_archetype:
            flag = "" if item.sufficient_sample else "  [under-sampled]"
            print(
                f"  {item.archetype!s:<16} {item.exact_accuracy:>6.1%} exact  "
                f"({item.evaluated} labels, recall {item.recall:.0%}){flag}"
            )

    if report.confusions:
        print("\nTOP CONFUSIONS")
        for confusion in report.confusions[:8]:
            print(
                f"  {confusion.count:>3}x  {confusion.expected} -> {confusion.predicted}\n"
                f"        e.g. {confusion.sample_url}"
            )

    print("\nESCALATION CURVE  (what each confidence threshold costs and buys)")
    print("  threshold   escalated   accuracy of the rest")
    for point in escalation_curve(corpus, profiles):  # type: ignore[arg-type]
        marker = "  <- ADR 0005" if abs(point.threshold - 0.85) < 1e-9 else ""
        print(
            f"    {point.threshold:>5.2f}     {point.escalation_rate:>6.1%}      "
            f"{point.exact_accuracy:>6.1%}{marker}"
        )

    if not report.is_trustworthy:
        print(
            "\nNOTE: the corpus is under-sampled. These figures describe which pages\n"
            "      happened to be labelled, not the engine. Do not publish them."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
