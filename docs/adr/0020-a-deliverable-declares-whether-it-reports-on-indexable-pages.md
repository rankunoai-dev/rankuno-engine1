# ADR 0020: A deliverable declares whether it reports on indexable pages only; there is no default answer

- **Status**: Accepted
- **Date**: 2026-09-28
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

The 21 RAE masterfile services each read one or more Screaming Frog issue exports,
join each URL against the `internal_all.csv` spine for enrichment, and write a
styled workbook. Build-log 0104 set out the shared rules for that join, one of
which was:

> 5. **Status 200 + Indexable filter** (except Response Codes service shows all
>    status codes in affected URLs)

The rule was implemented. The exception was not. Every one of the 21 services
dropped rows whose spine `Indexability` was not exactly `"Indexable"`, including
the one the spec had already carved out.

For some services that rule cannot match a row **by construction**, because the
thing being reported on is defined by non-indexability:

* a page carrying a `noindex` directive is Non-Indexable — that *is* the finding;
* a 4xx or 5xx response is Non-Indexable — that *is* the finding;
* an inlink pointing at a broken or blocked page resolves to a Non-Indexable
  destination — that *is* the finding.

Measured against a real 24,000-page Screaming Frog 19.4 export, the filter alone
cost:

```
directives         10,309 -> 0
response_codes      7,756 -> 0
internal_links     51,965 -> 838
```

The failure mode is what makes this worth an ADR rather than a bug fix. A service
that filters everything away does not raise, does not log, and does not fail a
test: it produces a **valid, well-formed, empty workbook**, which is exactly what
a service with no matching rows on a clean site should produce. The two are
indistinguishable from the outside. Nineteen of the twenty-one service test files
asserted only `isinstance(result, bytes)` and `len(result) > 0` against an empty
temporary directory, and an empty workbook satisfies both, so this shipped green
and was declared complete twice (commit `0d26e26`, build-log 0105).

There is no version of this question a service can decline to answer. Every
masterfile joins the spine, so every masterfile either applies the filter or does
not, whether or not its author thought about it.

## Decision

**Whether a deliverable reports on indexable pages only is a declared property of
the service, stated on the class, never inferred and never left implicit.**

1. `MasterfileService` carries `INDEXABLE_ONLY: ClassVar[bool] = True`. The
   default is the conservative common case — most masterfiles are about pages a
   search engine may actually index — but the default is a *value*, not an
   absence: it is greppable, overridable in one line, and visible in the class
   body of every subclass that disagrees with it.

2. The row test is the only place the rule is applied, and it reads:

   ```python
   return not self.INDEXABLE_ONLY or indexability == "Indexable"
   ```

   No service implements its own variant. A service that needs different
   behaviour changes the declaration, not the filter.

3. **A service that sets `INDEXABLE_ONLY = False` must say why in its own
   docstring**, in terms of the finding rather than the mechanics — "a `noindex`
   page is Non-Indexable by definition", not "the filter removed the rows".

4. **The set of services that set it `False` is pinned by a test.** As of this
   ADR that set is exactly:

   | Service | Why it cannot be `True` |
   | :--- | :--- |
   | `directives` | A `noindex`/`nofollow` directive makes the page Non-Indexable; that is the report |
   | `response_codes` | A non-200 response is Non-Indexable; carved out explicitly by build-log 0104 §223 |
   | `non_functional_internal_links` | The destination of a broken or blocked inlink is Non-Indexable |
   | `overview_report` | Synthesises every other service, so it must not pre-filter what they decide |

   A fifth member cannot be added by accident. Adding one is a test change and
   therefore a reviewed decision.

5. **The flag is per service, not per issue, and that boundary is a known limit.**
   Where a single service covers issues that disagree — `pagination`, whose
   `PAGINATION_NON_INDEXABLE` issue is non-indexable by definition while its other
   five issues concern indexable pages — the service keeps `INDEXABLE_ONLY = True`
   and the affected issue reports nothing. Over-including is not preferable to
   under-including here: a workbook that silently mixes in rows the analyst did
   not ask for is harder to detect than one that is missing a section. Per-issue
   filtering is deferred until the output shape records which issue put a row in
   the sheet (build-log 0116 §6.1/§6.2).

## Alternatives considered

**A helper each service calls.** This is effectively what already existed —
`sanitize_sheet_name` shows the same pattern failing in the same subsystem: the
helper was present, correct, and had zero callers. An opt-in rule that nothing
enforces is indistinguishable from no rule.

**Infer it from the source filenames.** A service reading `*_nonindexable.csv` or
`internal_client_error_(4xx)_inlinks.csv` could be assumed not to want the filter.
Rejected: it makes a correctness-critical behaviour depend on a substring match
against a vendor's filename, which is the exact class of coupling ADR 0018 already
removed from the allow-list. It would also be silently wrong for
`overview_report`, which reads 95 files of both kinds.

**Drop the filter entirely and let each service filter explicitly.** Rejected for
the same reason as the helper — it converts a declaration into 21 opportunities to
forget — and because the filter is right for 17 of the 21.

**Raise when a service filters away 100% of its rows.** Attractive, and rejected
for now: on a genuinely clean site, or a site with no hreflang at all, zero rows
is the correct answer, so the signal would fire on correct behaviour. It is worth
revisiting as a *warning* once more than one real export has been measured.

## Consequences

* A new masterfile service cannot be written without answering the question, and
  a wrong answer is one line in a diff rather than an absence.
* `directives`, `response_codes` and `non_functional_internal_links` produce
  10,309, 7,756 and 51,965 rows respectively where they produced 0, 0 and 0
  against the same export. Correct source filenames alone would have left all
  three blank.
* Build-log 0104 §223's specification is implemented for the first time.
* `pagination` remains a known residual (condition 5), and its fix is blocked on
  the output reshape rather than on this ADR.
* The flag governs the **detail table's row filter** only. It says nothing about
  enrichment, about which files a service reads (ADR 0018 and
  `contracts/sources.py` own that), or about `NOT_MEASURED` semantics
  (ADR 0011 §5).

Implemented in `src/modules/seo/deliverables/masterfile_base.py` and the four
services named above, pinned by
`tests/modules/seo/deliverables/test_masterfile_sources.py` and
`test_masterfile_against_export.py`
[build-log 0116](../build-log/0116-three-causes-for-one-empty-workbook.md).
