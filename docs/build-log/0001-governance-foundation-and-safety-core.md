# Cycle 0001: Governance foundation & Phase 1 safety core

- **Date**: 2026-08-06
- **Scope**: Establish version control, resolve specification contradictions, and land the three safety controls that must exist before any crawler code.
- **Commit**: `8fb66b1` — 97 files, 9,618 insertions
- **Quality gate**: 248 tests, 96.91% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   22 source files, mypy --strict
=== Tests ===       PASSED   248 passed, 96.91% coverage
ALL GATES PASSED.

Drift audit: PASSED — 38 markdown files, all links resolve
```

Baseline before this cycle was 65 tests at 88.67%.

---

## 2. What landed

### `src/core/url_safety.py` — SSRF guard (52 tests)

The crawler accepts operator- and client-supplied URLs, which makes it a
server-side request forgery vector *by construction*. A target of
`http://169.254.169.254/latest/meta-data/iam/security-credentials/` is not a
malformed URL — it is a well-formed request for cloud instance credentials.

Deny-by-default. Produces a `SafeUrl` type rather than returning a boolean, so a
reviewer can distinguish validated URLs from raw strings at a glance and an
unvalidated string cannot reach an HTTP client by accident.

Checks, in order: scheme allowlist (blocks `file:`, `gopher:`, `data:`),
embedded-credential rejection, control-character rejection (CRLF request
splitting), port allowlist, internal-hostname rejection **before** resolution,
then private-range blocking across **every** resolved address.

Three cases that a naive implementation misses, all tested:

- **IPv4-mapped IPv6.** `::ffff:127.0.0.1` is loopback wearing a v6 costume.
  Unwrapped before classification, as are 6to4 and Teredo.
- **Multi-homed hosts.** One private address in the set poisons the whole
  hostname. Checking only the first resolved address is a bypass.
- **Unicode homographs.** Hostnames are IDNA-encoded so a look-alike domain
  cannot slip past the suffix checks.

**Documented limitation, not solved:** DNS rebinding. Validation resolves and
checks, but a resolver can answer differently when the HTTP client resolves again
moments later. `SafeUrl.resolved_ips` is exposed specifically so a caller can pin
the connection to an address that was actually validated. Callers that reconnect
by hostname remain exposed, and the module docstring says so rather than implying
the problem is closed.

### `src/core/robots.py` — robots.txt & crawl-delay, RFC 9309 (43 tests)

Written rather than using `urllib.robotparser`, for a concrete reason: the stdlib
resolves conflicting rules by **declaration order**; RFC 9309 resolves by
**specificity**. On this extremely common pattern —

```
Disallow: /resources/
Allow: /resources/blog/
```

— the RFC permits `/resources/blog/post`; the stdlib refuses it. On HighRadius
that is 2,220 crawlable URLs silently lost, with no error to notice.

Pattern matching uses a **linear two-pointer glob, not a translated regex**.
robots.txt from a hostile or merely sloppy host is attacker-influenced input, and
`/*a*a*a*a*a*b` compiled to a regex is a catastrophic-backtracking DoS. There is
a test asserting an adversarial pattern terminates.

### `src/core/rate_limiter.py` — `AsyncTokenBucket`

Per [ADR 0003](../adr/0003-job-level-governance-and-async-internals.md).
Governance is synchronous because it is per-job; politeness must be async because
it is per-request and a blocking sleep would stall every other in-flight request
on the event loop.

`from_crawl_delay()` sets capacity to **1** deliberately: a declared crawl delay
asks for evenly *spaced* requests, so permitting a burst would honour the letter
of the directive while violating its intent.

The refill arithmetic was extracted into a shared helper both variants call, so
the sync and async buckets cannot drift apart. Evidence the refactor was safe:
all 8 pre-existing sync tests still pass unchanged.

Tests use `asyncio.run()` rather than adding `pytest-asyncio` — `pyproject.toml`
explicitly asks for a minimal dependency surface, and nothing here needs more than
the standard library.

### `src/integrations/llm_client.py` — provider-agnostic LLM interface

Interface only; no concrete provider (that needs a live credential and network).

`complete()` takes a `StrictModel` subclass and returns an instance of it, so
there is no `dict[str, Any]` anywhere and no prompt-and-parse retry loop. The
budget gate is **pre-flight**: a refused call never reaches the provider and costs
nothing, which is tested explicitly rather than assumed.

### `src/modules/seo/page_classifier/schemas.py` — Phase 1 taxonomy

`FullPageIntelligenceProfile` per
[ADR 0002](../adr/0002-canonical-phase1-output-contract.md), absorbing the
graph-topology fields from the retired `SiteNodeIntelligence`.

A `model_validator` rejects incoherent level/type pairs at construction, so a
consensus bug fails on the page that caused it rather than producing a site tree
with a second homepage three levels down.

---

## 3. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| `SafeUrl` as a distinct type | Return `bool` | A type makes "has this been validated?" answerable by reading, not by tracing call sites |
| Own robots parser | `urllib.robotparser` | Order-based conflict resolution is wrong and fails silently |
| Two-pointer glob | Regex translation | Attacker-influenced patterns; no catastrophic backtracking |
| `asyncio.run()` in tests | Add `pytest-asyncio` | Keeps the dependency surface minimal, as pyproject requires |
| Pre-flight budget gate | Charge after the call | A gate that fires after the spend is not a gate |
| `conversion_role` as enum | Bare `str` (as specified) | An untyped label cannot be aggregated across 20,000 pages, which is its only use |

### Ten specification contradictions resolved

The source documents were written at different times and genuinely disagree.
Rulings are recorded in [CLAUDE.md](../../CLAUDE.md) §7, which explicitly beats the
source documents. The sharpest:

- `_execute_impl(self, args)` (STEP6 standard) vs `execute(self, payload)` (actual
  code). **The code is right; the binding standard described an API that does not
  exist.**
- "Governed 10-step pipeline" vs 7 implemented. Idempotency, circuit breaker and
  checkpointing are **not** implemented; the register now says so.
- Enum case: governance enums lowercase (matching shipped code), domain taxonomy
  enums UPPER (matching every Phase 1 blueprint).
- `PrimaryPageType`: 14 members, not the blueprint's 12 — `CASE_STUDY` and
  `TOOL_APPLICATION` are both referenced elsewhere and observed in the HighRadius
  audit.

---

## 4. Bugs found and fixed

### A wrong number in my own ADR, caught by a test

While writing `test_llm_client.py` I asserted that output tokens dominate Layer 3
cost. **The test failed, and it was right.** At 1,200 input / 150 output tokens on
Haiku 4.5 pricing, input costs $0.0012 and output $0.00075 — input is larger in
absolute terms. Output is 5× per *token*, which is not the same claim.

The `$0.14` figure in ADR 0005's cost table was arithmetically wrong; it implied
both a trimmed output and a reduced input without saying so.

Corrected table, now **pinned by tests** so it cannot silently go stale:

| Configuration | Per call | 2% fallback | 0.5% fallback |
| :--- | ---: | ---: | ---: |
| Naive | $0.00195 | $0.78 | $0.20 |
| Batch API | $0.00098 | $0.39 | $0.10 |
| Batch + trimmed output | $0.00070 | $0.28 | $0.07 |
| Batch + trimmed + 4k cached prefix | $0.00040 | $0.16 | **$0.04** ✅ |

The useful conclusion is stronger than the wrong one: the target **is** reachable,
but only with every lever applied *and* a 0.5% escalation rate. That makes it an
**accuracy requirement on Layers 0–2**, not a model choice.

### `drift_check.py` was a near-vacuous gate

Its module check used substring matching, so `"seo"` "passed" because the string
appeared inside `seo-engine-guide` in an unrelated link. Its core-file loop was an
empty `for` body containing `pass`. It reported a clean audit while eleven links
were broken.

Rewritten to verify every relative link resolves, using path-based matching.
**Self-tested** by injecting a broken link and confirming it fails — a checker
that has never been seen to fail is not known to work.

---

## 5. Corrections

- **"My shell has no network."** Too broad. Git reaches GitHub fine because it
  bundles its own HTTPS stack; Python and PowerShell outbound still hang. The
  accurate statement is *git networking works, Python networking does not*.
- **"Authentication resolved."** Overstated. An exit-0 `git ls-remote` proved
  reachability only — the probe succeeded anonymously, and exit 0 with no branches
  simply means the repo is empty.
- **Git was installed all along** at the time I reported it missing. My shell
  captured its environment before the install, so `git` was not on `PATH` even
  though the binary existed. I was checking the wrong thing.

---

## 6. Explicitly not done

| Item | Why |
| :--- | :--- |
| `core/circuit_breaker.py` | Gap register item; not required before crawler code |
| `core/state_store.py` | Same. **Consequence: an interrupted crawl loses its work** |
| Idempotency keys | Specified for WRITE/FINANCIAL; no such tool exists yet |
| Concrete LLM provider | Needs a live credential and network access |
| Distributed rate limit / spend ceiling | In-process only. Blocking for hosted deploy, not for local ([ADR 0004](../adr/0004-local-first-deployment-swappable-ml-layer.md)) |
| Golden corpus | Needs network to fetch sitemaps. **The ≥98% accuracy claim is currently unverifiable** |
| 4 domain skills | GSC/GA4, Google Ads, SEO scraping, AEO/GEO. Empty shells removed and links dropped rather than left implying they work |

**Credentials retained in-repo by explicit operator decision.**
`docs/RANKUNO_INFRASTRUCTURE_ACCOUNTS_AND_SETUP_RECORD.pdf` contains a shared
plaintext password. Flagged twice, decision reaffirmed, proceeded. Now in commit
history — removing it later requires a history rewrite, not a file deletion.

---

## 7. Files changed

**New — core**: `url_safety.py`, `robots.py`
**New — integrations**: `llm_client.py`
**New — modules**: `seo/page_classifier/{__init__,schemas}.py`
**Modified**: `core/errors.py` (+`UnsafeUrlError`, `RobotsDisallowedError`),
`core/rate_limiter.py` (+`AsyncTokenBucket`, `AsyncRateLimiterRegistry`)

**Governance**: `CLAUDE.md` (new), `docs/adr/0001`–`0005` (new),
`docs/standards/SDLC_STEP1`, `SDLC_STEP4` (new), `scripts/drift_check.py`
(rewritten), `README.md` + `docs/ARCHITECTURE.md` (corrected to verified state)

**Repo**: `.gitattributes` (new — `eol=lf`, CI runs Linux while development is on
Windows), `.gitignore` (coverage/cache artifacts, model weights)

**Tests**: `test_url_safety.py` (52), `test_robots.py` (43),
`test_llm_client.py` (32), `test_page_classifier_schemas.py` (40), plus
`AsyncTokenBucket` coverage in `test_rate_limiter.py`

---

## 8. Follow-ups

1. `git push -u origin main` — remote wired, needs interactive auth.
2. Golden corpus — blocked on network.
3. `CostLedger` needs reserve/settle semantics before any variable-cost tool is
   classified `FINANCIAL`.
4. Reconcile the cost claim in `TECH_STACK_SPECIFICATION.md` §3 with ADR 0005.
5. `str_strip_whitespace` on `StrictModel`, with test coverage (CLAUDE.md §7 #4).
