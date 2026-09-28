import { useEffect, useState } from "react";
import type { CrawlActivityView, CrawlDataAdapter } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { useAuthStore } from "../../store/useAuthStore";
import { useCrawlStore } from "../../store/useCrawlStore";

/** Poll cadence while the tab is in front of the operator. */
export const VISIBLE_POLL_MS = 10_000;
/**
 * Poll cadence while the tab is hidden.
 *
 * Slowed rather than paused: a hidden tab that never polls shows a stale count
 * for the first moment it is looked at, and the visibility handler already
 * fetches immediately on return, so the slow tick only bounds server load.
 */
export const HIDDEN_POLL_MS = 60_000;
/** Failures back off exponentially from the base cadence, up to this ceiling. */
export const MAX_BACKOFF_MS = 5 * 60_000;

function cadence(): number {
  return document.visibilityState === "visible" ? VISIBLE_POLL_MS : HIDDEN_POLL_MS;
}

/**
 * The org-wide count of running crawls, kept fresh in the background.
 *
 * Returns `null` until a first good answer arrives, and again whenever polling
 * is not possible (signed out, or an adapter with no `getCrawlActivity`). The
 * caller renders "unavailable" for `null`; this hook never throws and never
 * raises a toast, because a header badge that shouts about its own failure is
 * worse than one that quietly keeps its last value.
 *
 * Requests are chained with `setTimeout` rather than fired from a
 * `setInterval`, so a slow response can never be overtaken by the next tick.
 * A `401` stops polling outright: `authorizedFetch` has already run the
 * session-expired handler, which signs the user out and disables this hook.
 */
export function useCrawlActivity(): CrawlActivityView | null {
  const adapter = useCrawlStore((state) => state.adapter);
  const authenticated = useAuthStore((state) => state.token !== null);
  const [activity, setActivity] = useState<CrawlActivityView | null>(null);

  const canPoll = authenticated && adapter?.getCrawlActivity !== undefined;

  useEffect(() => {
    if (!canPoll || adapter === null) {
      // Another operator's org counts must not linger after a sign-out.
      setActivity(null);
      return undefined;
    }
    return startPolling(adapter, setActivity);
  }, [canPoll, adapter]);

  return activity;
}

/** Runs the poll loop for one adapter and returns its teardown. */
function startPolling(
  adapter: CrawlDataAdapter,
  publish: (value: CrawlActivityView) => void,
): () => void {
  let stopped = false;
  let inFlight = false;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const schedule = (): void => {
    clearTimeout(timer);
    if (stopped) return;
    const delay = Math.min(cadence() * 2 ** failures, MAX_BACKOFF_MS);
    timer = setTimeout(() => void poll(), delay);
  };

  const poll = async (): Promise<void> => {
    if (stopped || inFlight || adapter.getCrawlActivity === undefined) return;
    inFlight = true;
    clearTimeout(timer);
    try {
      const value = await adapter.getCrawlActivity();
      if (stopped) return;
      failures = 0;
      publish(value);
    } catch (error) {
      if (stopped) return;
      if (error instanceof ApiError && error.status === 401) {
        // Dead session: the shared handler is already tearing it down. Retrying
        // would only send more requests the server is certain to refuse.
        stopped = true;
        return;
      }
      failures += 1;
    } finally {
      inFlight = false;
    }
    schedule();
  };

  const onVisibilityChange = (): void => {
    if (stopped) return;
    if (document.visibilityState === "visible") {
      // Back in front: do not make the operator wait out the slow tick. Backoff
      // is forgiven too, since it was earned while nobody was looking.
      failures = 0;
      void poll();
    } else if (!inFlight) {
      schedule();
    }
  };

  document.addEventListener("visibilitychange", onVisibilityChange);
  void poll();

  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}
