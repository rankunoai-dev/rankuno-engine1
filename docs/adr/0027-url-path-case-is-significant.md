# ADR 0027: URL path case is significant in the engine's page identity

- **Status**: Accepted
- **Date**: 2026-09-30
- **Deciders**: User (Gaurav Doshi), Lead AI Systems Engineer
- **Note**: Number chosen as next free on branch `fix-path-case`; may be renumbered at merge.

---

## Context

`normalize_url` is the engine's page identity: `SiteGraph.add` keys nodes on it, and audit
export, breadcrumb and hierarchy placement, the Screaming Frog merge and Search Console
resolution all compare on it. Its path step, `normalize_path`, lowercased every segment. That
had been the case since the first commit (`ba6f1b8`), with no recorded reason.

RFC 3986 §6.2.2.1 makes only the scheme and host case-insensitive. The path is not, and on a
case-sensitive server `/A` and `/a` are different resources. Google indexes them as two URLs, and
Screaming Frog crawls them as two. The engine merged them into one graph node, so one page's HTML,
classification and discovery reason were shown for both, and page counts were low.

Build-log 0079 had recorded the opposite as intended. Two test fixtures collided because
`/Blog/` and `/blog/` shared a key. The entry ruled "the code was right; the fixture was wrong"
and pinned the collapse as "a documented feature". That ruling described the behaviour that
already existed. It gave no evidence from a real site that merging case variants was the lesser
harm.

## Decision

The user chose to keep path case.

1. `normalize_path` no longer lowercases. Scheme and host are still lowercased, `www.` is still
   folded, and the query, fragment, slash and percent-decoding rules (build-log 0037) are
   unchanged.
2. The percent-escapes that survive decoding (structural or not valid UTF-8) now have their
   hex digits upper-cased. Before, the path-wide lowercasing made `%2f` and `%2F` one key; without
   this step they would become two.
3. Search Console and GA4 resolution (`performance/url_identity.py`) keep their case-blind
   matching, but only as an explicit fallback reported under `MatchTier.CASE_FOLDED`:
   - At each level (absolute URL, path with query, bare path) an exact case-preserving lookup
     is tried first, so an exact spelling always wins.
   - The folded index applies the same ambiguity rule as the other tiers. If two crawled pages
     differ only by case, a Google row that matches neither spelling exactly resolves to
     `MatchFailure.AMBIGUOUS`. It is not given to either page.
4. The build-log 0079 fixture ruling is reversed. Duplicates that really are the same page
   (scheme, `www.`, slashes, tracking parameters) still collapse. Case variants stay two pages.
   `URL_UPPERCASE` is still detected from the raw URL.

## Consequences

- A new crawl of a site that links the same path in mixed case will report **more pages** than
  an older crawl of the same site, and will spend more of the page budget. Counts across this
  change are not comparable for such sites.
- Stored crawls are not migrated. Search Console resolution and `dedupe_profiles` recompute the
  key from the raw stored URL, so old results re-key under the new rule when read. Checkpoints
  hold URLs only and are never resumed, so nothing there has to match.
- A site that serves one page under several casings without redirecting will now show them as
  separate pages. That matches what Screaming Frog and Google report, and it is a real
  duplicate-content finding.
- `src/integrations/gsc_property_validator.py` still lowercases the whole property URL,
  path included. This ADR does not change it.
