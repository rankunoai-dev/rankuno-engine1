# ADR 0018: The upload allow-list derives from the issue catalogue, not from Screaming Frog CLI argument strings

- **Status**: Accepted
- **Date**: 2026-09-27
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`ALLOWED_BUNDLE_FILENAMES` (`upload_manifest.py`) is the hard restriction on what a
worker-uploaded zip may contain (ADR 0015 condition 9). It was derived
*mechanically* — deliberately so, to avoid a hand-typed list drifting from reality
— by taking `export_manifest.py`'s `--export-tabs` / `--bulk-export` argument
strings and applying Screaming Frog's documented naming transform (lowercase;
strip `-`, `<`, `>`, `&`; `.` → `_`; ` ` and `:` → `_`; for a nested bulk-export
argument, only the last `:`-separated segment contributes).

That chain is *catalogue filename → CLI argument spelling → transform → filename*,
and the middle step loses information. For seven files the argument string cannot
produce the filename Screaming Frog writes:

- `H1:Over X Characters`, `Meta Description:Below/Over X Pixels` and
  `Page Titles:Below/Over X Pixels` carry a literal `X` that Screaming Frog replaces
  with the **active configuration's** threshold (`70`, `400`, `985`, `200`, `561` for
  this engine's templates). The transform copied the letter, yielding
  `h1_over_x_characters.csv` — a name no export has ever contained.
- `Hreflang:Incorrect Language & Region Codes` and its "Inconsistent … Return
  Links" sibling collapse `" & "` to a single `_` in the real filename, where
  stripping `&` and mapping each space leaves a **double** underscore.

The hazard was already on record. `export_manifest.py:16-27` carries a
"Needs-verification note" from the live 2026-09-15 run stating that these filenames
embed a number rather than the placeholder word, that four of the five were never
independently run, and that a template overriding one of those settings "will
silently change these five output filenames, not error" — ending "Flagged rather
than asserted as fact". The allow-list was then derived from the flagged mechanism
anyway.

The consequence was silent, because the worker daemon applies the same list as a
**filter** with a `continue`: the seven files were dropped before the zip was
built, the upload that arrived was always valid, and seven of the 110
`ISSUE_CATALOGUE` rows reported `Coverage.NOT_MEASURED` forever. The only signal
was `WARNING sf_sources_absent` from `screaming_frog_adapter.py` on every crawl —
indistinguishable from the legitimate case of a site that has no hreflang.

## Decision

**1. `ALLOWED_BUNDLE_FILENAMES` is derived from `ISSUE_CATALOGUE`'s `sf_sources`
filenames plus the mandatory spine file.** Nothing else. `_filename_for()` and the
`EXPORT_TABS`/`BULK_EXPORT` imports are removed from `upload_manifest.py`.

The property that must hold at this boundary is "every file a deliverable reads is
admissible". Deriving from the catalogue — which is what every consumer already
asks for by name — makes "the gate refuses a file a deliverable needs"
*unrepresentable* rather than merely tested for. Deriving from the CLI argument
strings was an attempt to satisfy a different property, "every file the worker
exports is admissible", which is not computable from those strings at all.

**2. The correspondence is pinned in both directions by a test.** Every catalogue
`sf_sources` name is admitted, and every admitted name is a catalogue name or the
spine. An edit to either list that breaks the correspondence fails the gate instead
of silently dropping files at run time.

**3. Seven exact literals, never a numeric pattern.** A pattern such as
`h1_over_\d+_characters\.csv` would hand the set of admissible filenames at an
untrusted upload boundary to whoever authored the `.seospiderconfig`. The five
thresholds live in that operator-authored file, which is an opaque Java-serialised
binary this codebase cannot read (`template_registry.py`), so the literals are
maintained by hand and the hazard is documented at the definition.

**4. A skipped file is reported, never silent.** `worker_daemon._upload_bundle`
collects the names it filters out and logs
`worker_bundle_files_skipped {job_id, count, files}` at WARNING;
`worker_bundle_uploaded` carries `skipped` beside `files`. That reporting is the
whole mitigation for a future recurrence, because nothing can verify a template's
thresholds.

**5. A rejected member's name never reaches the HTTP response body.** It goes to a
debug log; the `400` names the rule.

## Alternatives considered

1. **Keep the CLI derivation and special-case the seven names.** Rejected: the
   result is the hand-maintained list the mechanical derivation existed to avoid,
   *plus* a transform, so there are two things to keep in step instead of one.
2. **Regex-match the numeric segment.** Rejected — see decision 3. The security
   boundary must not be parameterised by a file this codebase cannot read.
3. **Derive the CLI arguments from the catalogue instead** (fix the transform's
   direction). Attractive and not taken this cycle: `export_manifest.py` would have
   to synthesise argument strings, including the placeholder `X`, from filenames
   that have the number baked in, which is the same lossy step run backwards.
4. **Accept any `*.csv` and let the adapter ignore what it does not recognise.**
   Rejected: this is an untrusted upload boundary, and an arbitrary-filename walk is
   what ADR 0015 condition 9 forbids.

## Consequences

**Positive**

- Seven catalogue issue ids can be measured for the first time:
  `PAGE_TITLES_OVER_561_PIXELS`, `PAGE_TITLES_BELOW_200_PIXELS`,
  `META_DESCRIPTION_OVER_985_PIXELS`, `META_DESCRIPTION_BELOW_400_PIXELS`,
  `H1_OVER_70_CHARACTERS`, `HREFLANG_INCORRECT_LANGUAGE_REGION_CODES`,
  `HREFLANG_INCONSISTENT_LANGUAGE_REGION_RETURN_LINKS`.
- One source of truth for export filenames, and a test that keeps it that way.
- The worker now says what it dropped, so the same class of loss is visible.

**Negative**

- The allow-list is only as correct as `catalogue.py`. A catalogue typo now
  silently makes a file inadmissible, where previously a transform typo did.
- The seven threshold-bearing literals remain hand-maintained, and a
  `.seospiderconfig` that changes a threshold still breaks them silently apart from
  the new warning.
- `search_console_all.csv` and `analytics_all.csv` are still not admissible, so the
  Search Console / GA4 enrichment the masterfile services read cannot arrive through
  the worker path. This ADR does not change that; it is recorded in build-log 0108
  §6.

**Follow-up**

- Surface a non-empty `skipped` set to the cloud API, so the drift does not live
  only in a desktop worker's log.
- Confirm the four pixel filenames against a live Screaming Frog run and clear the
  `export_manifest.py:16-27` flag, or promote that flag into a failing test.
