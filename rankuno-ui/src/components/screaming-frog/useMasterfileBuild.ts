import { message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import type { CrawlDataAdapter, MasterfileService } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { saveBlob } from "../../lib/download";

/** The four adapter methods a masterfile build needs, all optional on the adapter. */
export type MasterfileAdapter = Pick<
  CrawlDataAdapter,
  "listAvailableMasterfiles" | "buildMasterfile" | "getDeliverable" | "downloadDeliverable"
>;

/** The job a masterfile is built from: a Screaming Frog WORKER job, never a native crawl. */
export interface MasterfileTarget {
  /** `WorkerJobView.id`. The build route refuses any other kind of id with a 409. */
  id: string;
  /** ISO timestamp used only to date the saved filename. */
  when: string | null | undefined;
}

/** Same cadence the build menu used before it moved here: one poll a second. */
export const POLL_INTERVAL_MS = 1_000;
/** Sixty polls, so a build that has not finished after about a minute is reported. */
export const MAX_POLL_ATTEMPTS = 60;

export interface MasterfileBuild {
  /** Services the server offers; empty until loaded, or if the list failed. */
  services: readonly MasterfileService[];
  /** Whether this adapter can build at all. Fixtures cannot, so the control is absent. */
  supported: boolean;
  /** Whether this service is currently building for this job. */
  isBuilding: (jobId: string, slug: string) => boolean;
  /** Build, poll and save. Never rejects: failures surface through `message.error`. */
  build: (target: MasterfileTarget, service: MasterfileService) => Promise<void>;
}

/**
 * Build a masterfile for a finished Screaming Frog job and save it.
 *
 * Extracted from the native crawl table, which sent a native crawl id that the
 * backend refuses with a 409: masterfiles are built from an uploaded Screaming
 * Frog bundle, and only a worker job has one. The polling behaviour is
 * unchanged: `buildMasterfile` returns a deliverable id, `getDeliverable` is
 * polled once a second up to 60 times, `has_result` means done and a `failed`
 * status ends it early.
 *
 * The download goes through `downloadDeliverable`, a bearer-authenticated
 * fetch returning a `Blob`, then `saveBlob`. Never an `<a href>`: a navigation
 * cannot carry the `Authorization` header (build-log 0103).
 *
 * Progress is tracked per job and service, so one build does not lock every
 * other button. Timers are cleared when the component unmounts so a closed
 * tab of the dashboard does not keep polling.
 */
export function useMasterfileBuild(api: MasterfileAdapter | null): MasterfileBuild {
  const [services, setServices] = useState<readonly MasterfileService[]>([]);
  const [inFlight, setInFlight] = useState<ReadonlySet<string>>(() => new Set());
  // Mirrors `inFlight` synchronously: two clicks in one tick would both see an
  // empty state and start two builds.
  const inFlightRef = useRef<Set<string>>(new Set());
  const mounted = useRef(true);
  const sleepers = useRef<Map<number, () => void>>(new Map());

  useEffect(() => {
    mounted.current = true;
    const pending = sleepers.current;
    return () => {
      mounted.current = false;
      for (const [timer, wake] of pending) {
        window.clearTimeout(timer);
        wake();
      }
      pending.clear();
    };
  }, []);

  useEffect(() => {
    if (!api?.listAvailableMasterfiles) return;
    let cancelled = false;
    void (async () => {
      try {
        const listed = await api.listAvailableMasterfiles?.();
        if (!cancelled && listed) setServices(listed);
      } catch {
        // The list failing hides the control rather than raising an error on a
        // tab that is mostly about something else.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api]);

  const sleep = useCallback((ms: number): Promise<void> => {
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        sleepers.current.delete(timer);
        resolve();
      }, ms);
      sleepers.current.set(timer, resolve);
    });
  }, []);

  const setBusy = useCallback((key: string, busy: boolean): void => {
    if (busy) inFlightRef.current.add(key);
    else inFlightRef.current.delete(key);
    if (mounted.current) setInFlight(new Set(inFlightRef.current));
  }, []);

  const build = useCallback(
    async (target: MasterfileTarget, service: MasterfileService): Promise<void> => {
      const buildFn = api?.buildMasterfile;
      const getFn = api?.getDeliverable;
      const downloadFn = api?.downloadDeliverable;
      if (!api || !buildFn || !getFn || !downloadFn) return;

      const key = flightKey(target.id, service.slug);
      if (inFlightRef.current.has(key)) return;
      setBusy(key, true);

      let stage: "build" | "poll" = "build";
      try {
        const deliverableId = await buildFn.call(api, target.id, service.slug);
        stage = "poll";

        for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
          if (!mounted.current) return;
          const record = await getFn.call(api, deliverableId);

          if (record.has_result) {
            const blob = await downloadFn.call(api, deliverableId);
            if (!mounted.current) return;
            saveBlob(masterfileFilename(service.slug, target), blob);
            message.success(`${service.label} downloaded.`);
            return;
          }
          if (record.status === "failed") {
            message.error(record.error || `The ${service.label} masterfile failed to build.`);
            return;
          }
          await sleep(POLL_INTERVAL_MS);
        }
        if (mounted.current) {
          message.error(`The ${service.label} masterfile timed out. Please try again.`);
        }
      } catch (cause) {
        if (mounted.current) {
          message.error(describeMasterfileError(cause, service.label, stage));
        }
      } finally {
        setBusy(key, false);
      }
    },
    [api, setBusy, sleep],
  );

  const isBuilding = useCallback(
    (jobId: string, slug: string): boolean => inFlight.has(flightKey(jobId, slug)),
    [inFlight],
  );

  const supported =
    api?.buildMasterfile !== undefined &&
    api.getDeliverable !== undefined &&
    api.downloadDeliverable !== undefined;

  return { services, supported, isBuilding, build };
}

function flightKey(jobId: string, slug: string): string {
  return `${jobId}\u0000${slug}`;
}

/** `<service>-<first 8 of id>-<date>.xlsx`, the shape the old menu saved. */
export function masterfileFilename(slug: string, target: MasterfileTarget): string {
  const stamp = target.when ? target.when.slice(0, 10) : "undated";
  return `${slug}-${target.id.slice(0, 8)}-${stamp}.xlsx`;
}

/**
 * A sentence for a failed build.
 *
 * The status mapping applies only to the request that starts the build: those
 * codes mean something specific there (no bundle, expired bundle, quota), and
 * the same code from a status poll would mean something else entirely.
 */
export function describeMasterfileError(
  cause: unknown,
  label: string,
  stage: "build" | "poll",
): string {
  if (cause instanceof ApiError && stage === "build") {
    if (cause.status === 409) return "This crawl has no uploaded bundle to build from.";
    if (cause.status === 410) return "The bundle has expired.";
    if (cause.status === 429) {
      return "The server is busy building masterfiles. Try again in a moment.";
    }
  }
  if (cause instanceof Error && cause.message) return cause.message;
  return `The ${label} masterfile could not be built.`;
}
