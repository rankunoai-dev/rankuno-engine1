# Cycle 0089: Rotation is not rebinding

- **Date**: 2026-09-11
- **Scope**: `_verify_peer` in `src/integrations/http_fetcher.py` now classifies the
  actually-connected peer address with `describe_ip_block()` instead of doing raw
  set-membership against a pre-connect DNS snapshot, so a public CDN edge answering
  from an address outside that snapshot is treated as address rotation, not refused as
  DNS rebinding, while a peer that classifies as private/loopback/link-local/reserved
  is refused exactly as before.
- **Commit**: uncommitted at time of writing
- **Quality gate**: mypy `--strict` clean on `src/integrations/http_fetcher.py`; ruff
  clean on the touched `src/` file and the touched `tests/integrations/test_http_fetcher.py`
  file (2 pre-existing `D205` errors remain in `tests/modules/seo/test_discovery.py`,
  outside this cycle's own test additions — see §7); targeted suite
  `tests/integrations/test_http_fetcher.py`, `tests/core/test_url_safety.py`,
  `tests/modules/seo/test_discovery.py`, `tests/modules/seo/test_async_discovery.py` —
  **264 passed in 73.57s**, exit 0, independently re-run; full-repo `verify.ps1` not run
  to a green exit — see §7.

## 1. Origin

Diagnosing a live crawl of infosys.com this session (job
`0f69b80025874d30b57f54de33b8f705`) found that 3,597 of 3,960 records bucketed as
`transport_error` (see cycle 0087, which gave that refusal its own
`guardrail_refused` bucket) were the DNS-rebinding guard in `_verify_peer` refusing
legitimate CDN traffic: Akamai edge IPs answering a request from a different address
than the one `UrlSafetyPolicy.validate()` had resolved and validated moments earlier.
Every one of those refusals was against a *public* address — none was an attack.

A security-auditor review (a separate, already-recorded cycle) analysed four
distinguishing cases and recommended reusing the already-audited
`describe_ip_block()` classifier — the same function `UrlSafetyPolicy._validate_addresses`
already trusts pre-connect for every DNS answer — to answer one question post-connect:
is the *connected* peer itself dangerous, not merely absent from the validation
snapshot. A bug-fixer Step 3 design pass turned that into an exact code-level plan.
The operator approved with the explicit framing: "don't break the present healthy
logic, but the end goal is to achieve that we can crawl all the pages."

## 2. Security decision recorded

- **Case 2 — genuine DNS-rebinding attack** (hostname resolves to a public address at
  validation time, then the connection lands on a private/internal address): refusal
  behaviour is **identical** to before this change — same `UnsafeUrlError`, same
  `OUTCOME_GUARDRAIL_REFUSED` bucket, unconditional. Nothing about this fix weakens
  that refusal.
- **Cases 1 and 3 — CDN edge rotation and benign operational DNS repointing to another
  public address**: these **stop being refused**. The mismatch is logged at `INFO`
  (`peer_address_rotation`) and the fetch proceeds.
- The one classification question — "is the connected peer itself dangerous" — is
  answered by `describe_ip_block()`, applied here post-connect to the single address
  the transport actually reached, exactly the same function already applied pre-connect
  to every resolved address in `UrlSafetyPolicy._validate_addresses`. No new
  classification logic was written.
- Explicitly rejected directions from the security review, **not** implemented here:
  TTL caching of DNS answers, pinning the connection to `SafeUrl.resolved_ips`,
  retrying against the address that was actually validated. All three would have
  either weakened the guard further or added machinery the review did not ask for.

## 3. What shipped

Exact diff of `_verify_peer` (`src/integrations/http_fetcher.py`):

```diff
     def _verify_peer(self, response: httpx.Response, safe: SafeUrl) -> None:
-        """Refuse a response served from an address that was never validated.
+        """Refuse a response served from a peer that classifies as unsafe.

         Detection after connect, not prevention — see the module docstring.
+
+        An exact match against `safe.resolved_ips` is the common case and needs
+        no further check. A mismatch alone is not evidence of an attack: a CDN
+        or load balancer legitimately answers from any of several published edge
+        addresses, and which one a given connection lands on can differ between
+        the validation lookup and the transport's own independent lookup a
+        moment later. So a mismatch is refused only when the connected peer
+        itself classifies as unsafe — private, loopback, link-local, reserved,
+        etc. — using the same `describe_ip_block` classification already applied
+        pre-connect, in `UrlSafetyPolicy._validate_addresses`, to every resolved
+        address. That is the one outcome this guard exists to prevent: a
+        hostname rebound to an internal address after a public one was
+        validated. A mismatch onto another public address is address rotation,
+        not rebinding, and is not refused.
         """
         peer = self._peer_address(response)
         if peer is None or peer in safe.resolved_ips:
             return
+
+        reason = describe_ip_block(peer)
+        if reason is None:
+            _logger.info("peer_address_rotation", extra={"host": ..., "connected": peer, "validated": ...})
+            return
+
         _logger.warning(
             "dns_rebinding_suspected",
-            extra={"host": safe.host, "connected": peer, "validated": safe.resolved_ips},
+            extra={"host": safe.host, "connected": peer, "validated": safe.resolved_ips, "reason": reason},
         )
-        raise UnsafeUrlError(safe.url, f"connected to unvalidated address {peer}")
+        raise UnsafeUrlError(safe.url, f"connected to unvalidated address {peer} — {reason}")
```

Plus one import: `describe_ip_block` added to the existing `from src.core.url_safety
import SafeUrl, UrlSafetyPolicy` line.

Confirmed by reading the file directly (not just the diff): the fast path — an exact
match against `safe.resolved_ips` — still short-circuits before any classification
call, so the common case (no CDN, no rotation) costs nothing extra. No change to
`url_safety.py`, `_validate_addresses` (the pre-connect sweep — confirmed still runs
unconditionally before any connection is attempted), `SafeUrl`, the two call sites
(`_fetch_chain`, `_afetch_chain`), or `_peer_address`. `git diff --stat
src/core/url_safety.py` against `HEAD` is empty — that file is untouched.

## 4. Tests

Five new tests in a new `TestVerifyPeer` class, `tests/integrations/test_http_fetcher.py`
(lines 584–655):

- `test_an_exact_match_takes_the_fast_path` — monkeypatches `describe_ip_block` to
  record calls; asserts it is never called on an exact match.
- `test_a_public_mismatch_is_rotation_not_rebinding` — the direct regression test for
  the diagnosed false positive; a validated `93.184.216.1` and a connected
  `93.184.216.9` must not raise.
- `test_a_multi_ip_cdn_pool_mismatch_is_not_refused` — a synthetic Akamai-style pool
  of two validated addresses, connection lands on a third public one; must not raise.
- `test_a_loopback_mismatch_is_refused_as_rebinding` — connected peer `127.0.0.1`
  against a public validated address; must raise `UnsafeUrlError` naming the peer.
- `test_a_private_rfc1918_mismatch_is_refused_as_rebinding` — connected peer
  `10.0.0.5`; must raise `UnsafeUrlError` naming the peer.

One new bucket-integrity test in `tests/modules/seo/test_discovery.py`'s existing
`TestGuardrailRefusalOutcome` class (added by cycle 0087):
`test_a_post_connect_rebinding_refusal_is_bucketed_the_same_way` — a page links to
`/rebind`, whose mocked response reports a peer at `127.0.0.1` against a validated
snapshot of a public address; asserts `discover_site` still buckets this as
`guardrail_refused == 1`, proving this fix did not touch outcome classification.

### Before/after regression proof (independently re-run by docs-scribe, not taken on the implementer's word)

Reverted only `_verify_peer`'s body to the pre-fix version (raw set-membership, no
`describe_ip_block` call) and ran the direct regression test:

```
        peer = self._peer_address(response)
        if peer is None or peer in safe.resolved_ips:
            return
        _logger.warning(...)
>       raise UnsafeUrlError(safe.url, f"connected to unvalidated address {peer}")
E       src.core.errors.UnsafeUrlError: Refused to fetch 'https://e.com/': connected to unvalidated address 93.184.216.9
FAILED tests/integrations/test_http_fetcher.py::TestVerifyPeer::test_a_public_mismatch_is_rotation_not_rebinding
============================== 1 failed in 0.22s ==============================
```

Restored the fix from the working-tree backup (`diff` against the backup afterward was
empty — the restore was exact), then re-ran both the `TestVerifyPeer` class and the
new `TestGuardrailRefusalOutcome` test:

```
tests\integrations\test_http_fetcher.py .....                            [ 71%]
tests\modules\seo\test_discovery.py ..                                   [100%]
============================== 7 passed in 0.20s ==============================
```

Full targeted run, independently re-run:

```
tests/integrations/test_http_fetcher.py tests/core/test_url_safety.py tests/modules/seo/test_discovery.py tests/modules/seo/test_async_discovery.py
264 passed in 73.57s (0:01:13)
```

Matches the implementer's reported 264/264 exactly.

## 5. Residual risk statement

Restated from the security review this cycle implements, for completeness:
`describe_ip_block()` already correctly classifies private/loopback/link-local/reserved
ranges, including IPv4-mapped, 6to4, and Teredo IPv6 encodings (confirmed by reading
the function). There is no address that would classify as public/clean here that
would not equally have been accepted had DNS validation itself returned it as one of
the resolved addresses — this fix does not admit any address class that
`UrlSafetyPolicy` would not already have admitted pre-connect.

Scope boundary, unchanged by this fix in either direction: this guard's threat model
is preventing SSRF into internal infrastructure, not guaranteeing which public origin
serves a given hostname. A hostname rebound to a different attacker-controlled
*public* address is out of scope for this guard — it was out of scope before this fix
too, since the guard has never attempted to pin a hostname to a specific origin, only
to keep connections out of private/internal address space.

## 6. Bugs found and fixed

The bug is the one this whole cycle exists to fix: `_verify_peer` treated *any*
mismatch between the connected peer and the pre-connect DNS snapshot as evidence of an
attack, when a mismatch is the expected, routine behaviour of any CDN or load
balancer with more than one edge address. On infosys.com this produced 3,597 false
refusals in one crawl — 90.8% of that crawl's `transport_error`/`guardrail_refused`
total was not a failure of any kind, it was the guard refusing to fetch pages that
were perfectly reachable. No bug in the specification or in a test was found during
this cycle; the flaw was in the original `_verify_peer` implementation's use of raw
set-membership as a stand-in for "is this dangerous," conflating "unexpected" with
"unsafe."

## 7. Gate

mypy `--strict` on the touched `src/` file, independently re-run:

```
Success: no issues found in 1 source file
```

ruff check on the touched `src/` file and the touched `tests/integrations/test_http_fetcher.py`
file, independently re-run:

```
All checks passed!
```

ruff check across the full `tests/modules/seo/test_discovery.py` file surfaces 2
`D205` errors — both re-confirmed by line number to sit in `TestSitemapFetchCeiling`
(lines 843, 917), which is not a class touched by this cycle; per the implementer's
own report these belong to the concurrent 0086-adjacent work already present in the
working tree, not to this change. The implementer separately reports fixing 2 `D205`
issues in their own new test docstrings before this state was reached — a
self-correction, not a pre-existing issue, and not visible in the current diff because
it was already applied by the time this review ran.

Full-repo `verify.ps1` was not run to a green exit this cycle. The reason is the same
as every other cycle this session: concurrent, uncommitted Redis/Celery/Postgres/
multi-tenant work already in the working tree at session start
(`scripts/chaos_test.py`, `src/workers/job_executor.py`, `src/core/celery_config.py`,
`src/core/redis_config.py`, `src/core/rate_limiter.py`, `src/core/postgres_store.py`,
`tests/api/test_idempotency.py`, `tests/core/test_redis_config.py`,
`tests/core/test_redis_token_bucket.py`) produces lint/type/pytest failures in files
this cycle never touched and has no authority to fix — see the "do not touch" list on
this cycle's own brief. None of the 264 tests in this cycle's targeted, dependency-
matched suite regressed.

## 8. Handoffs

Same concurrent-session gate-blocking causes as prior cycles this session
(0085 onward) — not this cycle's to resolve.

A transient test flake was observed and self-resolved mid-session: 
`test_an_unsafe_redirect_is_bucketed_separately_from_transport_errors` (from cycle
0087) briefly disagreed while this cycle's changes and the separate, already-closed
timeout/retry reconciliation cycle's outcome-bucket rename were landing concurrently
in the same working tree. It resolved once both cycles' changes were present together
and is not reflected in the current, passing state — recorded here as an observation,
not an open issue.

## 9. Explicitly not done

- No change to `src/core/url_safety.py` or `UrlSafetyPolicy._validate_addresses` — the
  pre-connect sweep is untouched and still runs unconditionally before any connection.
- No TTL caching of DNS answers.
- No connection pinning to `SafeUrl.resolved_ips` (this remains the open gap recorded
  in `CLAUDE.md` §8: "the SSRF guard ... cannot close the DNS rebinding window on its
  own. Callers must pin connections to `SafeUrl.resolved_ips`" — that statement is
  still accurate after this fix and is not being closed or reworded by this cycle).
- No retry-against-the-originally-validated-address on a rotation event.
- No change to `_peer_address`.
- The separate, already-closed timeout/retry reconciliation cycle's own scope
  (`REQUEST_DEADLINE_S`, `STALL_TIMEOUT_S`, `FETCH_RETRY_ON`, `OUTCOME_TRANSPORT_*`) is
  not touched or re-described here beyond confirming this cycle's tests pass alongside
  it (§4, §7) — that cycle has its own build-log entry.
- No ADR. See §10 for the reasoning.
- Did not commit, per this cycle's instructions.

## 10. ADR-worthiness determination

Not created, per this cycle's explicit brief, on the grounds that the design decision
was already made and approved through the proper channel — a security-auditor review
plus a bug-fixer Step 3 design pass, with explicit operator sign-off — and this cycle
only implements that already-closed decision rather than making a new one.

Stated independently, for the record: this is a closer call than a typical
implementation cycle, because it changes the observable behaviour of a control that
`CLAUDE.md` §5 marks as mandatory on every outbound fetch ("Two controls in `core` are
mandatory on every outbound fetch, and neither is optional"), and `CLAUDE.md` §6 is
explicitly the table where this kind of ruling is meant to live. The change also has
real alternatives-considered/rejected content (TTL caching, connection pinning,
retry-against-corrected-IP, all named and rejected in §2 above) that is exactly the
shape an ADR exists to capture, and that content will be harder to find, sitting only
in a build-log entry, the next time someone touches this guard. Against that: the
change does not add a new mandatory control or remove one, it does not change which
address classes are ultimately reachable (§5), and the actual decision-making already
happened in a documented, HITL-gated review this session. On balance this reads as
implementation of an existing ruling rather than a new one — but if a future change
touches `_verify_peer` again, the reasoning in §2 and §5 above should probably graduate
into an ADR rather than being re-derived from a third build-log entry.

## 11. Files changed

- `src/integrations/http_fetcher.py` (`_verify_peer` and its import line only)
- `tests/integrations/test_http_fetcher.py` (new `TestVerifyPeer` class, 5 tests)
- `tests/modules/seo/test_discovery.py` (one new test in `TestGuardrailRefusalOutcome`)
