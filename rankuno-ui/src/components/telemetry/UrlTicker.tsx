import { useLayoutEffect, useRef } from "react";
import "./telemetry.css";

interface Props {
  urls: readonly string[];
  /** Rows tall. The jobs table shows a shorter stream than a detail panel. */
  compact?: boolean;
}

/**
 * The most recently fetched URLs, newest at the bottom.
 *
 * Auto-scrolls only when the user is already at the bottom. Yanking the view
 * down while someone is reading an earlier line makes the panel unusable.
 *
 * Extracted from `LiveCrawlProgressModal` when that modal was removed; the
 * scroll-pinning behaviour is carried over unchanged, because it was the part
 * of that component worth keeping.
 */
export function UrlTicker({ urls, compact = false }: Props): JSX.Element {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useLayoutEffect(() => {
    const element = box.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  }, [urls]);

  return (
    <div
      className={`tel-stream${compact ? " tel-compact" : ""}`}
      ref={box}
      onScroll={(event) => {
        const element = event.currentTarget;
        pinned.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 24;
      }}
    >
      {urls.length === 0 ? (
        <div className="tel-line tel-idle">waiting for the first page…</div>
      ) : (
        urls.map((url, index) => (
          <div
            key={`${url}-${index}`}
            className={`tel-line${index === urls.length - 1 ? " tel-newest" : ""}`}
          >
            <span className="tel-dot" />
            {url}
          </div>
        ))
      )}
    </div>
  );
}
