import { useCallback, useEffect, useRef, useState } from "react";
import {
  LEVEL_BADGE,
  TRAIL_SOURCE_BADGE,
  type DashModel,
  type DashNode,
} from "../../lib/dashboardModel";
import { reasonLabel } from "../../lib/treeOverlay";
import { useDashboardStore } from "../../store/useDashboardStore";
import { FullScreenTree } from "./FullScreenTree";
import { TreeControls } from "./TreeControls";
import { useActiveOverlay, useTreeOverlay } from "./useTreeOverlay";
import "./tree-overlay.css";

/** Row height in pixels. Fixed, which is what makes the window arithmetic O(1). */
const ROW = 30;

/** Rows rendered beyond each edge of the viewport, to hide scroll latency. */
const OVERSCAN = 3;

const LANE_CLASS = ["p0", "p1", "p2", "p3", "po"];

interface Props {
  model: DashModel;
}

/**
 * The directory tree card's contents: cross-check controls, the windowed list,
 * and the full-screen view it can open.
 *
 * The overlay is built here, once, and published to the store — this is the
 * one component always mounted while a tree is on screen.
 */
export function VirtualizedTree({ model }: Props): JSX.Element {
  const overlay = useTreeOverlay(model);
  return (
    <>
      <TreeControls model={model} overlay={overlay} />
      <TreeList model={model} />
      <FullScreenTree model={model} overlay={overlay} />
    </>
  );
}

interface ListProps {
  model: DashModel;
  /** Room for Search Console figures on the row. Only the full-screen view has it. */
  wide?: boolean;
}

/**
 * The directory tree, windowed to roughly 25 rows in the DOM.
 *
 * Only rows intersecting the viewport are mounted; the rest exist solely as
 * scroll height on a spacer. Without this the tree mounts 20,000 rows on first
 * paint and the tab stops responding — the failure is total rather than gradual,
 * which is why this is the one component in the app with hand-written
 * virtualization rather than a library.
 *
 * The flattened view-model lives in the store and is rebuilt only when the tree
 * or a filter changes. Rebuilding it per scroll frame would defeat the point.
 */
export function TreeList({ model, wide = false }: ListProps): JSX.Element {
  const flat = useDashboardStore((state) => state.flat);
  const open = useDashboardStore((state) => state.open);
  const focus = useDashboardStore((state) => state.focus);
  const toggleOpen = useDashboardStore((state) => state.toggleOpen);
  const setFocus = useDashboardStore((state) => state.setFocus);
  const expandBranch = useDashboardStore((state) => state.expandBranch);
  const collapseBranch = useDashboardStore((state) => state.collapseBranch);
  const active = useActiveOverlay(model);
  // Search Console figures need the overlay for the arrays but not the
  // toggle: they are facts about the crawl, not about the cross-check.
  const overlay = useDashboardStore((state) => state.overlay);
  const gsc = wide && overlay && overlay.model === model && overlay.gsc ? overlay : null;

  const viewport = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState({ start: 0, end: 40 });

  const recompute = useCallback(() => {
    const element = viewport.current;
    if (!element) return;
    const start = Math.max(0, Math.floor(element.scrollTop / ROW) - OVERSCAN);
    const end = Math.min(
      flat.length,
      Math.ceil((element.scrollTop + element.clientHeight) / ROW) + OVERSCAN,
    );
    setRange((previous) =>
      previous.start === start && previous.end === end ? previous : { start, end },
    );
  }, [flat.length]);

  useEffect(recompute, [recompute, flat]);

  // Scroll the focused row into view when selection arrives from elsewhere —
  // teleport search, a graph node, a breadcrumb. Without this, selecting a node
  // 12,000 rows down highlights a row nobody can see.
  //
  // Only when the *selection* moves. This used to run on every `flat` change
  // too, and opening any section re-flattens the tree — so with OTHERS
  // selected (the last root, off-screen) every twisty click "revealed" it and
  // threw the list to the bottom. `flat` is still read, because the row's
  // position is only known from it; the ref is what stops a re-flatten from
  // counting as a new selection.
  const revealed = useRef<number | null>(null);
  useEffect(() => {
    const element = viewport.current;
    if (!element || focus === null || revealed.current === focus) return;
    const position = flat.findIndex((row) => row.i === focus);
    if (position < 0) return;
    revealed.current = focus;

    const top = position * ROW;
    const visible = top >= element.scrollTop && top + ROW <= element.scrollTop + element.clientHeight;
    if (!visible) {
      element.scrollTop = Math.max(0, top - element.clientHeight / 2);
      recompute();
    }
  }, [focus, flat, recompute]);

  const onScroll = useCallback(() => {
    // rAF-coalesced: a trackpad fires scroll far more often than the browser
    // paints, and setting state per event drops frames for no visual gain.
    requestAnimationFrame(recompute);
  }, [recompute]);

  const rows = [];
  for (let position = range.start; position < range.end; position += 1) {
    const row = flat[position];
    if (!row) continue;
    const node = model.nodes[row.i];
    if (!node) continue;

    const hasChildren = node.kids.length > 0;
    const mark = active?.crossCheck ? active.mark[node.i] ?? "none" : "none";
    const missed = active?.crossCheck ? active.missedCnt[node.i] ?? 0 : 0;
    const added = active?.crossCheck ? active.addedCnt[node.i] ?? 0 : 0;
    const reason = active ? active.reason[node.i] : null;
    rows.push(
      /* A `div` with the button role rather than a `<button>`: the label on a
         page row is a real `<a href>`, and an anchor inside a button is invalid
         HTML that browsers repair by splitting the button in two. Enter and
         Space are wired by hand to keep what the element gave for free. */
      <div
        key={node.i}
        role="button"
        tabIndex={0}
        className={`vrow${focus === node.i ? " sel" : ""}${mark === "none" ? "" : ` x${mark}`}`}
        style={{ top: position * ROW, paddingLeft: 10 + row.depth * 16 }}
        onClick={() => setFocus(node.i, model)}
        onKeyDown={(event) => {
          // Only when the row itself has focus. The same keys on the link
          // inside are the link's own activation and must reach it untouched.
          if (event.target !== event.currentTarget) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          setFocus(node.i, model);
        }}
      >
        <span
          className={`tw${open.has(node.i) ? " open" : ""}`}
          title={hasChildren ? "Click to open one level · Shift-click for the whole branch" : ""}
          onClick={(event) => {
            // Stop the row's own select handler: expanding a branch and moving
            // the focus are different intentions.
            event.stopPropagation();
            // Shift is the power path for the same intention the ⇊ button
            // carries. Both exist because the button is discoverable and the
            // modifier is fast, and an analyst opening a 2,937-node section
            // one level at a time is doing it 30 times.
            if (event.shiftKey && hasChildren) {
              if (open.has(node.i)) collapseBranch(node.i, model);
              else expandBranch(node.i, model);
              return;
            }
            toggleOpen(node.i, model);
          }}
        >
          {hasChildren ? "▶" : ""}
        </span>
        <LevelChip node={node} />
        {/* A crawled page links to itself; a path segment has no page to open.
            The click stops here so opening the page does not also move the
            selection — reading a page and pointing at a row are different
            intentions, the same split the twisty makes. */}
        {node.profile ? (
          <a
            className="tlbl tlink"
            href={node.profile.url}
            target="_blank"
            rel="noreferrer noopener"
            title={`Open ${node.profile.url} in a new tab`}
            onClick={(event) => event.stopPropagation()}
          >
            {node.label}
          </a>
        ) : (
          <span className="tlbl">{node.label}</span>
        )}
        {/* On the page's own row. A section row carries the count instead —
            a badge on every row of a 784-page miss would say nothing. */}
        {mark === "missed" && !hasChildren && (
          <span
            className="xmark xmark-missed"
            title={`Rankuno found this page; Screaming Frog did not. Reason: ${reasonLabel(reason ?? "unknown")}`}
          >
            SF missed
          </span>
        )}
        {mark === "added" && !hasChildren && (
          <span
            className="xmark xmark-added"
            title="Screaming Frog found this page; Rankuno's crawl did not. Merged in from the export."
          >
            from SF
          </span>
        )}
        {/* Only on section headers. On a leaf the badge would repeat on every
            row and stop carrying information; the drawer states it per page. */}
        {hasChildren && model.hasProvenance && (
          <span
            className={`srcdot src-${node.src}`}
            title={`Section built from: ${TRAIL_SOURCE_BADGE[node.src]}`}
          >
            {TRAIL_SOURCE_BADGE[node.src]}
          </span>
        )}
        {/* Whole-branch control, revealed on hover so it costs no width until
            wanted. A `span` rather than a `button` because the row carries the
            button role and a control nested inside a button is invalid — the
            same reason the twisty above is a span. */}
        {hasChildren && (
          <span
            className="tbranch"
            title={
              open.has(node.i)
                ? `Collapse ${node.label} and everything under it`
                : `Expand ${node.label} and everything under it (${node.cnt.toLocaleString()} pages)`
            }
            onClick={(event) => {
              event.stopPropagation();
              if (open.has(node.i)) collapseBranch(node.i, model);
              else expandBranch(node.i, model);
            }}
          >
            {open.has(node.i) ? "⇈" : "⇊"}
          </span>
        )}
        {hasChildren && <span className="tcnt">{node.cnt.toLocaleString()}</span>}
        {/* Subtree figures, beside the subtree page count they qualify. */}
        {hasChildren && missed > 0 && (
          <span
            className="tmiss"
            title={`${missed.toLocaleString()} of ${node.cnt.toLocaleString()} pages in this section and below were not found by Screaming Frog`}
          >
            · {missed.toLocaleString()} missed
          </span>
        )}
        {hasChildren && added > 0 && (
          <span
            className="tadded"
            title={`${added.toLocaleString()} pages in this section and below were merged in from the Screaming Frog export`}
          >
            · {added.toLocaleString()} from SF
          </span>
        )}
        {gsc && (gsc.gscPages[node.i] ?? 0) > 0 && (
          <span
            className="tgsc"
            title={`${(gsc.clicks[node.i] ?? 0).toLocaleString()} clicks · ${(gsc.impressions[node.i] ?? 0).toLocaleString()} impressions${hasChildren ? " in this section and below" : ""}`}
          >
            {(gsc.clicks[node.i] ?? 0).toLocaleString()} clicks
          </span>
        )}
      </div>,
    );
  }

  return (
    <>
      <div className="vtree" ref={viewport} onScroll={onScroll}>
        <div className="vspacer" style={{ height: flat.length * ROW }}>
          {rows}
        </div>
      </div>
      <div className="treefoot">
        <span>{flat.length.toLocaleString()} rows in view-model</span>
        {active?.integrity && (
          /* pages − missed − added against the sidecar's own in_both. A
             mismatch means the two files disagree, and that is worth a mark
             in the footer rather than a silently wrong count. */
          <span
            title={`Pages on screen minus those marked, against the cross-check's own "found by both" count (${active.integrity.expected.toLocaleString()})${active.unmatched > 0 ? `. ${active.unmatched.toLocaleString()} missed URLs matched no page.` : ""}`}
          >
            cross-check{" "}
            {active.integrity.actual === active.integrity.expected && active.unmatched === 0
              ? "✓"
              : `✗ ${active.integrity.actual.toLocaleString()} ≠ ${active.integrity.expected.toLocaleString()}`}
          </span>
        )}
        <span>
          DOM rows: <b>{rows.length}</b> / {model.nodes.length.toLocaleString()}
        </span>
      </div>
    </>
  );
}

/**
 * The level badge for one row.
 *
 * Reads the engine's `hierarchy_level` when the page was classified, and falls
 * back to the lane only for a node the crawl never produced a profile for —
 * an intermediate path segment that is not itself a page.
 *
 * This used to render the lane unconditionally. With no header menu the lane is
 * URL-path depth, so every single-segment URL on a flat site showed `L0` while
 * the engine had classified it `L3_LEAF_PAGE`. The correct answer was already
 * in the payload; the row was showing a different number.
 */
function LevelChip({ node }: { node: DashNode }): JSX.Element {
  const level = node.profile?.hierarchy_level;

  // No profile means no page was crawled at this URL — it is a path segment
  // the tree needed in order to hold its children. It gets a neutral mark, not
  // a level.
  //
  // It used to fall back to the lane number, which produced the collision that
  // exposed this: under `global-presence`, the crawled entries showed `L3`
  // (their classification) while the uncrawled `asia` showed `L1` (its depth).
  // Two different scales in identically-shaped chips reads as a hierarchy
  // error, and there is no way to tell from the chip which scale you are
  // looking at.
  if (level === undefined) {
    return (
      <span
        className="lvchip lvpath"
        title="URL path segment — no page was crawled at this address"
      >
        ·
      </span>
    );
  }

  const badge = LEVEL_BADGE[level];
  return (
    <span className={`lvchip ${LANE_CLASS[badge.lane]}`} title={`Classified ${level}`}>
      {badge.label}
    </span>
  );
}
