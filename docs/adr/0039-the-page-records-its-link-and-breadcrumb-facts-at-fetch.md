# ADR 0039: The page records its link and breadcrumb facts at fetch

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: AI Lead, Lead AI Systems Engineer (the user approved the proposal, including
  the four stored fields and this amendment; the fifth stored field is recorded in
  "Decision" and needs the user's ratification, see "Open")
- **Amends**: [ADR 0002](0002-canonical-phase1-output-contract.md)

---

## Context

The "All URLs" workbook answered how a URL was found, but not three questions an analyst
asks about a page's place in the site:

1. **What does the page declare as its canonical, and is that a problem?** The crawl stored
   one canonical value, and the classifier fills it with the page's own URL when the page
   declares none. A reader cannot tell "declares itself" from "declares nothing", and the
   count of canonical tags (two is a defect) was never kept.
2. **How many pages link to this one from their content?** `inbound_internal_links_count`
   counts every link on every page, header and footer included. On a site with a sitewide
   menu, every page is "linked from" every other, which says nothing about content.
3. **Which page is this one's parent in the breadcrumb?** The crawl kept breadcrumb *labels*
   for tree placement, not the URL of the step a visitor came down from.

All three are facts about the body the crawl already had in hand when the page landed.
None needs a request.

## Decision

### Stored facts (on `DiscoveredNode`, `PageEvidence` and `FullPageIntelligenceProfile`)

Each defaults to `None`, which means "not recorded". A profile stored before this change
therefore reads as unknown, never as a measured zero or a measured "none".

| Field | Type | Meaning | Set |
| :--- | :--- | :--- | :--- |
| `canonical_declared` | `bool \| None` | The first canonical tag names a usable URL | `record_fetch`, for every HTML response |
| `canonical_link_count` | `int \| None` | Canonical tags with a non-empty `href` | `record_fetch`, same scan |
| `body_link_count` | `int \| None` | Outbound links whose anchor is in the body region | `record_links` |
| `breadcrumb_parent_url` | `str \| None` | URL of the last breadcrumb step before the page; `""` when read and none | `store_html`, same trail as the section labels |
| `unique_content_inlinks` | `int \| None` | Distinct source pages whose body region links here | `record_links`, incremented on the target |

`unique_content_inlinks` is a fifth field. It was not in the approved list of four. It is
needed because the export cannot compute a per-target count from the other stored values, so
the count has to be carried. It is additive and optional, and removing it would remove only
its column.

`canonical_declared` means **usable**: the first tag names a URL that survives screening.
A tag that names nothing usable is counted in `canonical_link_count` but not declared. This
departs from "present in the body" in the approved definition, for one reason. The profile
cannot hold an empty `canonical_url`, so an unusable tag would otherwise be stored as the
page's own URL and read back as "Self".

`breadcrumb_parent_url` has three states, and the report must tell them apart: `None` means
the body was never read (not fetched, or not HTML); `""` means it was read and there is no
usable parent; a URL is the parent.

### Body region

The body region is the first `<main>` element, else the first `<article>`, else the whole
document. Links are read once, by `read_page_links`, which returns the flat link list and the
body subset from the same parse. `extract_page_links` is defined as its `links`, so the flat
output cannot drift. Header, navigation and footer links are outside a `<main>` and are not
counted.

A page with neither tag counts links from the whole document, so its header and footer links
are included. The column note says so, and this is the known source of inflation.

### Unique Content Inlinks: counted, not stored as sets

For each target the count is the number of distinct source pages whose body region links to
it. `record_links` increments the target's counter once per linking page. This is exact,
because the links a page contributes are de-duplicated before they reach the graph.

The approved option named per-target source sets held during the crawl. This decision
replaces the set with a counter, because the counter gives the same answer with no set to
hold. Measured figures are in the build-log entry for this cycle.

### Derivations (export side, `report_columns.py`)

Five trailing columns, appended after the nine existing ones, in this order:
`Canonical Status | Canonical URL | Canonical Links (count) | Unique Content Inlinks | Breadcrumb Parent URL`.

- **Canonical Status**: blank when the page was not read as HTML; "Not recorded (older crawl)"
  for a profile that predates the field; "Multiple" when the count is above one (checked
  first); "Missing" when nothing usable is declared; "Self" when the declared canonical
  normalises to the page's own URL; otherwise "Elsewhere".
- **Canonical URL**: the declared canonical, blank when none is declared. Read through
  `canonical_declared`, not the stored `canonical_url`, which carries the page's own URL as a
  fallback.
- **Canonical Links (count)**: the stored count; blank where no HTML was read. A zero is a
  measured zero.
- **Unique Content Inlinks**: the stored count, blank unless this URL's own fetch outcome is
  `ok`. The approved rule. See "Open".
- **Breadcrumb Parent URL**: the stored URL; blank for `""`.

A value that is absent on a profile whose fetch outcome is recorded reads as "Not recorded
(older crawl)", because the absence then predates the field and does not mean "not measured".

The column note on Unique Content Inlinks, shown as a header comment, states the body-region
rule and the inflation for pages with neither tag.

### Breadcrumb parent rule

The parent is the last step before the page. Crumbs that name the page are removed wherever
they sit, and an unlinked final crumb is removed as the page itself. An unlinked crumb in any
other position is not guessed past: the parent is blank, not the nearest linked ancestor.

### Memory

The five fields are an int, a bool, an int, a string and an int on each node, plus the parent
URL string. The measured figures and the budget decision are in the build-log entry. The
decision is that the flat per-page charge is unchanged. The parent URL string is charged
through `retained_page_bytes`, and the rest is covered by the measured per-node overhead the
flat charge already allows for.

### Job bundle

`breadcrumb_parent_url` is a URL-named profile field, so it is classified as a site claim
(with `canonical_url`) and checked on import. The audit test requires every URL-named field
to be classified.

## Consequences

- Existing columns A to L, the PDF's twelve columns, and every other sheet are byte-stable.
  `indexability_of` is unchanged. The golden snapshot is not regenerated: the new fields are
  excluded from its projection, as earlier additive fields were, and every pre-existing field
  is byte-identical.
- The UI contract (`rankuno-ui/src/types/schema.ts`) gains the five fields on the profile and
  the node. They are nullable, so a stored profile still types.
- Link extraction makes one parse that returns two results rather than one. Its cost is the
  region tracking, which is two integer assignments per element.
- A page's body-region count is capped with its links at `MAX_LINKS_PER_PAGE`, so a body link
  beyond the cap is neither an outbound link nor a counted inlink.

## Open

- **Unique Content Inlinks is blank for a page whose own fetch was not ok.** The approved
  rule. It hides the most useful case: a 404 that content still links to is the finding, and
  it reads blank. A future decision may show the count for every fetched-or-not URL, the way
  "Unique Inlinks" does.
- **The fifth stored field** (`unique_content_inlinks`) needs the user's ratification.
- **Canonical Status compares to the page's own URL**, not its landed URL. A redirected page
  whose canonical names the redirect destination reads "Elsewhere".
- **Counts on a resumed crawl** cover only pages fetched in that run, as `Unique Inlinks`
  already does.

## Rejected alternatives

- **A set of source pages per target**, held for the crawl. The same answer at a memory cost
  that scales with body links, not with pages.
- **Stopping the change** because of the fifth field. The field is additive and optional, and
  the alternative leaves the approved column with no value to show.
- **Storing a sixth field to tell "not read" from "none" for the breadcrumb.** `""` carries the
  distinction without a new field.
