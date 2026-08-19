import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { LANE_LABELS, type DashModel } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";

/** Hits rendered. Beyond this the list stops being scannable, not just slow. */
const MAX_HITS = 40;

/** Below this length nearly everything matches, so the dropdown is noise. */
const MIN_QUERY = 2;

const LANE_CLASS = ["p0", "p1", "p2", "p3", "po"];

interface Props {
  model: DashModel;
}

/**
 * Jump straight to any URL in the crawl, without expanding the tree by hand.
 *
 * A linear scan over a pre-lowercased index rather than a fuzzy matcher. At
 * 20,000 entries a substring scan is well under a frame, and it stops early at
 * `MAX_HITS`; the total is counted separately so the footer can say how many
 * matched rather than implying 40 was all of them.
 */
export function TeleportSearch({ model }: Props): JSX.Element {
  const [query, setQuery] = useState("");
  const [openList, setOpenList] = useState(false);
  const [cursor, setCursor] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const setFocus = useDashboardStore((state) => state.setFocus);

  // Deferred so typing stays responsive: React can abandon a superseded scan
  // instead of blocking the keystroke behind it.
  const deferred = useDeferredValue(query);

  const { hits, total } = useMemo(() => {
    const needle = deferred.trim().toLowerCase();
    if (needle.length < MIN_QUERY) return { hits: [] as number[], total: 0 };

    const found: number[] = [];
    let matched = 0;
    for (let index = 0; index < model.index.length; index += 1) {
      if (!model.index[index]!.includes(needle)) continue;
      matched += 1;
      if (found.length < MAX_HITS) found.push(index);
    }
    return { hits: found, total: matched };
  }, [deferred, model]);

  useEffect(() => setCursor(0), [deferred]);

  // Dismiss on an outside click. Without this the dropdown covers the tree and
  // there is no obvious way to get rid of it.
  useEffect(() => {
    function onDocumentClick(event: MouseEvent): void {
      if (!container.current?.contains(event.target as Node)) setOpenList(false);
    }
    document.addEventListener("mousedown", onDocumentClick);
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, []);

  function jump(index: number): void {
    setFocus(index, model);
    setOpenList(false);
    setQuery("");
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Escape") {
      setOpenList(false);
      return;
    }
    if (!hits.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => (value + 1) % hits.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => (value - 1 + hits.length) % hits.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = hits[cursor];
      if (target !== undefined) jump(target);
    }
  }

  const visible = openList && deferred.trim().length >= MIN_QUERY;

  return (
    <div className="search" ref={container}>
      <input
        value={query}
        // "nodes", not "URLs". The index covers grouping nodes too — menu
        // sections that are not themselves pages — and those have no URL of
        // their own; `dashboardModel` falls back to the section path. On
        // kinsta.com 1,592 of the 29,248 were structural, so the old wording
        // overstated the crawl by that much against a KPI card reading 27,656
        // on the same screen.
        placeholder={`Teleport-search ${model.nodes.length.toLocaleString()} nodes…`}
        aria-label="Search all nodes"
        autoComplete="off"
        onChange={(event) => {
          setQuery(event.target.value);
          setOpenList(true);
        }}
        onFocus={() => setOpenList(true)}
        onKeyDown={onKeyDown}
      />

      {visible && (
        <div className="hits">
          {hits.map((index, position) => {
            const node = model.nodes[index]!;
            return (
              <button
                key={index}
                type="button"
                className={`hit${position === cursor ? " cursor" : ""}`}
                onClick={() => jump(index)}
              >
                <span className={`lvchip ${LANE_CLASS[node.lv]}`}>{LANE_LABELS[node.lv]}</span>
                <span className="hu">{node.url}</span>
                <span className="hn">{node.label}</span>
              </button>
            );
          })}
          <div className="more">
            {total === 0
              ? "No matches"
              : `${total.toLocaleString()} matches across ${model.nodes.length.toLocaleString()} nodes — showing first ${hits.length}`}
          </div>
        </div>
      )}
    </div>
  );
}
