# ADR 0021: A browser may not upload a `.seospiderconfig` to a worker; a description may travel instead

- **Status**: Accepted
- **Date**: 2026-09-28
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

RAE — the system this engine replaces — has a config-upload panel: an operator picks a
`.seospiderconfig` file in a browser, types a description beside it, and the file lands in the
template directory on a worker desktop. It is a screenshot away, it is obviously useful, and the
request to build it will recur.

It cannot be built here as drawn, for two reasons that are structural rather than scheduling.

### 1. The file format defeats the re-validation ADR 0015 requires

A `.seospiderconfig` is a Java `ObjectInputStream`-serialised blob. This was confirmed against a
real Screaming Frog crash log's "invalid stream header" error, and
`src/modules/seo/screaming_frog_control/template_registry.py:1-14` has said so since it was written:
this codebase cannot author one, validate its contents, or fabricate a placeholder Screaming Frog
would accept.

[ADR 0015](0015-cloud-local-desktop-worker-architecture.md) condition 8 makes worker-side
re-validation of what the cloud hands a worker load-bearing — the worker never trusts the cloud's
say-so, it independently verifies. For a file whose format this system cannot parse, that
re-validation is not *unimplemented*; there is no implementation to write. The worker could confirm
a signature over the bytes, which proves who sent them, and nothing whatever about what they are.

What the bytes then do is not incidental either. The file is deserialised by a JVM on the operator's
desktop, outside any sandbox this engine controls, by a third-party binary
(`ScreamingFrogSEOSpiderCli.exe`) whose deserialisation behaviour is not ours to reason about. Java
deserialisation of untrusted input is a well-known remote-code-execution class. The upload path
would therefore be a channel from a browser session to code execution on a desktop, gated on nothing
this codebase can inspect.

### 2. "Only an admin may upload" is not expressible

The obvious mitigation is to restrict the capability to a small, trusted set of humans.

`Principal` (`src/core/auth.py`, [ADR 0016](0016-cloud-api-authentication.md)) has **no role
field**. Every authenticated operator in an org is equivalent to every other. The policy cannot be
written, so the mitigation is unavailable — not merely unbuilt.

### What the feature was actually for

Separating the two halves of RAE's panel makes the trade obvious. RAE's own help text explains the
description field:

> Config files are binary, so their custom extraction rules cannot be read back on the server. Note
> them here so the next person knows what this config captures.

The operator's real problem is **not knowing what `advance-with-url-parameter` does**. Moving bytes
is how RAE got a config onto a machine; reading a sentence is how an operator picks the right one.
The second is the value, and it carries none of the first's risk.

## Decision

**No engine → worker byte channel exists for configuration files, and none is added without a new
ADR.** Specifically:

1. There is **no upload endpoint** for `.seospiderconfig` or any other opaque binary destined for a
   worker's filesystem.
2. The dispatch envelope chain — `DispatchPreviewRequest` → `DispatchPreviewToken` →
   `DispatchAssignmentClaims` → `WorkerJobEnvelope` → `ScreamingFrogJobInput` — carries a template
   **name** and never template **content**. Any change to that chain is a change to what gate (b)'s
   HMAC signs and is out of scope for a feature request.
3. Populating the template directory stays an operator action performed once, in the real Screaming
   Frog GUI, on the machine that will use it (File > Configuration > Save As).
4. **A description may travel in the opposite direction.** Worker → cloud → browser, as a sidecar
   `<name>.md` beside each config, read as plain text and rendered as a text node. It is
   documentation and never configuration: nothing reads it to decide how a crawl runs. It is treated
   as hostile input at every boundary regardless — length-capped, and refused if it carries control,
   zero-width or bidirectional-override characters.

### The ladder, if this is revisited

The refusal is of the feature *as drawn*, not of the underlying need. Three rungs, in order, each
with a precondition:

| Rung | What | Precondition |
| :--- | :--- | :--- |
| 1 | Descriptions on the templates workers already report | **Done** — build-log 0117 |
| 2 | A hash-pinned allow-list: an operator vets a config once, out of band, and its SHA-256 is recorded; only pinned hashes may be referenced | A vetting step and a record of who vetted what. Still does not let a browser introduce a *new* config |
| 3 | Upload to quarantine, with an explicit human release step on the worker | `Principal` must gain a role field first, so the capability can be restricted. Quarantine must be a directory Screaming Frog is never pointed at |

Rung 3 is the only one that satisfies the original request, and it is gated on a change to the
authentication model, not on anyone's willingness to build it.

## Alternatives considered

**Sign the uploaded bytes and let the worker verify the signature.** Rejected: this proves
provenance, not safety. ADR 0015 condition 8 exists precisely because a signature from the cloud is
not a substitute for the worker forming its own judgement, and a worker cannot form a judgement
about a format it cannot parse. It would convert a structural objection into a false sense of one
having been addressed — the worst available outcome.

**Parse the `.seospiderconfig` so it *can* be validated.** Rejected: it would mean reimplementing a
third-party application's private Java serialisation format, tracking it across Screaming Frog
releases, and being wrong silently when it changes. The format is not documented and is not a
contract Screaming Frog offers.

**Store the config in Postgres and have the worker pull it on dispatch.** Rejected: this is the same
channel with an extra hop. The worker still writes attacker-influenced bytes to its own disk and
hands them to a JVM.

**Restrict uploads to an admin role.** Rejected as currently impossible (see Context 2), and noted
as the precondition for rung 3 rather than discarded.

**Embed the description inside the config file.** Rejected — it is exactly the thing that cannot be
done. The binary cannot be written or read by this codebase, which is the entire reason a
description is needed. Hence the sidecar.

**A shared `descriptions.json` per template directory instead of one sidecar per template.**
Rejected on blast radius: one unparseable JSON file blanks every description at once, whereas a bad
`.md` costs exactly the template it belongs to. Recorded here for completeness; it is a file-format
choice rather than a governance decision, and the reasoning lives in build-log 0117 §3.1 and in
`template_registry.py`'s module docstring.

## Consequences

**Accepted.** An operator must still walk to, or remote into, a desktop to add a template. For a
fleet of a handful of analyst workstations this is a small cost paid rarely; it would not be at a
hundred machines, which is when rung 2 becomes worth its preconditions.

**Accepted.** The template directory is not under version control and was lost once already with no
commit to restore it from (build-log 0117 §6.1). This ADR does not fix that, and fixing it by
committing binary configs to git would reintroduce the same untrusted-blob problem with a different
delivery mechanism.

**Gained.** The dispatch envelope chain is unchanged, so gate (b)'s HMAC covers exactly what it
covered before and ADR 0015's 14 conditions are all still satisfied by the same arguments that
satisfied them originally. A feature that touched the envelope would have required re-arguing all of
them.

**Gained.** The operator's actual question — "what does this config do?" — is answered, by the only
mechanism that can answer it: a human writing it down next to the file.

**Obligation.** Anyone proposing config upload in future is bound to address Context 1 and Context 2
directly. Re-proposing the feature without a parser for the format, or without a role model on
`Principal`, is re-proposing a decision already made.
