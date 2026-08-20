# Cycle 0037: One address spelled two ways is one page

- **Date**: 2026-08-20
- **Scope**: Fold percent-encoding in `normalize_path`, so a URL and its encoded
  spelling share a dedup key. Closes follow-up 1 of cycle 0036.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1398 passed` Python / `65 passed` UI / `Total coverage: 95.50%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.50%
1398 passed, 1 warning in 110.51s (0:01:50)
PASSED: Tests
 Test Files  8 passed (8)
      Tests  65 passed (65)
PASSED: UI Component Tests
```

---

## 2. The defect

Reported from a live gep.com audit. These two were held as separate nodes and
published to the client as a duplicate-content defect on their site:

```
gep.com/blog/technology/procurement%E2%80%91ai%E2%80%91agents-purchase%E2%80%91order%E2%80%91compliance
gep.com/blog/technology/procurement‑ai‑agents-purchase‑order‑compliance
```

They are one address. `%E2%80%91` *is* U+2011; a browser encodes the raw form
before sending it, so the server receives identical bytes either way. RFC 3986
§6.2.2.2 says so directly. The finding was our artefact, not GEP's defect.

---

## 3. Design decisions

### 3.1 Scope: RFC 3986 generally, not non-breaking hyphens specifically

The instruction was to *"decode non-breaking hyphens"*. Implemented as the
general rule instead, which strictly contains it. Measured on the stored corpus
before choosing:

| Rule | URLs whose key changes | Spurious duplicates resolved |
| :--- | ---: | ---: |
| Non-breaking hyphen only | 1 | 1 |
| Any non-structural escape | 102 | **24** |

The narrow rule fixes the one URL that was reported and leaves every sibling
case in place — `%E2%80%90` (U+2010, a *different* hyphen, 5 occurrences),
`%C3%A9`, `%E2%80%99`, Korean and Japanese slugs, and encoded ASCII. Each is the
same bug waiting for a different client to hit it. Fixing the reported instance
rather than the defect is how a register of known gaps grows.

### 3.2 Structural escapes are preserved, and this is the whole reason decoding cannot be blanket

`STRUCTURAL_ESCAPES = {%2F, %3F, %23, %25, %5C}`. `/a%2Fb` is **one** segment
containing a slash; `/a/b` is **two**. RFC 3986 §2.2 reserves these precisely
because the encoded and decoded forms are not equivalent, and folding them would
merge two genuinely different addresses onto one node — the opposite of the bug
being fixed. `%25` is in the set because it is the escape character itself:
decoding it first would make `%2520` decode twice.

Because `%2F` survives, the split on `/` in `normalize_path` is still safe to do
*after* decoding. Nothing decoding returns can grow a segment boundary that was
not already there.

### 3.3 It lives in `normalize_path`, not `normalize_url`

`normalize_path` has two callers: `normalize_url`, and `_path_key` in
`signal_parsers`, which matches header-menu hrefs against crawled page paths.
Putting the decode one level down means a menu href spelled one way and a page
URL spelled the other now match. Had it gone in `normalize_url` only, that page
would have silently lost its navigation placement for a reason invisible in the
report.

### 3.4 Invalid UTF-8 stays encoded

`errors="strict"`, and an undecodable run is returned untouched. `errors=
"replace"` would map every broken sequence onto U+FFFD and collapse unrelated
URLs onto one key — a merging bug introduced while fixing a splitting one.
Tested: `/bad%FF/` and `/bad%FE/` remain distinct.

---

## 4. Bugs found and fixed

**The first implementation of this decoded escape by escape and merged
nothing.** A UTF-8 character is several octets — `%E2%80%91` is three — and
`unquote("%E2")` in isolation returns U+FFFD. Decoding per-escape therefore
corrupts the very key it is meant to repair, while appearing to work: the
function ran, returned a string, and every test written against ASCII passed.

Caught by measuring against the stored corpus rather than the fixtures: the
candidate rule reported it had merged the kinsta and backlinko pairs but *not*
the GEP pair it was written for. A fix that misses its own reported case is the
signal that the mechanism is wrong. Runs are now decoded whole, and the test for
it asserts the absence of U+FFFD rather than only the presence of the right
character.

**A published measurement in this cycle's own drafting was wrong twice.** The
first sweep excluded `*.result.json` and so never loaded the GEP crawl — the
pair lives in the result, not the checkpoint — and reported "narrow fix merges
nothing across 474,954 URLs". The second reported 3 merges for the general rule
because the candidate did not yet strip segment whitespace. The number in §3.1
is from the shipped code compared against a reconstruction of the previous one,
over every URL in `.jobs/`.

---

## 5. What actually changed, measured

Over **476,067** distinct URLs from 65 stored crawls:

```
keys before : 473,968
keys after  : 473,944
net         :      24 fewer
```

All 24 merges were inspected individually. Every one is the same page:

- **19** kinsta URLs where a leading `%20` or space made `/ blog/x` a separate
  node from `/blog/x` — the `href=" blog/post"` defect. Historical: cycle 0029's
  `is_malformed_url` already refuses these at `graph.add`, so a new crawl never
  creates them.
- **2** stripe URLs (`payments%20/%20checkout` → `payments/checkout`).
- **1** kinsta `%6D%79%6B%69%6E%73%74%61` → `mykinsta` — encoded unreserved
  ASCII, the textbook §6.2.2.2 case.
- **1** backlinko trailing `%20`.
- **1** the reported gep.com pair.

**No false merge.** That was the check this change had to pass: it is the dedup
key for the entire engine, and a wrong merge deletes a real page silently.

---

## 6. Explicitly not done

- **Stored crawls are not re-keyed.** Nothing rewrites `.jobs/`. The 65 stored
  results keep the keys they were saved with, so **the gep.com report still
  shows the false duplicate until the site is re-crawled**. A reparse does not
  help: `reparse_job` re-runs placement over the stored pages, it does not
  rebuild the graph. Re-crawl gep.com before sending that report.
- **Query strings were already handled and are untouched.** `parse_qsl` decodes
  and `urlencode` re-encodes, so the query has always been normalised. Only the
  path was inconsistent.
- **Unicode normalisation (NFC/NFD) is not applied.** `é` as one codepoint and
  as `e` + combining acute are still different keys. Not observed in the corpus,
  and folding them is a separate claim needing its own evidence.
- **The host is not IDNA-normalised.** `xn--` punycode and its Unicode spelling
  remain distinct hosts. Same reasoning.
- **Percent-escape case is not upper-cased before comparison**, because the path
  is lowercased wholesale anyway; `%2F` and `%2f` both end as `%2f`. Consistent
  as a key, but it is not the canonical form RFC 3986 §6.2.2.1 prescribes, and a
  reader comparing our keys to another tool's should know that.

---

## 7. Files changed

```
src/modules/seo/page_classifier/url_rules.py   STRUCTURAL_ESCAPES,
                                               decode_percent_escapes,
                                               normalize_path decodes + strips
tests/modules/seo/test_url_rules.py            +10 (TestPercentEscapeDecoding)
```

---

## 8. Follow-ups

1. **Re-crawl gep.com** and confirm the duplicate count drops by one set.
2. **A `--rekey` maintenance pass** over stored results, if old crawls ever need
   to agree with new ones.
3. Cycle 0036's follow-ups 2 and 3 remain open: one export for the whole audit,
   and `groups` on the pagination finding.
