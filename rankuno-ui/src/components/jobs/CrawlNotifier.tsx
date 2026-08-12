import { Button, notification } from "antd";
import { useEffect, useRef } from "react";
import type { JobStatus } from "../../adapters/adapterInterface";
import { hostOf } from "../../lib/url";
import { isLive, useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";

/**
 * Announce background crawls as they finish.
 *
 * Renders nothing. It exists because a crawl completing must *not* change what
 * is on screen: the operator may be halfway through reading another site's
 * tree, and replacing it without being asked discards that work. A notification
 * offers the result and lets them decide when to take it.
 *
 * The diffing lives here rather than in the store so that `useCrawlStore` stays
 * free of antd — the store is the one part of this UI that could be tested
 * without a DOM.
 */
export function CrawlNotifier(): JSX.Element | null {
  const liveJobs = useCrawlStore((state) => state.liveJobs);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const loadCheckpoint = useCrawlStore((state) => state.loadCheckpoint);
  const jobs = useCrawlStore((state) => state.jobs);
  const setView = useUiStore((state) => state.setView);

  const [api, contextHolder] = notification.useNotification();

  /*
   * Statuses as of the previous render, so a transition can be spotted.
   *
   * Seeded on the first pass rather than left empty: a page reload with a
   * finished job still in the map would otherwise fire a notification for a
   * crawl that ended before the component existed.
   */
  const seen = useRef<Map<string, JobStatus> | null>(null);

  useEffect(() => {
    if (seen.current === null) {
      seen.current = new Map(Object.values(liveJobs).map((job) => [job.id, job.status]));
      return;
    }

    for (const job of Object.values(liveJobs)) {
      const before = seen.current.get(job.id);
      seen.current.set(job.id, job.status);

      // Only the crossing from live to finished is an event. Without the
      // `before` check every poll of an already-finished job would re-notify.
      if (before === undefined || !wasLive(before) || isLive(job)) continue;

      const summary = jobs.find((entry) => entry.id === job.id);
      const recoverable = summary?.recoverable === true;
      const host = hostOf(job.label);

      const open = (): void => {
        void (async () => {
          if (recoverable) await loadCheckpoint(job.id);
          else await selectJob(job.id);
          setView("visualizer");
          api.destroy(job.id);
        })();
      };

      if (job.status === "failed" && !recoverable) {
        api.error({
          key: job.id,
          message: `Crawl failed — ${host}`,
          description: job.error ?? job.message,
          // Sticky. A failure the operator did not see is a crawl they will
          // sit waiting for.
          duration: 0,
        });
        continue;
      }

      const pages = job.telemetry?.completed ?? 0;
      api.open({
        key: job.id,
        type: job.status === "succeeded" ? "success" : "warning",
        message: recoverable
          ? `Crawl failed, partial tree saved — ${host}`
          : job.status === "partial"
            ? `Crawl stopped early — ${host}`
            : `Crawl complete — ${host}`,
        description:
          pages > 0
            ? `${pages.toLocaleString()} pages fetched.`
            : "No pages were fetched over the network.",
        duration: 8,
        btn: (
          <Button size="small" type="primary" onClick={open}>
            {recoverable ? "Open partial tree" : "Open tree"}
          </Button>
        ),
      });
    }
  }, [liveJobs, jobs, api, selectJob, loadCheckpoint, setView]);

  return contextHolder;
}

/**
 * Whether a status is one a job can still leave.
 *
 * Takes a bare status rather than a `LiveJob`, which is why it cannot reuse
 * `isLive`: only the previous status was retained, not the whole entry.
 */
function wasLive(status: JobStatus): boolean {
  return status === "queued" || status === "running";
}
