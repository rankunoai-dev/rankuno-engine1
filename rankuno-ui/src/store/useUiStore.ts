import { create } from "zustand";

/**
 * Every rail destination, as a value and not a type alone.
 *
 * `RailView` is derived from this tuple so the runtime list and the compile-time
 * union cannot drift. Restoring the view from `localStorage` has to check a
 * string of unknown provenance against the real set of destinations, and a
 * hand-maintained second copy of that set is precisely what goes stale when a
 * view is renamed or retired — leaving the restore trusting a name nothing
 * renders any more.
 */
export const RAIL_VIEWS = [
  "launch",
  "visualizer",
  "jobs",
  "audit",
  "gsc-accounts",
  "screaming-frog",
] as const;

/** Which rail destination is on screen. */
export type RailView = (typeof RAIL_VIEWS)[number];

/**
 * Which product the operator is working in.
 *
 * The engine and Screaming Frog are separate tools with separate job systems;
 * the rail shows one product's destinations at a time so that neither is read
 * as part of the other.
 */
export type ProductMode = "engine" | "screaming-frog";

/** The views that belong to the engine, in rail order. */
export type EngineView = Exclude<RailView, "launch" | "screaming-frog">;

interface UiState {
  view: RailView;
  /** Where "back to the engine" lands, instead of always the visualizer. */
  lastEngineView: EngineView;
  /**
   * A crawl the operator asked to run through Screaming Frog in list mode,
   * or `null`.
   *
   * A one-shot request, not a selection: the Screaming Frog launcher reads it
   * once, opens itself on that crawl, and calls `clearListCrawl`. Left
   * standing it would re-arm list mode every time the operator came back to
   * that screen, which is a crawl setting they did not ask for a second time.
   *
   * Deliberately not persisted. It is an intent formed by one click, and a
   * reload two days later restoring it would point the launcher at a crawl
   * nobody remembers choosing. The storage subscription below writes `view`
   * and nothing else, so this cannot leak into `localStorage`.
   */
  listCrawlSourceJobId: string | null;
  setView: (view: RailView) => void;
  /** Enter a product from the Launch screen, landing on its main view. */
  enterMode: (mode: ProductMode) => void;
  /**
   * Open the Screaming Frog launcher in list mode, on this crawl's URLs.
   *
   * Carries a `/jobs` id — a crawl this engine ran — never a `/workers/jobs`
   * dispatch id. It navigates as well as arming the request, because the two
   * are one operator action ("run these there") and splitting them would let
   * a caller arm it without going anywhere.
   */
  startListCrawl: (jobId: string) => void;
  /** Consume the request, so returning to the launcher does not re-apply it. */
  clearListCrawl: () => void;
}

/**
 * The product a view belongs to, or `null` for Launch, which is shared.
 *
 * The only source of truth for "which product is on screen". There is
 * deliberately no stored mode beside it: a mode field that could be set
 * independently of the view is what put the engine's rail and header over the
 * Launch chooser, because Launch belongs to neither product and the stored
 * value answered for it.
 */
export function modeOfView(view: RailView): ProductMode | null {
  if (view === "launch") return null;
  return view === "screaming-frog" ? "screaming-frog" : "engine";
}

const STORAGE_KEY = "rankuno.ui";

/** What is kept in `localStorage`. No identity, no credentials — one view name. */
interface StoredUi {
  view: RailView;
}

/** Whether a value out of storage names a destination this build still has. */
function isRailView(value: unknown): value is RailView {
  return typeof value === "string" && (RAIL_VIEWS as readonly string[]).includes(value);
}

/** The engine view to return to, for a restored view that is one. */
function engineViewOf(view: RailView | null): EngineView | null {
  if (view === null || view === "launch" || view === "screaming-frog") return null;
  return view;
}

/**
 * The view a previous session left open, or `null`.
 *
 * Nothing that comes out of `localStorage` is trusted: it can be from an older
 * build that had a view this one does not, hand-edited, truncated by a quota
 * error mid-write, or not JSON at all. Anything that is not a currently
 * rendered destination reads as no stored view, and the app opens on the
 * chooser exactly as a first-ever visit does.
 */
function readStoredView(): RailView | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredUi>;
    return isRailView(parsed?.view) ? parsed.view : null;
  } catch {
    return null;
  }
}

function writeStoredView(view: RailView): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view } satisfies StoredUi));
  } catch {
    // Private mode, a full quota, or storage disabled outright. The session
    // still navigates; it only fails to survive a reload, which is a smaller
    // loss than a rail button that throws.
  }
}

/*
 * Rail navigation, kept out of the other two stores on purpose.
 *
 * `useDashboardStore` holds the derived tree view-model, which is rebuilt from
 * a 20,000-node walk. Putting the current tab in there would make every
 * subscriber to that store re-render on a tab change, which is precisely the
 * coupling the crawl/dashboard split was introduced to avoid.
 *
 * No router: there is one window, a handful of destinations, and no URLs to be
 * deep linked to. A router would add a dependency and a build step to express
 * an enum.
 *
 * Persisted, and `view` alone. A reload used to drop the operator back on the
 * Launch chooser from wherever they were, which reads as the application
 * forgetting what it was doing. Every piece of product chrome derives from the
 * view through `modeOfView`, so there is no second field a restore could
 * contradict — which is the same reason the deleted `lastMode` is not coming
 * back. `lastEngineView` is not stored either: it is re-derived from the
 * restored view, so it can never disagree with it across a reload.
 *
 * `launch` is the opening view rather than `visualizer`. A session starts with
 * nothing loaded, and the visualizer's answer to that was one line of grey text
 * — which left "how do I start a crawl?" answered only by a button in the
 * header. The two crawlers are also genuinely different tools with separate job
 * systems, and a screen that names both is what keeps that distinction visible
 * instead of hidden behind one ambiguous "New crawl".
 *
 * Launch shows no product's destinations at all. It used to fall back to the
 * last product used, which put the engine's five tabs on the chooser; the way
 * into the engine without starting a crawl is now a control on the engine card
 * itself, so a rail that shows nothing strands nobody — including in fixture
 * mode, where no crawl can be started but the bundled results still open.
 */
const restoredView = readStoredView();

export const useUiStore = create<UiState>((set) => ({
  view: restoredView ?? "launch",
  // Derived from the restored view rather than stored beside it, so "back to
  // the engine" after a reload lands on the engine view that is actually on
  // screen instead of a default that contradicts it.
  lastEngineView: engineViewOf(restoredView) ?? "visualizer",
  setView: (view) =>
    set(() => {
      // Only an engine view is remembered: "back to the engine" must never
      // land on Launch or on the other product.
      if (view === "launch" || view === "screaming-frog") return { view };
      return { view, lastEngineView: view };
    }),
  enterMode: (mode) =>
    set((state) => ({
      view: mode === "engine" ? state.lastEngineView : "screaming-frog",
    })),
  listCrawlSourceJobId: null,
  startListCrawl: (jobId) => set(() => ({ view: "screaming-frog", listCrawlSourceJobId: jobId })),
  clearListCrawl: () => set(() => ({ listCrawlSourceJobId: null })),
}));

/*
 * One writer, subscribed rather than called from each action.
 *
 * `setView` and `enterMode` are not the only ways the view moves — tests set it
 * directly, and any action added later would have to remember to persist. A
 * subscription is the one place that cannot be forgotten, and it writes only on
 * an actual change, so an unrelated store write costs no storage round trip.
 */
useUiStore.subscribe((state, previous) => {
  if (state.view !== previous.view) writeStoredView(state.view);
});
