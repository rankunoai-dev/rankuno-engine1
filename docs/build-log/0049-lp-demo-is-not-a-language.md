# Cycle 0049: `lp-demo` is not a language

- **Date**: 2026-08-21
- **Scope**: A hyphenated path segment is only a locale when one half is a real
  language. Closes follow-up 1 of cycle 0046.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1568 passed` Python / `131 passed` UI / `Total coverage: 95.75%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 51 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.75%
1568 passed, 1 warning in 129.16s (0:02:09)
PASSED: Tests
 Test Files  12 passed (12)
      Tests  131 passed (131)
PASSED: UI Component Tests
```

---

## 2. The defect was 44 tabs, not one

Cycle 0046 reported `highradius.com/lp-demo/` rendering as a language tab beside
`en-gb` and `fr`, and logged it as minor. Measuring it before fixing it showed
otherwise.

The shape rule `^[a-z]{2}[-_][a-z]{2,4}$` matched **116 distinct segments across
19,865 pages** in the stored corpus. Forty-four of them were not locales:

| Site | Fake locale tabs |
| :--- | ---: |
| postman.com | **42** |
| highradius.com | 1 (`lp-demo`) |
| backlinko.com | 1 (`ai-seo`) |

Postman publishes user workspaces at `/{slug}/{workspace}/`, and any slug of the
form `xx-yyy` was read as a language: `jd-bots`, `cv-core`, `mb-api`, `zs-zpa`,
`ho-erp`, `my-duka`, `zz-rx`. Postman's tree therefore opened with **47
"language" tabs**, five of them real.

A false positive here is not cosmetic. The segment becomes a **root**, so every
page beneath it is lifted out of the section it belongs to and presented to a
client as a language the site does not publish.

---

## 3. Design decisions

### 3.1 One half must be a language — either half

`jp-ja` (132 pages on gep.com) and `hk-zh` (infosys.com) put the **region
first**. A rule requiring the left half to be a language — the obvious
implementation — would have deleted both from their locale roots while fixing
Postman. The check is `left or right`.

### 3.2 The project's narrow language list is the right one, and this proves it

`_ISO_639_1` holds 39 common codes rather than the full 184. Under the full ISO
list, ten of the 44 would have survived as fake locales, because their first two
letters are genuine but rare language codes:

```
ka-kkk   (ka = Georgian)    →  postman.com/ka-kkk/kakkk-blog/
my-duka  (my = Burmese)     →  postman.com/my-duka/crud-node-express/
su-lab   (su = Sundanese)   →  postman.com/su-lab/bluesky-api/
ti-jmd   (ti = Tigrinya)    →  postman.com/ti-jmd/e-rede/
om-sai   (om = Oromo)       →  postman.com/om-sai/my-workplace/
yi-api, ia-jmj, oc-tech, sg-intl, ku-ndpx
```

Every one is a workspace slug. The narrow list was written for the bare-segment
case and turns out to carry the hyphenated case as well.

### 3.3 `it` and `hr` are eligible hyphenated and nowhere else

Both are omitted from `_ISO_639_1` because a bare `/it/` is IT services and
`/hr/` is human resources far more often than Italian or Croatian. Hyphenated,
the ambiguity is gone — `it-it` (210 pages) and `it-hr` (48) are locales — so
`_REGIONAL_LANGUAGES` is `_ISO_639_1 | {it, hr}` and is used only by the
hyphenated check.

### 3.4 Fixed in both implementations

`url_rules.is_locale_segment` (Python) and `navTree.localeOf` (TypeScript) carry
the same rule for different jobs — stripping locales in the crawler, and
grouping tabs in the browser. The Python copy matters more than the reported
symptom suggested: `strip_locale_prefix` feeds `depth_of`, so `/lp-demo/x` was
being measured one segment shallower than it is.

They cannot share a module, so they are pinned by **matching test classes** —
`TestRegionalLocaleShape` and the `localeOf` suite assert the same segments.

---

## 4. Bugs found and fixed

**The reported bug, and 43 more instances of it.** See §2.

**A test that could not fail.** `TestRegionalLocaleShape` first raised
`NameError: is_locale_segment is not defined` — the function was never imported
into `test_url_rules.py`, because nothing had tested it directly before. Five
assertions in the class had been "passing" as errors until the import was added.
Worth recording: a `NameError` in a test reads as a failure only if someone
looks at the reason rather than the count.

---

## 5. Corrections

**Cycle 0046 §4 called this "a minor regex bug" affecting `lp-demo`.** Measured,
it is 44 segments across three sites, 42 of them on one. The claim that it was
minor was made from a single observed instance without counting the others, and
it was wrong.

**Cycle 0046 §4 also said the fix "changes which tabs a stored crawl
produces".** True, and now measured: postman.com goes from 47 locale tabs to 5.
No real locale is lost — all 44 removed segments were inspected individually,
and every one resolves to a workspace, a landing page or a blog category.

---

## 6. Explicitly not done

- **The panel/visualizer section mismatch is untouched.** Cycle 0046 §3
  established that the recommendations panel understates every business section
  on a multilingual site — 26% of highradius.com's pages are localised and land
  under `Home`, `EN` and `Accueil` rather than under their business section.
  That is the larger of the two findings and it is still open by decision, not
  by oversight.
- **`Home` and `HOME` are still two sections** on gep.com. Also still open.
- **`cs-demo` (57 pages) is still treated as a locale**, because `cs` is Czech
  and nothing in the segment contradicts it. Asserted by test so the behaviour
  is a decision on the record rather than an accident.
- **Stored `.jobs/` results are not rewritten.** The tree groups client-side, so
  the corrected tabs appear on any stored crawl as soon as it is reloaded — no
  re-crawl. The Python half only affects crawls run from now on.
- **No region-code list.** Validating the *other* half against ISO 3166 would
  catch `cs-demo`, and would fail on the first site using a region this project
  has not seen. The language check is the half that can be closed.

---

## 7. Files changed

```
src/modules/seo/page_classifier/url_rules.py   _REGIONAL_LANGUAGES,
                                               _is_regional_locale
rankuno-ui/src/lib/navTree.ts                  REGIONAL_LANGUAGES,
                                               isRegionalLocale
tests/modules/seo/test_url_rules.py            +24 (TestRegionalLocaleShape),
                                               is_locale_segment imported
rankuno-ui/src/lib/navTree.test.ts             new — 23 tests
```

---

## 8. Follow-ups

1. **The panel's locale grouping** (§6). The open item that moves numbers in a
   client report.
2. **Case-fold section labels** so `Home` and `HOME` are one section.
3. **A shared locale fixture** across the Python and TypeScript suites, so the
   two implementations cannot drift without a test naming the segment that
   differs.
