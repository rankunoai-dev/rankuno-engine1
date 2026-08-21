# Cycle 0043: The refusal that described the wrong file

- **Date**: 2026-08-21
- **Scope**: `gsc_export.py` — what the parser says when it will not read a file.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1527 passed, 1 warning in 91.00s`, total coverage 95.83%

## 1. What happened

The first real upload against the endpoint shipped in 0042 was refused, and the
refusal was correct. The file was `rankuno.com-Coverage-2026-08-21.xlsx` — the
**Page indexing** report, not Performance. Its four sheets:

| sheet | columns |
| :--- | :--- |
| Chart | Date, Not indexed, Indexed, Impressions |
| Critical issues | Reason, Source, Validation, Pages *(counts)* |
| Non-critical issues | *(header only)* |
| Metadata | Property, Value |

Not one URL anywhere in it. There was nothing to attach.

## 2. The defect was the message, not the decision

What the operator saw:

```text
this file is not a readable Search Console page export. Upload the ZIP from
Export → CSV, the workbook from Export → Excel, or the pages CSV from inside
either one.
```

Every word of that is true, and none of it is usable. It describes **the file
the parser wanted** and says nothing about **the file it got** — so somebody
holding a perfectly valid Search Console export, downloaded from Search Console
minutes earlier, is told it is not a Search Console export. The natural next
move is to try the same file again in a different format.

It also names three ways to produce the file without ever saying **which
report**, which is the one thing that was actually wrong.

The message now names what it found:

```text
no tab in this file holds page addresses, so there is nothing to attach to the
crawl. Found: Chart, Critical issues, Non-critical issues, Metadata. That looks
like a different Search Console report — Page indexing, Sitemaps and Core Web
Vitals all export counts rather than URLs. The one with pages in it is
Performance: open Performance → search results, then Export at the top right.
```

## 3. Design decisions

**Three refusals, not one.** They answer different questions and had been
collapsed into one sentence:

* **nothing readable at all** — an empty body, a corrupt archive. Still
  "not a readable Search Console page export", because the reader has not got
  as far as columns yet.
* **tables exist and are named, none hold addresses** — name them. This is the
  wrong-report case, and listing the tabs is what lets the reader recognise it.
* **one unnamed table with no addresses** — a lone CSV, so there are no tab
  names to list. Names the column instead.

**Plain text, no markdown.** The message lands in an antd `Alert`, which renders
none. An earlier draft emphasised *Performance* with asterisks that would have
appeared literally; there is now a test asserting no `**` survives.

**Named tabs are capped at six.** A message is not a file listing.

## 4. Bugs found and fixed

**The message itself**, above.

**An empty body was about to get the wrong one of the three.** Splitting the
cases moved `_pick`'s early return, and without care an empty upload would have
been told which column should hold addresses — a question about a file that has
no columns. The `best is None` branch is now separate and explicit.

## 5. Corrections

**Cycle 0042 claimed the parser accepts "whatever Search Console produced".**
That is too broad and this cycle proves it: it accepts whatever the
**Performance** report produces, in three containers. Page indexing, Sitemaps
and Core Web Vitals are also things Search Console produces, and none of them
carry URLs to attach. The claim should have been narrower, and the refusal
should have said so from the start.

## 6. Explicitly not done

- **The Page indexing report is refused, not read.** Its "Critical issues" sheet
  is a real audit finding — 26 pages with redirects, 15 excluded by noindex, 7
  alternates with canonicals on rankuno.com — and this engine already reports on
  all three from its own crawl. Cross-checking Google's counts against ours
  would be a genuine feature and is **not** this one.
- **The report type is not detected by name.** `-Coverage-` is in that file's
  filename, and nothing reads it: the endpoint takes a body, not a filename, and
  a filename is what an operating system guessed. Content is the only evidence.
- **Still no real Performance export has been parsed.** This cycle proves the
  refusal path against a real file. The accept path remains tested only against
  files this repository generates.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/gsc_export.py` | three refusal messages, split by what the reader needs |
| `tests/modules/seo/test_gsc_export.py` | the Page indexing shape, and the split cases |
| `docs/build-log/0043-the-refusal-that-described-the-wrong-file.md` | this entry |
| `docs/build-log/README.md` | index row |

## 8. Follow-ups

1. **A real Performance export**, still. Unchanged since 0039, and now the only
   untested half of this parser.
2. Consider reading the Page indexing report as a separate cross-check against
   the engine's own redirect, noindex and canonical findings.
