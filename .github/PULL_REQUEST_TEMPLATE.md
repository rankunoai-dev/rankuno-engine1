# Summary

<!-- What changed and why, in two or three sentences. -->

## SDLC Compliance

Every box must be ticked or explicitly struck through with a reason. See
[docs/SDLC_GUIDELINES.md](../docs/SDLC_GUIDELINES.md).

- [ ] **1. Investigation** — Verified existing code/files before writing new ones. No duplicate capability introduced.
- [ ] **2. Architecture & schemas** — Pydantic models defined for every data boundary.
- [ ] **3. HITL review** — Architecture was approved by an operator before implementation began.
- [ ] **4. Implementation plan** — Target files and logic were planned before coding.
- [ ] **5. Security / rate-limit / cost audit** — Completed; findings recorded below.
- [ ] **6. Modular implementation** — Code is typed, modular, and lands in the correct layer.
- [ ] **7. Automated verification** — `scripts/verify.ps1` (or `make verify`) exits zero. Output pasted below.
- [ ] **8. Documentation drift audit** — README.md and docs/ARCHITECTURE.md reflect reality.

## Risk & Guardrail Review

- **Highest `RiskClass` introduced or changed:** <!-- READ / DRAFT / WRITE / FINANCIAL -->
- **New external API calls:** <!-- service, endpoint, documented quota -->
- **Rate-limit key used:** <!-- must be shared with any other tool on the same quota -->
- **Estimated cost per invocation (USD):** <!-- 0.00 if free -->
- **New credentials required:** <!-- must be added to .env.example, never committed -->

Any tool classified `WRITE` or `FINANCIAL` requires an explicit reviewer sign-off
in the comments below, not just a ticked box.

## Verification Output

```text
<!-- Paste the tail of scripts/verify.ps1 / make verify here. -->
```

## Documentation Changed

<!-- List the docs updated, or state why none were needed. A PR touching module
     structure, tool signatures, or environment settings with no doc change will
     be failed by the drift-audit workflow. -->
