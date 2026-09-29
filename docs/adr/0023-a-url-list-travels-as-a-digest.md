# ADR 0023: The signed dispatch envelope gains a field, and a URL list travels as a digest

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Screaming Frog's `--crawl` mode follows links, so it audits only what a site
points at. The URLs worth auditing most — orphans, and pages published only in
a sitemap — are by definition the ones it never reaches. This engine already
holds both. `--crawl-list` is the CLI mode that takes them: Screaming Frog
fetches the supplied URLs and does **not** spider outward from them.

Handing that list over means handing a worker desktop a set of addresses it
will fetch. Under [ADR 0015](0015-cloud-local-desktop-worker-architecture.md)
the cloud↔worker hop is untrusted in both directions, and condition 8 makes
worker-side re-validation of whatever the cloud sends load-bearing.

### This reverses a stated position

`WorkerJobEnvelope`'s own docstring said the envelope "deliberately carries
nothing else: no crawl options, no path override, no raw command", matching
`ScreamingFrogJobInput`'s shape exactly plus the transport metadata a network
hop needs. [ADR 0021](0021-no-binary-config-upload-to-a-worker.md) leaned on
that minimality explicitly and pointed at it as a reason a config upload has
nowhere to live. `url_list_sha256` is the first field added since, so this is a
**documented reversal**, not a gap being filled, and it narrows ADR 0015
condition 8: for this one field the worker's re-validation is a digest
comparison, not a semantic re-check of what the digest names.

The reversal is recorded rather than argued away because the next person to
propose an envelope field will cite this one as precedent, and should have to
meet the same bar: a fixed-width, self-authenticating value the worker can
independently verify without trusting the sender.

## Decision

### 1. The list is not carried in the signed claims. A 64-character digest is.

`url_list_sha256` is a lowercase-hex SHA-256, pattern-pinned
(`^[0-9a-f]{64}$`) on `DispatchPreviewToken`, `DispatchAssignmentClaims` and
`WorkerJobEnvelope`. The bytes themselves live in a content-addressed
`worker_dispatch_url_lists` table (migration `0007`) and are fetched by the
worker over its own authenticated, org-scoped channel
(`GET /workers/jobs/{id}/url-list`, `WorkerCloudClient.fetch_url_list`).

Three reasons, in order of weight:

1. **A 10,000-entry list inside an assignment token would make the token
   enormous.** The ceiling below permits 10,000 URLs; at a realistic average
   URL length that is hundreds of kilobytes, inside a base64url-encoded
   artifact minted on every poll, logged, and returned in a poll response body.
   The token is an identity artifact, not a transport.
2. **Signing a digest preserves the property that matters.** ADR 0015
   condition 4 signs one object so that tampering with *either* the envelope
   or the approval invalidates the *same* HMAC. Putting the digest inside
   `DispatchAssignmentClaims` inherits that unchanged — no second signature and
   no change to the HMAC construction in `worker_dispatch_signing.py` — and an
   attacker who substitutes a digest naming a different stored list breaks the
   same signature that protects `seed_url`.
3. **It keeps operator-influenced strings out of a signed, logged artifact.**

The worker therefore compares the downloaded bytes against the digest inside
its own HMAC-verified claims — never against anything the download itself
supplied. That is why `GET /workers/jobs/{id}/url-list` deliberately does
**not** send the digest in a response header: a second copy travelling beside
the bytes is a copy anyone who can alter the bytes can also alter.

### 2. The list is generated and frozen at preview time.

The bytes an operator approves a fingerprint of have to already exist.
Generating at download time would mean the operator approves a fingerprint of
one list and the worker fetches whatever the source crawl says later — or
nothing at all, if that crawl was deleted or re-run in between. The digest is
then bound through all four gates: the cloud preview row, the confirm
statement's own `WHERE` clause, the signed assignment claims, and
`describe_invocation`, which names the crawl, the count and three real URLs,
because a bare hash is not something a human can approve.

### 3. Over the ceiling, refuse. Never trim.

`SCREAMING_FROG_URL_LIST_MAX_URLS` (`Settings.screaming_frog_url_list_max_urls`,
default **10,000**) caps one generated list. Exceeding it raises
`UrlListTooLargeError` and the dispatch is refused with an explanation.

A silently truncated crawl list is worse than a refused one: the approval text
says "N URLs" and the crawl audits fewer, with no signal anywhere that the
difference exists. It would also destroy the free-tier truncation check, which
works by comparing supplied list length against pages actually crawled — the
first check in this codebase able to distinguish "crawled exactly 500 because
that is all there was" from "capped at 500". 10,000 was chosen against real
crawls on this workstation (100,687 / 33,439 / 26,255 pages): every one of them
exceeds it, which is the point. "All Discovered URLs" on a large site is
exactly the request that should have to be reconsidered, and "Orphans Only" is
the smaller, recommended source.

Off-domain URLs are the opposite case: dropped and **counted**, never a reason
to refuse. A crawl of one site routinely holds a handful of outbound links, and
refusing a 10,000-URL list over 18 of them would be useless.

### 4. SSRF validation happens at admission, once per unique netloc.

`UrlSafetyPolicy.validate()` calls `socket.getaddrinfo` and has **no cache**
(`src/core/url_safety.py`). A per-URL check on a 50,000-URL list would be
50,000 blocking DNS lookups inside a request handler, for a list that resolves
one or two names. `url_list._safe_hosts()` therefore validates each distinct
host once and filters the list against the resulting set.

This trades granularity for liveness, and it is sound for the property being
enforced: `UrlSafetyPolicy`'s verdict is a function of the host, not the path.

### 5. The worker does not re-apply `UrlSafetyPolicy` to the entries it downloads.

Verified in `src/modules/seo/screaming_frog_control/worker_url_list.py` at the
time of writing. `prepare_url_list` fetches the bytes, compares
`fingerprint(body)` against `claims.url_list_sha256`, parses with
`read_url_list_file`, refuses an empty list, re-renders as CRLF UTF-8 and
writes the file. There is no `UrlSafetyPolicy` import in that module and no
per-entry host check anywhere on the worker side; `worker_daemon.py` holds a
`UrlSafetyPolicy` and applies it to the **`seed_url`** only.

So the SSRF control on list entries is **cloud-side admission alone**, on the
far side of the hop ADR 0015 calls untrusted. What the digest check does give
is that a worker crawls exactly the bytes a human approved and nothing else:
the substitution case is closed, the "the cloud admitted something it should
not have" case is not independently caught.

Accepted for v1 and stated plainly rather than implied. Adding a worker-side
re-check is a bounded change — the URLs are already parsed inside that same
function — and it is recorded as an obligation below, not as done.

## Alternatives considered

**Carry the URLs in the envelope.** Rejected: see Decision 1. It would also put
arbitrary operator-influenced strings inside the artifact that gets logged.

**Sign a separate "list manifest" object alongside the assignment.** Rejected
for the reason ADR 0015 condition 4 gives for signing one object: two
signatures create a gap where an attacker leaves one intact and forges the
other.

**Trim at the ceiling and report the trim.** Rejected: a reported trim is a
field nothing is obliged to read, and the truncation check below it silently
becomes meaningless. A refusal cannot be ignored.

**Validate every URL individually with `UrlSafetyPolicy`.** Rejected on
liveness (Decision 4), not on principle.

**Generate the list when the worker asks for it.** Rejected: the approval would
no longer bind bytes that exist.

## Consequences

**Accepted.** `WorkerJobEnvelope` is no longer minimal in the sense ADR 0021
relied on. Anyone citing "the envelope carries nothing else" must now cite this
ADR as the exception and argue why theirs would be the second one.

**Accepted.** The digest check is the worker's whole re-validation of the list.
ADR 0015 condition 8 is satisfied in form — the worker verifies independently
and refuses on mismatch, with its own non-transient error type
(`UrlListIntegrityError`) — but not in the fuller sense of re-deriving the
decision the cloud made.

**Accepted.** `PostgresJobStore.iter_result_page_urls` does **not** get the
bounded-memory property `DiskJobStore.iter_result_page_urls` has (5.3 MB peak
against 292 MB, measured on a real 100,687-page result), because Postgres
returns an already-parsed `json` column that is whole in the process before any
of it can be iterated. Acceptable only because ADR 0004 deploys the local
workstation, which uses `DiskJobStore`. Recorded in that method's own docstring
rather than buried here.

**Gained.** `--crawl-list` makes the Screaming Frog free-tier cap detectable for
the first time, because a known supplied length is the missing half of the
comparison. A real 500-URL list that completed is no longer reported as
degraded, and a genuine shortfall is surfaced on the finished job.

**Gained.** One field, not a channel. No engine→worker channel for arbitrary
content was opened; the single new cloud→worker route serves one
content-addressed blob to the one worker a job is pinned to, filtered on
`org_id` in SQL a second time.

**Obligation.** A worker-side `UrlSafetyPolicy` re-check on downloaded list
entries. Until it exists, no document may describe list-mode SSRF protection as
defence in depth.

**Unverified.** Migration `0007` has been rendered for the PostgreSQL dialect
offline but has **not** been executed against a real database — the same
posture migrations 0002–0005 carry.
