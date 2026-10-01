# ADR 0028: Dispatch claims are signed asymmetrically (Ed25519)

**Status**: APPROVED — design approved by the operator after a Step-5 security audit
returned FAIL against the shared-HMAC construction, 2026-10-01.

**Date**: 2026-10-01

**Amends**: [ADR 0015](0015-cloud-local-desktop-worker-architecture.md) condition 4
("HMAC command signing is a tampering/spoofing defense, not an approval mechanism").
Condition 4's *limit* is unchanged — signing still does not defend against a compromised
cloud process, and gate (a) still bounds that. What changes is the mechanism, and with
it who is able to sign.

---

## Context

ADR 0015 gate (b) is the worker's independent check of a signed, expiring,
identity-bound dispatch assignment. It shipped as HMAC-SHA256 under one key,
`WORKER_DISPATCH_SIGNING_SECRET`, held by the cloud **and every worker**:

* the cloud signs in `issue_dispatch_assignment` (`src/core/worker_dispatch_signing.py`),
  called from the poll route in `src/api/worker_routes.py`;
* every worker verifies in `verify_dispatch_assignment`, called from
  `src/modules/seo/screaming_frog_control/worker_daemon.py`;
* `worker_daemon_cli` required the secret on every worker, and
  `scripts/register_worker.py` told the operator to paste "the same secret set in Railway
  variables" and wrote it in plaintext to `.env.local`.

With a symmetric key every verifier is also a signer. Anyone who holds **any** worker's
configuration — a copied `.env.local`, a backup, a support screenshot — can mint a valid
assignment for **any** worker, org, seed URL, template or URL-list digest. Gate (b)
reduced to "whoever has a copy of the config". The worker is about to be distributed as
a downloadable `.exe`; any install flow that ships or prompts for the key would make it
effectively public. The audit verdict was **FAIL until fixed**.

Two smaller findings from the same audit are fixed here because they sit on the same
channel: the worker's cloud client accepted a plain `http://` base URL (sending its
bearer credential and receiving assignments in clear), and `register_worker.py` echoed
raw server error bodies (`resp.text`) to the terminal.

## Decision

1. **Ed25519.** The cloud signs with a private key
   (`WORKER_DISPATCH_SIGNING_PRIVATE_KEY`, `SecretStr`, cloud only). A worker holds only
   the public key (`WORKER_DISPATCH_VERIFY_KEY`, not secret), which can verify an
   assignment and can never produce one. Both are standard base64 of the 32 raw key
   bytes, validated at boot (`src/core/worker_dispatch_keys.py`). `cryptography` is now a
   declared core dependency (it was previously only transitive via `google-auth`).
2. **Key id.** `kid` = first 16 hex chars of SHA-256 of the raw public key — derived, so
   it cannot drift from the key. It travels inside the *signed* protected header. A
   worker rejects any `kid` it does not hold, which is what makes a later rotation
   (two keys published side by side) possible without trial verification.
3. **Envelope.** The wire model `SignedDispatchAssignment` is **unchanged**
   (`{token, expires_at}`): deployed workers parse it with `extra="forbid"`, so a new
   field would make every un-upgraded worker reject every job. The token keeps its three
   segments; the Ed25519 signature rides in the header as a JWS-style detached
   signature:

   ```
   header  = {"alg": "HS256" | "EdDSA", "typ": "RANKUNO-DISPATCH",
              "ed25519": {"protected": b64url({"alg":"EdDSA","typ":"RANKUNO-DISPATCH","kid":kid}),
                          "signature": b64url(Ed25519(protected "." payload))}}
   token   = b64url(header) "." b64url(claims) "." (b64url(HMAC(header "." payload)) | "")
   ```

   The Ed25519 signing input has the same `<b64url header>.<b64url claims>` shape the
   HMAC signs, over the protected header, and over the byte-identical claims segment —
   the claims canonicalisation is unchanged. The legacy HMAC covers the whole outer header
   (including the embedded Ed25519 signature), so an old worker verifies a dual-signed
   token unchanged. With no private key configured, the header is the original
   `{"alg":"HS256","typ":...}` and tokens are exactly what they were before this ADR.
4. **The worker chooses the algorithm from its own configuration, never from the
   token.** If `WORKER_DISPATCH_VERIFY_KEY` is set, the worker demands a valid Ed25519
   signature under a matching `kid` and never reads the HMAC segment — even if the
   legacy secret is also present in its settings. There is no fallback; a fallback would
   preserve the forgery. Only a worker with **no** verify key uses the legacy HMAC path,
   and it logs `worker_dispatch_legacy_hmac_deprecated` at every start.
5. **Fail closed on the cloud.** Production refuses to boot unless a private key is set
   or the legacy secret is set *and* `WORKER_DISPATCH_LEGACY_HMAC_ENABLED` is true.
   `ApiState` refuses to construct, and `issue_dispatch_assignment` refuses to mint, with
   neither. Outside production an unset private key is generated per process (the same
   posture as every other signing key in `Settings`); a random HMAC key is no longer
   emitted, because it could never verify on a separate worker process.
6. **Key distribution.** `GET /api/v1/workers/dispatch-verify-key` returns
   `{algorithm, kid, public_key}` behind operator session auth (`require_principal`).
   It answers `503` on a deployment with no Ed25519 key rather than inventing one.
   `scripts/register_worker.py` fetches it (before registering, so a failure cannot
   orphan a one-time worker credential), checks the `kid` against the key, and writes
   `WORKER_DISPATCH_VERIFY_KEY`. It no longer asks for or writes any signing secret.
   `scripts/generate_dispatch_keypair.py` generates a keypair, prints the private key
   under a SECRET banner and the public key under a PUBLIC one, and writes nothing to disk.
7. **HTTPS.** `WorkerCloudClient` refuses, at construction, a base URL that is not
   `https://` unless the host is `localhost`, `127.0.0.1` or `::1`
   (`require_secure_base_url`, raising `ConfigurationError`). `register_worker.py`
   applies the same rule before prompting for a password, and reports failed responses
   by status code only.

## Transition matrix

| Cloud config | Old worker (HMAC secret only) | New worker (verify key) |
| :--- | :--- | :--- |
| HMAC secret only (today) | works, tokens byte-identical to before | **rejected** — no Ed25519 signature; register refuses with 503 |
| HMAC secret + private key, legacy flag true | works (HMAC covers the new header) | works (Ed25519) |
| Private key, legacy flag false (or secret removed) | **rejected** — empty HMAC segment; upgrade first | works |

A claim minted before deploy is an HMAC-only token and still verifies on an old worker.
Its 300 s TTL bounds any overlap with the switch.

## Operator runbook

1. Run `python scripts/generate_dispatch_keypair.py` on a trusted machine. Copy the
   private key straight into Railway as `WORKER_DISPATCH_SIGNING_PRIVATE_KEY`; clear the
   terminal. Do not store it anywhere else.
2. Deploy. Leave `WORKER_DISPATCH_SIGNING_SECRET` set and
   `WORKER_DISPATCH_LEGACY_HMAC_ENABLED` unset (true): assignments are now dual-signed and
   existing workers keep running.
3. Confirm `GET /api/v1/workers/dispatch-verify-key` returns the expected `kid`.
4. Upgrade each worker: re-run `scripts/register_worker.py` (or set
   `WORKER_DISPATCH_VERIFY_KEY` by hand from step 3) and **delete
   `WORKER_DISPATCH_SIGNING_SECRET` from that worker's `.env.local`**. Restart it; the
   deprecation warning must be gone from its log.
5. When no worker logs `worker_dispatch_legacy_hmac_deprecated`, set
   `WORKER_DISPATCH_LEGACY_HMAC_ENABLED=false` in Railway and redeploy.
6. **Remove `WORKER_DISPATCH_SIGNING_SECRET` from Railway and every machine, and treat
   its value as compromised** — it has lived in plaintext on every worker. Never reuse it
   for anything. Deactivate any worker registration you cannot account for.

Rotating the Ed25519 key later: generate a new pair, deploy it, re-run step 4 for every
worker. Running two keys side by side (publishing both `kid`s) is the path the `kid`
exists for but is **not implemented** — today a rotation is a cut-over.

## Alternatives considered

* **Per-worker HMAC keys.** Removes cross-worker forgery but each worker can still forge
  claims *for itself* (any seed URL, any template), and the cloud must store every key
  recoverably to sign with it — a second credential store with plaintext secrets, which
  ADR 0015 condition 2 forbids for worker credentials. Rejected.
* **mTLS between worker and cloud.** Authenticates the channel, not the claim: it would
  not let the worker verify that *this* assignment was issued by the cloud after gate
  (a), and Railway's edge terminates TLS, so client-certificate auth would need a
  separate ingress. A large operational cost for a property we do not need. Rejected.
* **JWT with RS256 / ES256.** Equivalent security in principle. RS256 keys and
  signatures are large and slow to generate; ECDSA needs a good per-signature nonce
  (a repeated nonce leaks the key). A JWT library would also invite `alg` negotiation
  from the token header — the confusion this design avoids by fixing the algorithm in
  configuration. Ed25519 is deterministic, has 32-byte keys that paste into one
  environment variable, and is already available through `cryptography`.

## Consequences

* A worker's configuration no longer contains signing authority. A leaked `.env.local`
  exposes only that worker's own bearer credential (revocable per worker) and a public key.
* The private key is a single high-value secret on the cloud. ADR 0015 condition 4's
  limit stands: a compromised cloud process can still sign; gate (a) bounds that.
* The verify-key endpoint is trust-on-first-use over operator-authenticated HTTPS.
  A worker trusts whatever key the cloud it registered against returns; pinning a
  fingerprint out of band is possible (`kid` is printed) but not enforced.

## Explicitly not done

* No multi-key / overlapping rotation: the worker holds exactly one verify key.
* No change to replay handling: still TTL plus the worker's local consumed-job ledger.
* The worker `.exe` packaging itself is out of scope.
