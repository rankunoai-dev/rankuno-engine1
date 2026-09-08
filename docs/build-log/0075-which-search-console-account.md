# Cycle 0075: Which Search Console account — named GSC profiles selected per crawl

- **Date**: 2026-09-08
- **Scope**: A crawl names which authorised Google account reads Search Console
  for it. Profiles live in `.env.local` as `GSC_ACCOUNTS__<name>__*`; the API
  publishes names only; the crawl modal offers a picker when there is something
  to pick. ADR 0012.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `verify.ps1 -Fix` exit 0. Python coverage 93.86%
  (`TOTAL 7667 379 1920 138 94%`); UI `232 passed` / 21 files. The implementer
  did not quote the Python passed-count; the docs-scribe run in §1.3 supplies it.

**Cycle number.** This entry was drafted as 0074. While it was being written,
another session claimed 0074 in the index, `README.md` and `docs/ARCHITECTURE.md`
(`0074-absent-is-not-empty.md`, the Screaming Frog adapter). Numbers are never
reused and a collision is never created (`README.md` in this directory), so this
cycle is 0075. ADR 0012 and this cycle's Step 8 edits were renumbered with it.

---

## 1. Gate results

### 1.1 Implementer's gate (verbatim from the hand-off; not re-run by docs-scribe)

```
npm run typecheck: tsc --noEmit, clean.
npm run contract:  "UI contract is up to date."  exit 0
npm run build:     "✓ built in 49.48s"           exit 0   (pre-existing chunk-size warning)

npm test inside the gate:
 Test Files  21 passed (21)
      Tests  232 passed (232)
PASSED: UI Component Tests
ALL GATES PASSED.
gate exit=0

Python coverage:
TOTAL   7667    379   1920    138    94%
Required test coverage of 85% reached. Total coverage: 93.86%

ruff check .:          All checks passed!
ruff format --check .: 282 files already formatted.
mypy --strict server.py tool.py: Success: no issues found in 2 source files.
verify.ps1 -Fix exit 0.
```

The `mypy` line above is the implementer's targeted run on two files. The full
`verify.ps1` type-check stage covers the whole `src/` tree and passed inside the
same `exit 0`; its own summary line was not quoted.

### 1.2 Drift check

`scripts/drift_check.py` was run three times while this entry was being
written. The final run, on the tree as it stands, passed:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
EXIT=0
```

The two earlier runs reported three broken links, all pointing at the other
session's `0074-absent-is-not-empty.md`, which had been indexed and linked in
`README.md` and `docs/ARCHITECTURE.md` before the file existed on disk; it landed
between the second and third run. Kept for the record because it is how the
cycle-number collision in the header note was discovered. None of the links
this cycle added was ever reported. The 12 broken links in 0058/0060/0061 that
cycles 0062–0073 carried are gone: that session's edits to those three entries
are in the working tree.

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
FAILED: 3 documentation drift issue(s) detected:

  - docs\ARCHITECTURE.md: broken link -> build-log/0074-absent-is-not-empty.md
  - docsuild-log\README.md: broken link -> 0074-absent-is-not-empty.md
  - README.md: broken link -> docs/build-log/0074-absent-is-not-empty.md

Update the documentation to reflect the verified state of the code.
EXIT=1
```

### 1.3 Docs-scribe pytest run

Run on 2026-09-08 against the working tree, which also holds other sessions'
uncommitted work (cycles 0072, 0073 and the `deliverables/` package in
progress), so the count is of the whole tree, not this cycle alone:

```
$ .venv/Scripts/python.exe -m pytest -o addopts="" -p no:warnings --no-header -q
1964 passed, 1 skipped in 130.18s (0:02:10)
exit=0
```

---

## 2. What landed

### 2.1 `src/core/config.py` — the profile table

- `GscAccountProfile(StrictModel)`: `refresh_token: SecretStr` (required),
  `client_id: str | None`, `client_secret: SecretStr | None`.
- `ResolvedGscCredentials(StrictModel)`: the complete triple plus the profile
  name, so a consumer never has to re-derive inheritance.
- `Settings.gsc_accounts: dict[str, GscAccountProfile]`, populated by
  pydantic-settings with `env_nested_delimiter="__"`, so
  `GSC_ACCOUNTS__ACME__REFRESH_TOKEN=...` becomes `gsc_accounts["acme"]`.
- `GSC_ACCOUNT_NAME_PATTERN = r"^[a-z0-9_-]{1,64}$"` and a `field_validator`
  that refuses any configured key the request schema could never select.
  Lowercase because pydantic-settings lowercases nested env keys under
  `case_sensitive=False`.
- `gsc_account_names()` returns a sorted tuple of names.
- `resolve_gsc_account(name)`: `None` returns the legacy flat
  `GOOGLE_OAUTH_*` triple; a known name returns its token with `client_id` /
  `client_secret` inherited from the flat pair unless the profile overrides
  them; an unknown name raises `ConfigurationError`. **There is no fallback**:
  querying the wrong client's Search Console is worse than a failed crawl, and
  the docstring says so.

### 2.2 `src/integrations/gsc_token_manager.py`, `gsc_client.py`, `gsc_schemas.py`

- Both constructors gained `account: str | None` (keyword-only). The token
  manager calls `resolve_gsc_account(account)` once, in `__init__`.
- Audit identity is the profile name: `get_account_email()` returns
  `oauth2://profile/<name>` for a named account and `oauth2://<client_id>`
  for the default. Logs carry `account` in `extra`.
- Audit finding F2: the token refresh POST was moved **outside** `with_retries`.
  A revoked refresh token answers `invalid_grant`, which is not transient, and
  retrying it four times against Google's token endpoint is the pattern
  ADR 0010 §1 exists to prevent. Regression tests in
  `tests/integrations/test_gsc_client.py` (L332–385) assert
  `mock_post.call_count == 1` on both the analytics and the property-list paths.
- Audit finding F7: `test_invalid_grant_names_the_code_and_nothing_else`
  asserts that the response body of a failed refresh never reaches a log line.
- `GscOAuthToken.access_token` is now `SecretStr` (F6). It was a plain `str`
  and would have printed in any `repr`.

### 2.3 `src/modules/seo/page_classifier/tool.py`

- `PageClassificationInput.gsc_account: str | None`, `min_length=1`,
  `max_length=64`, `pattern=r"^[a-z0-9_-]+$"`. The shape is enforced at the
  request boundary so a name that could never match a profile is a 422 before
  anything looks at settings.
- Enrichment constructs `GscApiClient(account=payload.gsc_account)` and puts
  the account name in the enrichment log extras.
- The enrichment failure log records `type(exc).__name__`, not `str(exc)`. An
  OAuth error message can quote the request that produced it.

### 2.4 `src/api/server.py`

- `GscAccountsView(StrictModel)` — a list of strings, deliberately not a
  serialised `Settings` sub-tree that a later field could quietly widen.
- `GET /api/v1/gsc/accounts` returns the sorted names and nothing else.
- Admission: inside `_start`, which is shared by create, retry and resume, an
  unknown `gsc_account` is a 400 and **no job record is created**. A retry
  replays a stored payload, and a profile can be deleted from `.env.local`
  between runs; refusing at admission is the only place that covers all three
  entry points at once (audit finding F4). Left to the enrichment step it would
  degrade gracefully and report "no search data", which is the silent-wrong
  outcome the audit rejected.

### 2.5 `.env.example`

`GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REFRESH_TOKEN` documented as the
default account, and a commented `GSC_ACCOUNTS__ACME__*` block showing the
three keys (only `REFRESH_TOKEN` required). Values are blank; real values go in
`.env.local`, which is gitignored.

### 2.6 UI

- `adapterInterface.ts`: optional `listGscAccounts?(): Promise<string[]>`;
  `DEFAULT_CRAWL_REQUEST.gsc_account = null`.
- `httpAdapter.ts` implements it. `mockAdapter.ts` deliberately does **not**, so
  fixture mode never shows a picker for accounts that do not exist.
- `LiveCrawlModal.tsx` fetches on open, renders a "Search Console account" antd
  `Select` only when the list is non-empty, uses `""` as the sentinel for
  "Default (.env.local)" and maps it to `null` on submit, disables the control
  while loading, and treats a fetch failure as "no picker" — an older engine
  without the endpoint must still be crawlable.
- `rankuno-ui/src/types/schema.ts` regenerated: `gsc_account: string | null`.

### 2.7 Tests

| File | Added |
| :--- | :--- |
| `tests/core/test_config.py` | +101 lines: profile parsing, name validation, inheritance, unknown-name refusal |
| `tests/integrations/test_gsc_client.py` | +78 lines: `call_count == 1` on `invalid_grant`, two paths |
| `tests/integrations/test_gsc_token_manager.py` | rewritten for accounts (217 lines changed per `git diff --stat`) |
| `tests/modules/seo/page_classifier/test_gsc_e2e.py::TestGscAccountSelection` | account passed to client; default `None`; name shape enforced at the boundary, parametrised over `Acme`, `"a b"`, 65 chars, `""` |
| `tests/api/test_gsc_accounts_endpoint.py` (new) | `TestListAccounts` (names only; body carries no credential; empty when unconfigured), `TestCreateJobWithAccount` (unknown → 400 and no job; known → accepted; none → unchanged; unknown even with none configured → 400; malformed → 422), `TestReplayWithAccount` (retry with now-unknown → 400; known → accepted) |
| `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx` (new) | absent when adapter lacks the method; absent on `[]`; absent on fetch reject; lists names and submits `"acme"`; default submits `null` |

---

## 3. Design decisions

### 3.1 Security audit: Option B rejected, Option A passed with conditions

Two designs were put to the security-auditor before code was written.

- **Option B — a settings form in the UI** that posts credentials to the local
  API, which writes them to `.env.local`. **Rejected (F1, HIGH).** The API is
  unauthenticated and bound to loopback by design (ADR 0008); it is the wrong
  ingress for a refresh token. Anything on the workstation that can reach
  `127.0.0.1:8000` could then read or replace a client's Search Console
  credential, and the credential would transit React state and the browser's
  devtools on the way.
- **Option A — profiles in `.env.local`, names over the API.** Passed, with the
  conditions recorded as findings F2–F7 below. Credentials are typed once by an
  operator into a gitignored file and never enter the API, React state, a job
  record, or a log line.

The findings list, for the record:

| # | Severity | Finding | Outcome |
| :--- | :--- | :--- | :--- |
| F1 | HIGH | Design B: credentials over an unauthenticated API | design rejected |
| F2 | MEDIUM | Auth error (`invalid_grant`) retried inside `with_retries` | fixed; refresh moved outside the retry loop; `call_count == 1` tests |
| F3 | MEDIUM | `requests.post` to the token URL outside `BaseAPIClient` (rule 5) | accepted deviation; recorded in the module docstring (§6) |
| F4 | MEDIUM | Unknown profile name resolved silently | fixed; admission validation in `_start`, no fallback in `resolve_gsc_account` |
| F5 | LOW | Audit identity did not distinguish accounts | fixed; `oauth2://profile/<name>` |
| F6 | LOW | `access_token` was a plain `str` | fixed; `SecretStr` |
| F7 | LOW | Build-log 0064 lists files that do not exist | corrected in §5 |

### 3.2 Nested env keys rather than a JSON blob or a separate file

`GSC_ACCOUNTS__ACME__REFRESH_TOKEN` is one line per value in the file that
already holds the default credentials, is parsed by the settings library the
project already uses, and keeps rule 3 (no `os.environ` reads outside
`Settings`) intact without a second loader. A JSON blob in one variable would
have put every client's token on one line; a separate YAML file would have been
a second secret store to gitignore, document and audit. Alternatives are in
ADR 0012.

### 3.3 Names only over the wire, and a fixed-shape view model

The endpoint returns `list[str]`. `GscAccountsView` exists so the response
shape is a declared model rather than whatever `Settings.gsc_accounts` happens
to serialise to; a future field on `GscAccountProfile` cannot leak through it.

### 3.4 Refuse at admission, not at enrichment

Discussed in §2.4. The enrichment step is written to degrade gracefully when
Search Console is unavailable, which is right for a network fault and wrong for
a misconfiguration. Putting the check in `_start` reuses the argument already
made there for SSRF re-validation on retry.

### 3.5 The picker is absent, not disabled, when there is nothing to pick

An empty list, an adapter without the method, and a failed fetch all render no
control at all. A disabled dropdown would imply accounts exist that the operator
cannot reach; none of the three cases means that.

---

## 4. Bugs found and fixed

### 4.1 Six ruff errors left by session 1 were blocking the gate

Session 1 (config, token manager, client, schemas) ended with six ruff errors in
its test files. Session 2 fixed them before its own work; the gate would not
have been green otherwise. Session 1 had reported its unit tests passing, which
was true, and did not run the full gate.

### 4.2 A test was wrong and the code was right

`TestGscAccountSelection.test_account_name_shape_is_enforced_at_the_boundary`
originally included `"acme__x"` as a name that should be rejected. It is valid
under `^[a-z0-9_-]+$`: underscores are permitted, and two of them are still
underscores. The concern behind the case — that a name containing `__` could be
confused with the nesting delimiter — does not arise at the request boundary,
because the delimiter is consumed by pydantic-settings when the environment is
read, before the name exists as a key. The case was removed from the
parametrisation. Remaining cases: `Acme` (uppercase), `"a b"` (space), 65
characters (length), `""` (empty).

### 4.3 antd `Select` renders the chosen value with the option's `title`

In `LiveCrawlModal.test.tsx`, an unscoped `findByTitle("acme")` found two
elements: the option row in the dropdown and the closed control showing the
selected value. The query is now scoped to `.ant-select-dropdown`. Separately,
a cold jsdom takes roughly 4 s to mount the dropdown portal, so that one test
waits up to 15 s and has a 30 s timeout, with a comment explaining why.

### 4.4 A session was interrupted mid-implementation

The Claude Code process exited during the first implementation attempt. Work
resumed from the working tree with no loss; nothing had to be redone. Recorded
so a future reader of the diff is not surprised by two authoring sessions in one
cycle.

### 4.5 Observed in the diff, not in the implementer reports

`scripts/export_ui_contract.py` now writes `schema.ts` with `newline="\n"`.
Without it, `write_text` on Windows emits CRLF and `npm run contract` reports
the file as stale on a tree that is otherwise up to date. Neither session
mentioned it; the change is in `git diff` and is consistent with the
"UI contract is up to date" line in §1.1.

---

## 5. Corrections

1. **Build-log 0064 "Files changed" lists `test_gsc_connection.py` and
   `test_gsc_crawl.py` as new files at the repository root** (lines 118–119) and
   gives commands to run them (lines 162, 165). Neither file exists in the
   working tree and neither has ever been tracked (`git ls-files` finds
   nothing). They were scratch scripts deleted before the gate, as CLAUDE.md §4
   requires, and the entry described them as deliverables. Audit finding F7.
2. **Build-log 0064 contained the real OAuth client id and client secret
   values.** A push was blocked by GitHub secret scanning on 2026-09-07. At the
   time of writing, line 21 of that entry as committed at `HEAD` still carries a
   credential-shaped `apps.googleusercontent.com` value. The values are not
   reproduced here and must not be reproduced in any build-log entry, ADR,
   README or test fixture: the log is committed, and rule 4 of
   `docs/build-log/README.md` ("never revise history") does not extend to
   secrets. Redaction of the historical entry plus rotation of the credential
   in Google Cloud is a **separate action**, not part of this cycle (§8).
3. **`docs/ARCHITECTURE.md` §2 "Planned, not yet implemented"** said
   `integrations/google_search_console.py` — "No connector exists. Search
   Console data arrives only by manual upload; nothing fetches it." That has
   been false since cycles 0055 and 0064 shipped `gsc_client.py`,
   `gsc_token_manager.py`, `gsc_property_validator.py` and `gsc_schemas.py`,
   and none of the four was in the §2 tree. Corrected in this cycle's Step 8:
   the four files are in the tree, and the row now says only GA4 has no
   ingestion.

---

## 6. Explicitly not done

- **Option B, the settings form.** Rejected by the audit (§3.1). Credentials
  are entered by editing `.env.local`; there is no UI for it and none is
  planned under ADR 0012.
- **F3, `requests.post` outside `BaseAPIClient`.** `gsc_token_manager.py`
  posts directly to the fixed Google token URL. Routing it through
  `BaseAPIClient.call()` would put the refresh inside `with_retries`, which is
  the F2 defect. The deviation from rule 5 is accepted by the audit and stated
  in the module docstring. It is not a precedent for any other outbound call.
- **The `gsc_quota` rate limiter is still in-process, one bucket per worker.**
  CLAUDE.md §8 is unchanged.
- **Per-profile rate-limit buckets were not built.** One shared `gsc_quota`
  bucket is correct while every profile authorises the same OAuth app, because
  Google's per-project quota is shared. If a profile ever supplies its own
  `client_id`, that reasoning no longer holds and a per-app bucket is needed.
- **The hard-coded Search Console date range in `tool.py`**
  (`2026-01-01`..`2026-12-31`, lines 515–516) is unchanged. Optional follow-up.
- **`LiveCrawlModal` still uses antd's deprecated `destroyOnClose`.** The
  warning pre-dates this cycle.
- **Redaction and rotation of the 0064 credential** (§5.2) is not done here.
- **This entry is not committed**, per the brief.

---

## 7. Files changed

Backend (session 1):

```
src/core/config.py                              GscAccountProfile, ResolvedGscCredentials, gsc_accounts,
                                                gsc_account_names(), resolve_gsc_account(), name validator
src/integrations/gsc_token_manager.py           account kwarg; refresh outside with_retries; profile identity
src/integrations/gsc_client.py                  account kwarg
src/integrations/gsc_schemas.py                 GscOAuthToken.access_token: SecretStr
tests/core/test_config.py                       +101
tests/integrations/test_gsc_client.py           +78
tests/integrations/test_gsc_token_manager.py    rewritten for accounts
```

Backend (session 2):

```
src/modules/seo/page_classifier/tool.py         gsc_account field; GscApiClient(account=...); log extras
src/api/server.py                               GscAccountsView; GET /api/v1/gsc/accounts; admission check in _start
.env.example                                    GOOGLE_OAUTH_* and commented GSC_ACCOUNTS__ACME__* block
rankuno-ui/src/types/schema.ts                  gsc_account: string | null (regenerated)
scripts/export_ui_contract.py                   newline="\n" (§4.5)
tests/modules/seo/page_classifier/test_gsc_e2e.py   TestGscAccountSelection
tests/api/test_gsc_accounts_endpoint.py         new
```

UI:

```
rankuno-ui/src/adapters/adapterInterface.ts     listGscAccounts?(); gsc_account: null in DEFAULT_CRAWL_REQUEST
rankuno-ui/src/adapters/httpAdapter.ts          listGscAccounts()
rankuno-ui/src/components/layout/LiveCrawlModal.tsx        account picker
rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx   new
```

Documentation (this cycle's Step 8):

```
docs/build-log/0075-which-search-console-account.md   this entry
docs/build-log/README.md                              index row
docs/adr/0012-gsc-account-profiles.md                 new
README.md                                             "Search Console accounts" subsection; GET /api/v1/gsc/accounts
docs/ARCHITECTURE.md                                  GSC connector files in the tree; §2 row corrected (§5.3);
                                                      gsc_account on the input; ADR 0012 row
```

`CLAUDE.md` was not touched. ADR 0012 is a configuration convention and a
credential boundary; it changes no ruling in §6 or §7 and closes no gap in §8.

The working tree also holds unrelated uncommitted work from the Screaming Frog
cycles (0072, 0073 and the `deliverables/` package in progress). None of it was
touched by this cycle and none of it is described here.

---

## 8. Follow-ups

1. **Redact the credential in build-log 0064 and rotate it in Google Cloud.**
   Separate action; both halves are required — redaction alone leaves a live
   secret in git history.
2. **Replace the hard-coded date range in `tool.py`** with a request field or a
   trailing window. Optional.
3. **Per-app rate-limit buckets** if any profile ever carries its own
   `client_id` / `client_secret`.
4. **`destroyOnClose` → `destroyOnHidden`** in `LiveCrawlModal.tsx` when antd is
   next bumped.
