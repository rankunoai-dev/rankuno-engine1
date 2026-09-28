# ADR 0019: An export bundle decides its own job status; an empty or spine-less bundle is not a success

- **Status**: Accepted
- **Date**: 2026-09-28
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Under ADR 0015 a Screaming Frog crawl runs on a desktop worker and its exports
travel to the cloud as a zip. `POST /workers/jobs/{id}/upload` was the only place
that decides what a worker's run *meant*, and it decided on the wrong evidence: it
validated the archive's structure (member names against
`ALLOWED_BUNDLE_FILENAMES`, sizes, member count — ADR 0015 condition 9 and
ADR 0018), stored it, and called `mark_uploaded(job_id, bundle_size_bytes=...)`.
`mark_uploaded` already accepted `partial: bool`, and its only caller never passed
it, so every structurally valid archive became `SUCCEEDED` regardless of what was
in it. `WorkerJobStatus.PARTIAL` was consequently unreachable, and its own
docstring said so.

A zip with zero members is structurally valid. It is 22 bytes: an
End-of-Central-Directory record and nothing else.

On 2026-09-24 and 2026-09-25 two real crawls, of 1:05:47 and 1:47:39, were killed
by a misfiring orphan reaper — one at 99.7% complete — and both reported
`SUCCEEDED` with a 22-byte download attached. Screaming Frog writes nothing to
`--output-folder` until a crawl completes, so a kill near the end leaves an empty
folder, which becomes an empty bundle, which became a successful job. The reaper
defect is fixed separately (build-log 0113 §3.3); this ADR is about the fact that
nothing downstream noticed, and would not have noticed any other cause of an empty
export either.

The status is not cosmetic. It is what the dashboard shows, what an operator uses
to decide whether to re-run an hour-long crawl, and what any future automation
reading `WorkerJob.status` will branch on.

## Decision

**The contents of an uploaded bundle determine the job's terminal status. The
cloud decides; the worker does not assert.**

1. **Zero members → `FAILED`, and the bundle is not stored.** A valid archive with
   nothing in it is not a finished crawl. The bytes are discarded deliberately:
   offering a 22-byte download is the failure being removed, and storing it would
   preserve it behind a different label.
2. **Members present, `internal_all.csv` absent → `PARTIAL`, and the bundle is
   stored.** The spine is required non-optionally by
   `load_screaming_frog_bundle` (`screaming_frog_adapter.py`, `SPINE_FILE`), so a
   bundle without it can never produce a deliverable however many other files it
   carries. The data is still worth keeping and downloading; what it is not is a
   clean finish.
3. **Members present including the spine → `SUCCEEDED`.**
4. **All three return HTTP `200`.** The status code answers "was this upload
   report accepted?", not "did the crawl work?". `WorkerCloudClient.upload_bundle`
   calls `raise_for_status()`, so a 4xx becomes a daemon-side exception about a
   job that is already terminal and that no retry can improve. The report was
   accepted; the job failed; those are two different claims and only the first
   belongs in the status line.
5. **A non-`SUCCEEDED` transition carries an operator-facing reason**, written to
   the same `error` column `mark_failed` uses — the one the dashboard already
   reads. `mark_uploaded` therefore takes `reason: str | None = None` on both the
   `WorkerDispatchStore` protocol and `PostgresWorkerDispatchStore`. Without it,
   `WorkerJobsPanel.tsx` renders `job.error ?? "No reason was recorded."` beside a
   `PARTIAL` row, which replaces a wrong status with a mute one.
6. **The worker names what the cloud cannot see.** Two different failures produce
   zero uploadable files — a crawl that never reached its export phase, and an
   output folder whose files are all outside the allow-list — and they need
   different people to act. Only the daemon holds both counts, so the daemon
   refuses to upload an empty archive and reports the distinguishing reason
   itself (`files=0, skipped=0` versus `files=0, skipped=N`).

`WorkerJobStatus.PARTIAL` thereby acquires exactly one reachable trigger. Its
original licence-degrade meaning is retained in the docstring as a second,
still-unreached case.

## Alternatives considered

**Leave the status alone and fix only the reaper.** Rejected. The reaper was one
cause of an empty export; a crashed JVM, a full disk, a cancelled run or a future
supervision bug produce the same artefact. A status that is derived from evidence
survives causes nobody has thought of yet.

**Return `400` for an empty bundle.** Rejected, and this is the part most likely
to be "corrected" later by someone reading the rule cold. `raise_for_status()` in
`WorkerCloudClient.upload_bundle` turns any 4xx into an exception on the daemon,
which then treats a terminal job as an upload it should complain about or retry.
Nothing about the crawl improves. The refusal semantics that *do* belong on this
route — an unlisted member, an oversized body, a truncated archive — remain `400`
and `413`, because in those cases the *report* really is malformed.

**Have the worker assert the status.** Rejected on ADR 0015's own footing: a
worker is untrusted input. It may report *evidence* (what it wrote, what it
skipped) and the cloud decides what that evidence means. Condition 9's validation
already rests on this and would be inconsistent otherwise.

**Introduce a new status for "empty".** Rejected. `FAILED` with a specific reason
carries the same information, and every consumer — the dashboard, the job list
filter, any future automation — already handles `FAILED`. A new enum member is a
migration and a branch in every consumer, bought for nothing.

**Store the empty bundle anyway, for forensics.** Rejected. There is nothing in it
to examine; the forensic value is in the worker's log lines and the audit trail,
both of which were kept and extended. A downloadable 22-byte artefact is purely a
way to waste an operator's time twice.

## Consequences

**Positive**

- An hour-long crawl that produced nothing can no longer be reported as a success,
  whatever killed it.
- `WorkerJobStatus.PARTIAL` becomes a real status with a defined trigger rather
  than a documented dead letter.
- Three distinct failure signatures are distinguishable in the logs
  (`files=0, skipped=0`, `files=0, skipped=N`, `members=N, spine_present=false`)
  rather than one generic "empty".
- Part of ADR 0018's follow-up is discharged: allow-list drift now reaches the
  cloud as a job failure reason instead of living only in a desktop log.

**Negative**

- The spine rule is a single-filename dependency. If `SPINE_FILE` ever changes, or
  a future deliverable path stops needing it, this rule silently becomes either
  too strict or meaningless. `SPINE_FILENAME` is exported from
  `upload_manifest.py` and derived from `SPINE_TAB` precisely so there is one
  place to change, but nothing tests the two definitions against each other.
- A job that previously read `SUCCEEDED` in the database still does. This is not
  retroactive, and the two incidents that prompted it remain mislabelled in any
  store that holds them.
- The direct, non-worker `ScreamingFrogControlTool.execute()` path is untouched.
  It still returns success for a killed crawl, because it never examines exit
  status and `SupervisedProcess` exposes none (build-log 0113 §6.1). This ADR
  covers the cloud upload boundary only.

**Follow-up**

- Make `execute()` verify the spine exists in `bundle_dir` before returning
  success, which would apply the same rule at source and cover the direct path.
- A two-way test that `SPINE_FILENAME` and `screaming_frog_adapter.SPINE_FILE`
  still name the same file, in the shape of ADR 0018's drift test.
