# Cycle 0044: The first real export, and the four things it broke

- **Date**: 2026-08-21
- **Scope**: `opportunity_scorer.py` hub selection and finding overlap;
  `server.py` CSV encoding.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1530 passed, 1 warning in 153.04s`, total coverage 95.84%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.84%
1530 passed, 1 warning in 153.04s (0:02:33)
PASSED: Tests
 Test Files  11 passed (11)
      Tests  101 passed (101)
PASSED: UI Component Tests
ALL GATES PASSED.
```

## 2. The finding that is not an SEO finding

A real Search Console export for **gep.com**, 1,000 rows, run against the
8,139-page crawl `1e9dfba4`. Match rate **41.5%**. The failure breakdown:

```text
by_failure : {'off_site': 569, 'not_crawled': 16, 'unparseable': 0, 'ambiguous': 0}
```

**569 of 1,000 rows are subdomains of gep.com that the crawl never covered**,
and 558 of those are two hosts:

```text
   283  smartstaging-auth.gep.com
   275  leodsaks-us.gep.com
```

Serving paths of this shape, indexed by Google with impressions against them:

```text
http://smartstaging-auth.gep.com/cop/video/<adult-keyword-spam>-138.html
http://smartstaging-auth.gep.com/tox/video/<adult-keyword-spam>-5056.html
```

Adult-content spam on a staging/auth subdomain, at scale. The unattributed
totals: **776,270 clicks and 10,822,500 impressions**, against 335,270 clicks
that reached a real page — **69.8% of the export's clicks go to URLs that are
not the website**.

This is a compromised-host signature, not an SEO defect, and the engine found it
by accident: the resolver classified those rows `off_site` and moved on. Nothing
in the product says "more than half your indexed traffic is on a subdomain you
did not crawl". It should.

**`off_site` is doing two jobs.** A different registrable domain and a subdomain
of the site being audited are not the same finding, and merging them is what
buried this. Not fixed in this cycle — it needs its own design, and this entry
exists so the next reader knows why.

## 3. Three defects in the scorer, all visible in one CSV

**Every "well-linked sibling" was a site-wide link.** The recommendation read
"a sibling in Knowledge Bank > Explore by Type > Info Guide carries 6354
internal links. Check whether that page links here." Measured:

| named as the hub | inbound | share of site |
| :--- | ---: | ---: |
| `/info-guide` | 6354 | **78.1%** |
| `/careers/join-us/campus-connect` | 6354 | **78.1%** |
| `/blog/strategy/autonomous-procurement-…` | 2953 | **36.3%** |
| `gep.com/` (homepage) | 7189 | 88.3% |
| locale switchers `/fr-fr/`, `/de-de/` | 6922 | 85.0% |

`max(inbound)` within a section selects whatever is in the header or footer. The
advice was "consider linking from the footer", with a score attached.

`SITEWIDE_LINK_SHARE = 0.2` now excludes them. Placed on measurement, not taste:
across the eight largest stored crawls the 95th percentile of inbound share is
at most **0.9%** and the 99th at most **20.6%** — content sits near zero,
navigation sits in the top one percent, and nothing sits between. Re-run on the
same data, the hubs named are now at **0.5%** and **0.2%** of the site.

**A page winning was reported as underperforming.** `gep.com/login` appeared as
an opportunity at position 5.31 — with **89,220 clicks on 589,390 impressions**,
a 15% click-through rate. That is a page answering a navigational query, not one
starved of links.

The fix needs no click-through curve, which cycle 0041 refused to invent: a page
must be converting **worse than its own section's combined rate**. The benchmark
is the client's own data.

**Seven pages were reported twice.** `buried_with_traffic` and
`underperforming_sibling` overlapped — `/careers/join-us/campus-connect/india`,
`/info-guide/understanding-purchase-order-po` and five more appeared under both.
This is the **third** pairing of this defect: 0041 fixed orphan/buried, 0042
fixed orphan/sibling, and buried/sibling was still open. Replaced with one
`reported` set covering every page-level kind, so a fourth pairing cannot exist.
Re-run on the same data: **7 → 0**.

## 4. And one in the API

**The CSV was mojibake in Excel.** The delivered file contained `EspaÃ±ol` and
`PortuguÃ©s` where the engine holds `Español` and `Portugués` — verified, the
corruption is in the download, not the crawl. Excel reads a `.csv` in the system
codepage unless a byte-order mark says otherwise, and `charset=utf-8` in the
media type never reaches it. Both CSV endpoints now emit a BOM; the
reconciliation download had the same defect and has had it since 0029.

## 5. Corrections

**Cycle 0041 said the sibling finding "stands on its own" because the
underperformance is real even if the link exists.** That was too generous to it.
On real data the finding was wrong in two further ways at once — the hub was
navigation and the page was outperforming its section — and neither was visible
in any fixture. The claim should have been that it was *untested against real
data*, which is what 0039–0043 kept saying about everything else.

## 6. Not defects, though they look like them

Recorded so a later reader does not re-investigate:

* **5,257,200 impressions on one info-guide page** is Google's own figure, from
  a single export row matched at `crawled_url`. No canonical folding or
  double-counting: `by_tier` is `{'crawled_url': 415}` and every other tier is
  zero. The implied 0.045% click-through rate at position 9.18 is odd and worth
  asking about, but it is not arithmetic this engine performed.
* **`Solutions > Solutions > Supplier Management`**, `Solutions > Register Now`,
  and `/global-presence/americas/spanish` under `Knowledge Bank > Join Us` are
  navigation-parse artefacts from the crawl, not the scorer. A CTA button read
  as a section, and a duplicated label. Pre-existing; out of scope here.

## 7. Explicitly not done

- **The subdomain finding.** §2 is reported in this log and nowhere in the
  product.
- **The navigation artefacts** in §6.
- **GA4**, connectors, and the standing gap since 0039 — although this cycle
  finally puts a real number on it: **41.5%** on one real export, against 100%
  on every synthetic one. The synthetic figures were never evidence.

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/opportunity_scorer.py` | site-wide hubs excluded; section-relative CTR; one finding per page |
| `src/api/server.py` | `_csv_response` with a BOM, both endpoints |
| `tests/modules/seo/test_opportunity_scorer.py` | three new tests; fixtures given a realistic site size |
| `docs/build-log/0044-the-first-real-export.md` | this entry |

## 9. Follow-ups

1. **Tell the client about §2.** Ahead of every other item here.
2. Split `off_site` into "another property" and "a subdomain of this site", and
   surface the second as a finding.
3. The navigation artefacts in §6.
4. A second real export, to see whether 41.5% is gep.com's property
   configuration or the resolver.
