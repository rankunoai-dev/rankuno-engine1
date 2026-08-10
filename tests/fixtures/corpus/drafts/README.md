# Draft Labelling Worksheets

**These are not labels.** Nothing in this directory is ground truth, and nothing
here affects any measurement until a human has worked on it.

Each CSV holds the engine's own suggestions plus two empty columns for the real
answer. `load_reviewed_csv` admits a row into the corpus only when
`expected_level` *and* `expected_page_type` are filled in **and** `reviewed` is
set. That gate is enforced in code, not by convention — see
`src/modules/seo/page_classifier/corpus_drafts.py`.

Why it is a hard gate: scoring the engine against its own output measures
nothing. A corpus seeded from predictions would report high accuracy on exactly
the pages the engine already handles, and stay silent about the rest.

---

## Current worksheets

| File | Site | Archetype | Rows | Reviewed |
| :--- | :--- | :--- | ---: | ---: |
| `www.allbirds.com.csv` | Allbirds | `ECOMMERCE` | 120 | 0 |
| `www.vitaquest.com.csv` | VitaQuest | `FLAT_URL` | 21 | 0 |

Generated in cycle 0010 from live crawls. Rows are ordered **lowest confidence
first** — that is where review time is worth most, and the top of each file is
where the engine is guessing.

---

## How to review

1. Open the CSV. Work top-down; the hard cases are first.
2. For each row, decide the true `expected_level` and `expected_page_type` from
   [the taxonomy](../../../../src/modules/seo/page_classifier/schemas.py).
   The `suggested_*` and `signals` columns show what the engine thought and why
   — useful context, but **overrule them freely**. A worksheet where every
   expectation matches the suggestion is a worksheet nobody actually read.
3. Set `reviewed` to `y`.
4. Add a `notes` line on anything non-obvious. Future-you will dispute it.

Rows you skip stay inert. Partial review is fine and normal — `ReviewStats`
reports progress, and a half-reviewed file is more useful than an unreviewed one.

### Loading a reviewed worksheet

```python
from src.modules.seo.page_classifier.corpus import SiteArchetype
from src.modules.seo.page_classifier.corpus_drafts import load_reviewed_csv

site, stats = load_reviewed_csv(
    "tests/fixtures/corpus/drafts/www.allbirds.com.csv",
    name="allbirds",
    base_url="https://www.allbirds.com",
    archetype=SiteArchetype.ECOMMERCE,
    labelled_by="Your Name, 2026-08-07",
)
print(stats.summary_line())
```

Once a worksheet has enough reviewed rows to be worth keeping, promote it to a
`.json` file in the parent directory — that is what `load_corpus_dir` reads.

---

## Generating more

```powershell
.\.venv\Scripts\python.exe scripts\draft_labels.py https://example.com --archetype ECOMMERCE
```

Archetypes still at zero labels: `HEADLESS_SPA`, `MULTI_REGION`,
`LARGE_CATALOGUE`. See the [parent README](../README.md) for what each exercises
and why the gaps matter.
