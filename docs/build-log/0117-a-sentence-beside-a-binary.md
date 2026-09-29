# Cycle 0117: A sentence beside a binary — the half of config upload that could be built

- **Date**: 2026-09-28
- **Scope**: A human-authored description travels worker → cloud → browser for each Screaming Frog
  config template; unrecognised config filenames stop vanishing in silence.
- **Commit**: `94894ce` (code); this entry and its documentation updates are a follow-up commit
- **Quality gate**: `ALL GATES PASSED.` — 3368 passed, 2 skipped in 364.88s, 92.74% against an
  unchanged 85% floor; UI 43 files / 533 tests

---

## 0. What this cycle is, and what it deliberately is not

The request was for RAE's config-upload UI: a file picker that moves a `.seospiderconfig` from a
browser onto a worker desktop, with a description field beside it.

A Step 5 security audit returned **DO NOT SHIP** on the upload half, for two structural reasons
rather than two fixable ones:

1. A `.seospiderconfig` is a Java `ObjectInputStream`-serialised blob.
   `template_registry.py:1-14` already states that this codebase cannot author one, validate its
   contents, or inspect them. ADR 0015 condition 8 makes worker-side re-validation of anything the
   cloud hands a worker load-bearing — and for a file whose format this system cannot parse, that
   re-validation is not merely unimplemented, it is impossible to write.
2. `Principal` (`src/core/auth.py`) has no role field. "Only an admin may upload a config" is not a
   policy this codebase can currently express, so the mitigation that would narrow the blast radius
   is unavailable too.

The audit's recommended ladder was:

| Rung | What it is | State |
| :--- | :--- | :--- |
| 1 | Descriptions on the templates workers already report | **This cycle** |
| 2 | An operator-vetted, hash-pinned allow-list of configs | Not built |
| 3 | Upload to quarantine, with an explicit human release step | Not built |

Rung 1 delivers precisely what RAE's own help text says the upload panel's description field is
for:

> Config files are binary, so their custom extraction rules cannot be read back on the server. Note
> them here so the next person knows what this config captures.

Verifiable properties of the refusal, stated so they can be re-checked rather than re-argued:

* No upload endpoint was added. `git show 94894ce --stat` lists no new route module.
* No engine → worker byte channel exists. The daemon still only polls.
* The dispatch envelope chain — `DispatchPreviewRequest` → `DispatchPreviewToken` →
  `DispatchAssignmentClaims` → `WorkerJobEnvelope` → `ScreamingFrogJobInput` — is byte-identical.
  `git show 94894ce -- src/core/worker_dispatch_signing.py src/core/worker_dispatch.py` returns
  empty. There is therefore **no HMAC implication** and gate (b) is untouched.

The reasoning above is the single most likely thing in this project to be lost and re-argued —
someone will see RAE's screenshot in six months and simply build the file picker — so it is also
recorded as [ADR 0021](../adr/0021-no-binary-config-upload-to-a-worker.md).

---

## 1. Gate results

Run by the implementing agent at `94894ce`, and independently re-run by the scribe on the same
commit with a clean tree (see §1.1).

```
PASSED: Format / PASSED: Lint / PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 92.74%
3368 passed, 2 skipped, 1 warning in 364.88s
Test Files 43 passed (43)   Tests 533 passed (533)
ALL GATES PASSED.
```

| Figure | Prior cycle (0116) | This cycle | Delta |
| :--- | ---: | ---: | ---: |
| Python tests passed | 3,327 | 3,368 | +41 |
| Python skipped | 2 | 2 | 0 |
| UI tests passed | 530 | 533 | +3 |
| Coverage | 92.72% | 92.74% | +0.02 pp |
| Coverage floor | 85% | 85% | unchanged |

### 1.1 What the scribe verified independently

Re-read from the committed tree rather than taken on report:

| Claim | How checked | Result |
| :--- | :--- | :--- |
| Sidecar is `<name>.md`, read as bytes, 16 KiB cap | `template_registry.py` `_MAX_SIDECAR_BYTES`, `_describe()` | Confirmed |
| Truncated, not dropped, and logged | `sf_template_description_truncated` warning | Confirmed |
| Nothing renders the sidecar as Markdown | No Markdown import anywhere in the module; UI renders a text node | Confirmed |
| `grep -rn dangerouslySetInnerHTML rankuno-ui/src` | Run by the scribe | **0** matches |
| Envelope chain unchanged | `git show 94894ce -- src/core/worker_dispatch_signing.py src/core/worker_dispatch.py` | Empty diff |
| `Dockerfile` and `railway.toml` exist | `ls` at repo root | Both present — see §5.1 |
| Migration 0005 sits on head 0004 | `revision = "005"`, `down_revision = "004"` | Confirmed |
| Named tests exist | `grep -rn` in `tests/` | Both found (§4.2, §3.1) |
| Over-400-line files | `wc -l` before and after | See §6.4 — one figure corrected |

---

## 2. What landed

### 2.1 `src/core/worker_templates.py` (new, 182 lines)

The value objects a worker reports about its own template directory: `WorkerTemplate`
(`name` + `description`), `WorkerTemplateReport` (`templates` + `unrecognised_count`), the
`TemplateDescription` annotated type, `normalise_description()`, and the three constants
`TEMPLATE_NAME_PATTERN`, `MAX_REPORTED_TEMPLATES` (200), `MAX_TEMPLATE_DESCRIPTION_CHARS` (500).

Split out of `worker_auth.py` rather than added to it because three layers that have no business
importing worker *identity* need these types: the HTTP wire models (`api/worker_schemas.py`), the
daemon-side registry (`screaming_frog_control/template_registry.py`), and the persistence
(`core/postgres_worker_store.py`). A shared value object with no dependency on password hashing is
the honest home. Size was the secondary reason — `worker_auth.py` was already at the 400-line
target.

### 2.2 `template_registry.py` — `scan()` replaces a silent filter

`list_templates()` now delegates to a new `scan() -> TemplateScan`, which returns `templates` **and**
`unrecognised`. `TEMPLATE_NAME_PATTERN` is unchanged (`^[a-z0-9_-]{1,128}$`); what changed is that
the files it refuses are now reported instead of dropped.

`_describe(name)` reads the sidecar. The rules, all tested:

| Rule | Behaviour |
| :--- | :--- |
| Read size | At most 16 KiB (`_MAX_SIDECAR_BYTES`), so a sidecar pointed at a 2 GB file cannot be pulled into memory |
| Decode | UTF-8 with `errors="replace"` |
| Whitespace | Every run collapsed to one space, ends stripped |
| Hostile characters | Control, zero-width and bidi-override characters **stripped** worker-side |
| Over 500 chars | **Truncated, not dropped**, and logged `sf_template_description_truncated` |
| Missing sidecar | `""`, not logged — most templates will never have one, and a line per template per scan buries the ones that matter |
| Unreadable sidecar | `""`, logged `sf_template_description_unreadable` with the template name only |
| No description at all | The UI renders **nothing** — not an empty element. Pinned on both sides |

### 2.3 The heartbeat, the store, and the dashboard

`WorkerTemplateReport` is now the heartbeat body. `Worker` (`core/worker_auth.py`) carries
`templates` and `unrecognised_template_count`. `PostgresWorkerStore` serialises through Pydantic
(`_templates_json`) rather than by hand, so a future field on `WorkerTemplate` persists without
anyone remembering to edit the store, and re-validates every row through
`WorkerTemplate.model_validate` on the way out — even a row written by some other process cannot
reintroduce a bad name or a bidi override.

`ScreamingFrogView.tsx` renders the chosen template's description beneath the `Select`, looked up
from the list rather than stored alongside the selection: the list is re-read on every machine
change, and a stale copy of a description is a description of a different config.

### 2.4 `alembic/versions/0005_worker_template_descriptions.py` (new, head `004`)

Three changes on `workers`:

* `template_names` → `templates`, with the JSON array of strings rewritten **in place** as
  `{"name", "description"}` objects via
  `json_agg(json_build_object('name', entry.value, 'description', ''))`.
* `COALESCE(..., '[]')` around that aggregate. Without it, `json_agg` over an empty array returns
  `NULL`, and every worker that had reported no templates would land a `NULL` in a `NOT NULL`
  column.
* `unrecognised_template_count INTEGER NOT NULL DEFAULT 0` — "no report yet" and "nothing skipped"
  want the same, non-alarming rendering.

**The rename is deliberate, not cosmetic.** A column still called `template_names` holding objects
is how the next person writes a wrong query. Downgrade is lossy by nature (descriptions are
dropped; the column they go back into has no room for them) and the docstring says so rather than
leaving it to be discovered.

---

## 3. Design decisions

### 3.1 A sidecar `<name>.md` per template, not a shared `descriptions.json`

The blast radii are not comparable. One unparseable JSON file blanks **every** description at once;
a missing, empty or unreadable `.md` costs exactly the template it belongs to. That is pinned by
`tests/modules/seo/screaming_frog_control/test_template_registry.py:95`
`test_an_unreadable_sidecar_costs_only_its_own_description`.

Three supporting reasons:

* The author is an operator in a folder, not a developer in an editor. Prose in a text file needs no
  escaping, quoting or comma discipline.
* A template stays atomic: adding one is two files copied in, with nothing shared to remember to
  edit.
* The sidecar path derives from a stem that has **already** passed `TEMPLATE_NAME_PATTERN`, so it
  opens no path surface the config file did not already open.

**The file is read as plain text; nothing renders it as Markdown.** The extension exists only to
signal "prose goes here" to the human writing it. If a later cycle wants Markdown rendering, that is
a new decision with its own injection surface, not an implication of the filename.

### 3.2 Only the count of unrecognised files crosses the network

The unrecognised set is surfaced at four layers, and deliberately not identically:

| Layer | What it carries | Why |
| :--- | :--- | :--- |
| Worker log (`sf_template_files_unrecognised`, WARNING) | The filenames | This is the only machine where a human can rename them, and renaming is the fix |
| Heartbeat | The count only | See below |
| `workers.unrecognised_template_count` | The count | Stored so the dashboard need not re-ask |
| UI hint | The count, plus what to do | Answers "why is this dropdown empty when the folder is full" |

**Why only the count crosses the network.** A filename here is arbitrary text from outside the trust
boundary that this engine did not choose, and it can carry a client's name — `Manulife
JS.seospiderconfig` is the realistic case, not a contrived one. A count answers the operator's
actual question ("are files being skipped?") without republishing a client identifier into a
different org's dashboard, a log aggregator, or a screenshot.

---

## 4. Bugs found and fixed

### 4.1 A clamp the old code never had: 201 templates reported as zero

A desktop holding more than 200 templates built a heartbeat body the cloud rejected **whole** with a
422, because `MAX_REPORTED_TEMPLATES` was enforced only at the wire. The worker therefore reported
**zero** templates rather than 200 — a silently short list, which is precisely the failure this
whole cycle exists to remove, arriving by a different route.

`worker_daemon.py` now clamps both halves of the report *before* sending and logs
`worker_templates_report_clamped` with `found` and `reported`:

```python
kept = scan.templates[:MAX_REPORTED_TEMPLATES]
if len(scan.templates) > len(kept):
    _logger.warning(
        "worker_templates_report_clamped",
        extra={"found": len(scan.templates), "reported": len(kept)},
    )
```

This is a pre-existing bug, not one introduced this cycle. It was unreachable in practice only
because no desk has held 200 configs yet.

### 4.2 `normalise_description` spliced words together — caught by the implementer's own test

The first implementation stripped control characters **before** collapsing whitespace. Newlines and
tabs **are** C0 controls, so a two-line sidecar note came out as:

```
"line oneline two"
```

Words fused at the line break. The fix is an ordering, and it is now load-bearing rather than
incidental, so the docstring says so:

```python
return _FORBIDDEN_DESCRIPTION_CHARS.sub("", _WHITESPACE_RUN.sub(" ", value)).strip()
```

> Whitespace is collapsed *first*, and the order is load-bearing: newlines and tabs are themselves
> C0 controls, so deleting the forbidden set first would splice a two-line note into one word.

This is the best illustration in the entry of why the feature needed tests rather than review. The
defect produces valid-looking output — a string, of plausible length, with no error and no log line.
A description field would have shipped with it silently and the corruption would have been read as
the operator's own typo.

### 4.3 Pydantic `pattern=` could not express the constraint safely

The forbidden-character rule was first written as a Pydantic `pattern=`. It cannot be, for a reason
worth recording because it will come up again:

* `^...$` matches a string with a **trailing newline** in both Python's `re` and the Rust `regex`
  engine Pydantic hands `pattern=` to. A description ending in `\n` would pass a `^[^\x00-\x1f]*$`
  check that was meant to reject it.
* The portable fix, `\A`/`\z`, is not portable between those two engines: Python's `re` rejects
  `\z`, and older Rust `regex` rejects `\Z`. There is no spelling that is correct in both.

A compiled Python pattern behind an `AfterValidator` is used instead, and it searches for what is
**forbidden** rather than asserting the shape of what is allowed — a `search` has no anchoring edge
case at all.

Note that `WorkerTemplate.name` still uses `Field(pattern=TEMPLATE_NAME_PATTERN)`. That is safe for
a different reason: `[a-z0-9_-]` excludes `\n`, so the trailing-newline hole cannot be reached.

---

## 5. Corrections

### 5.1 `CLAUDE.md` §8 claims there is no Dockerfile. Both it and `railway.toml` exist

`CLAUDE.md` §8 currently states:

> - No `Dockerfile`; Railway deployment deferred per ADR 0004.

Verified false by the scribe at `94894ce` with a clean tree:

```
$ ls Dockerfile railway.toml
Dockerfile
railway.toml
```

Both are at the repository root, and the project is actively deploying to Railway — build-log 0099
records serving the compiled React UI from FastAPI specifically so a Railway container has something
to serve, and un-ignoring `!rankuno-ui/dist` in the Docker build.

`CLAUDE.md` was **not edited by this cycle**: no agent message is authorisation to change it. The
exact replacement text is handed to the lead in the scribe's report, and follows the precedent set
in build-log 0110, which recorded the same class of error for §8's false
"`circuit_breaker.py` — does not exist".

This is the second known-wrong line in §8 found in eight cycles. §8 exists to prevent drift and is
itself drifting.

### 5.2 README's ADR 0015 row describes a template-reporting contract that has changed

`README.md:145` says, of per-worker template reporting:

> a worker is untrusted input; names are pattern- and count-checked server-side

Still true, and still the design stance — but it describes a payload of bare names. As of this
cycle the heartbeat carries objects, and the checks include description content, not just names and
count. The row is left intact and a new row records the change (§7).

---

## 6. Explicitly not done

### 6.1 Nothing populates the template directory

Saving a `.seospiderconfig` remains a one-time operator action inside the real Screaming Frog GUI
(File > Configuration > Save As), exactly as `template_registry.py`'s own module docstring has said
since it was written. This cycle describes templates; it does not create them.

Related and worth stating because it will look like a regression: **the user's template folder was
lost and was never tracked in git.** There is no commit to restore it from. Re-populating it is
manual work in the GUI on the machine that needs it.

### 6.2 Rungs 2 and 3 of the security ladder

No hash-pinned allow-list, and no upload-to-quarantine. See §0 and ADR 0021 for what each would
require before it could be built — rung 3 in particular is blocked on `Principal` gaining a role
field, not merely unscheduled.

### 6.3 `WorkerSummary.templates` ships every description on a list endpoint

`GET /workers` now carries every template description for every worker in the org. Bounded at
200 templates × 500 chars per worker, which is fine at the present fleet size and is the first thing
to trim if the fleet grows — most likely by dropping descriptions from the list view and leaving
them on `GET /workers/{id}/templates`, which the UI already calls on selection. Not done now
because the fallback path in `ScreamingFrogView.tsx` reads them from the summary when
`getWorkerTemplates` is absent.

### 6.4 Three files remain over the 400-line target

All three were already over it before this cycle. None was made worse than necessary; none was
split, because splitting any of them is a refactor with its own risk and belongs in its own change.

| File | Before | After |
| :--- | ---: | ---: |
| `src/core/worker_auth.py` | 434 | 442 |
| `rankuno-ui/src/components/screaming-frog/ScreamingFrogView.tsx` | 520 | 555 |
| `src/modules/seo/screaming_frog_control/worker_daemon.py` | 465 | 492 |

`worker_auth.py` grew by 8 lines *despite* `MAX_REPORTED_TEMPLATES`, `TEMPLATE_NAME_PATTERN` and the
template models being moved **out** of it into `worker_templates.py` — the re-export block and the
expanded `Worker` docstring cost more than the constants saved. Worth naming so nobody assumes the
extraction failed to do anything.

---

## 7. Security — Step 5 summary

Eight questions answered. The finding that drove the design: the description is
**attacker-controlled text crossing from outside the trust boundary into an operator's browser**. A
worker daemon is a machine on someone's desk. It is authenticated, but authentication is not trust.

### 7.1 The control worth recording in full: bidi overrides are refused, not stripped

`U+202A`–`U+202E` and `U+2066`–`U+2069` are **refused** at every trust boundary — the HTTP wire
model, `Worker` before persistence, and again on read back out of Postgres. The reasoning:

> React escapes HTML for us; nothing escapes a right-to-left override.

An escaped, perfectly inert text node containing `U+202E` still **renders as a string it does not
contain**. That makes a template label a forgery surface that no amount of HTML escaping touches,
which is why this class is handled by refusal rather than left to the renderer. Zero-width
characters are in the same set for the same reason (hiding content inside a short-looking label), as
are C0/C1 controls (corrupting a log line).

Worker-side the identical character set is **stripped** rather than refused. That asymmetry is
deliberate: one author's stray tab must not 422 the whole heartbeat and take every *other*
template's description down with it. The cloud-side validator remains the authority; the worker-side
normaliser is a courtesy to a well-meaning author, not a defence against a hostile one.

### 7.2 The rest

| Question | Answer |
| :--- | :--- |
| Length | Capped at three boundaries: HTTP request model, `Worker` before persistence, and on read back out of Postgres |
| Rendering | Text node only. `grep -rn dangerouslySetInnerHTML rankuno-ui/src` → **0** before and after |
| Logs | Never interpolated unescaped. Unrecognised filenames are normalised and clamped to 128 chars before logging |
| Error messages | The validator message names the character *class*, never the value |
| Unreadable sidecar | The `OSError` text is deliberately **discarded** — it embeds a filesystem path this process has no reason to republish |
| Path traversal | The sidecar stem has already passed `TEMPLATE_NAME_PATTERN`; no new path surface |
| Cost | $0.00. No new host, no `rate_limit_key`, no `CostLedger` entry, no `RiskClass` change |
| DoS | 16 KiB read cap per sidecar; 200 templates per worker; 500 chars per description; ≈130 KB bounded heartbeat body |

### 7.3 Residual risk, stated rather than hidden

Pydantic's `ValidationError` string carries `input_value=`, and FastAPI's 422 response body echoes
it. A refused description is therefore reflected back in the rejection. This is accepted because
that response goes **only to the worker that sent it** — the party that already holds the value —
and never to an operator browser. Pinned by
`tests/core/test_worker_templates.py:56`
`test_the_rejection_message_names_the_problem_and_not_the_value`, which asserts the message this
codebase *authors* names the problem class and not the value.

---

## 8. Breaking change: an un-upgraded daemon's heartbeat now gets a 422

**This is the one thing in this entry that can affect a running deployment.**

The heartbeat wire shape changed:

```
before   {"template_names": ["basic", "js-render"]}
after    {"templates": [{"name": "basic", "description": "..."}], "unrecognised_count": 0}
```

`StrictModel` sets `extra="forbid"`, so an old daemon sending `template_names` is refused with a
**422**.

What that does and does not cost:

| Still works | Stops working |
| :--- | :--- |
| Polling for jobs | The reported template list stops refreshing |
| Claiming a job | — |
| Running a crawl | — |
| Uploading a bundle | — |
| Reporting progress | — |
| Liveness / `is_online` | — |

The stored list is *not* wiped — `COALESCE(%s, templates)` in the store means a poll that reports
nothing does not clear what a heartbeat reported earlier. The list simply goes stale, showing the
last thing that desktop successfully said, until the daemon on that machine is updated.

Accepting both shapes indefinitely was the alternative and was rejected: the daemon ships from this
repository, so there is no third-party client to accommodate and a permanent compatibility branch
would be carried forever to serve a window that closes as soon as each desk is updated.

**Anyone deploying to a desk they cannot immediately update needs to know this.** Migration 0005's
docstring repeats it, because that is the file a person reads when they are deploying.

---

## 9. Files changed

23 files, +1,244 / −159.

| File | Change |
| :--- | :--- |
| `src/core/worker_templates.py` | **New**, 182 lines — the shared value objects |
| `alembic/versions/0005_worker_template_descriptions.py` | **New**, 100 lines — rename + in-place rewrite + count column |
| `src/core/worker_auth.py` | `Worker.templates` / `unrecognised_template_count`; constants re-exported from the new module |
| `src/api/worker_schemas.py` | `WorkerTemplate` reused as the wire shape; `TemplateName` removed |
| `src/api/worker_routes.py` | Heartbeat accepts the new report |
| `src/api/worker_dashboard_routes.py` | Summary carries templates + count |
| `src/core/postgres_worker_store.py` | `templates` column, `_templates_json`, per-row re-validation |
| `src/integrations/worker_cloud_client.py` | `heartbeat(WorkerTemplateReport)` |
| `src/modules/seo/screaming_frog_control/template_registry.py` | `scan()`, `TemplateScan`, sidecar reading |
| `src/modules/seo/screaming_frog_control/schemas.py` | `ScreamingFrogTemplate.description` imports its constraints |
| `src/modules/seo/screaming_frog_control/worker_daemon.py` | Clamp + report assembly |
| `rankuno-ui/src/adapters/adapterInterface.ts` | `templates` object array; `unrecognised_count` |
| `rankuno-ui/src/components/screaming-frog/ScreamingFrogView.tsx` | Description beneath the Select; skipped-file hint |
| `rankuno-ui/src/components/screaming-frog/screaming-frog.css` | `.sfd-template-note` |
| `rankuno-ui/src/test/factories.ts` | Factory updated |
| 8 test files | +41 Python, +3 UI |

---

## 10. Process hazard: the fourth branch-state event

Recorded factually, without speculation about cause.

The implementing agent was briefed that it was on branch `fix/ui-reload-restores-view-and-crawl` at
`eb1d7e8`. It found itself on `main` at `6cc479d` with a clean working tree. **It made no git write
of any kind** and reported the discrepancy rather than acting on it.

Its Python baseline reconciled exactly — 3368 − 41 = 3327, which is 0116's recorded figure — so the
code it built on was the code the brief had measured, whatever the branch was called.

Separately, the two commits from the prior cycle now appear on `main` as `5303b7b` and `6cc479d`,
having been cherry-picked and pushed by another actor.

Prior events of this class: build-log 0112 and build-log 0116. This is the fourth.

Its practical cost this cycle was zero. Its practical risk is not: an agent that had trusted the
brief's branch name and run a git write would have written to the wrong ref, and an agent that had
trusted the brief's baseline without reconciling would have reported a wrong test delta.

---

## 11. Follow-ups

| Item | Why it is not done here |
| :--- | :--- |
| Correct `CLAUDE.md` §8's `Dockerfile` line | Only the user edits `CLAUDE.md`; replacement text handed over in the scribe's report (§5.1) |
| Rung 2 — hash-pinned config allow-list | ADR 0021; needs an operator vetting step that does not exist |
| Rung 3 — upload to quarantine | ADR 0021; blocked on `Principal` gaining a role field |
| Trim `WorkerSummary.templates` | §6.3; not a problem at present fleet size |
| Split the three over-target files | §6.4; each is its own refactor |
| Verify migration 0005 against a real Postgres | Same standing gap as migrations 0002–0004: `psycopg` is not installed locally and no server is reachable. Covered by the in-memory fake cursor only |
