import { create } from "zustand";

/**
 * Every dashboard safety banner that can be dismissed, as a value and not a
 * type alone.
 *
 * Derived the same way `RAIL_VIEWS` is, and for the same reason: a dismissal
 * read back out of `localStorage` has to be checked against the banners this
 * build actually renders, and a hand-maintained second copy of that list is
 * what goes stale when a banner is renamed or retired — leaving a stored
 * dismissal silently attached to nothing, or worse, to the wrong finding.
 */
export const NOTICE_IDS = [
  "synthetic",
  "zero-fetch",
  "sitemaps-blocked",
  "stopped-early",
  "gsc",
  "truncated",
  "nav-unparsed",
] as const;

/** Which dashboard banner a dismissal refers to. */
export type NoticeId = (typeof NOTICE_IDS)[number];

const STORAGE_KEY = "rankuno.notices";

/**
 * How many crawls' dismissals are kept.
 *
 * Dismissals accumulate one entry per crawl the operator ever closed a banner
 * on, and nothing in the app ever deletes a crawl from this browser's history,
 * so an unbounded key grows for the lifetime of the profile and eventually
 * costs a JSON parse of it on every boot. Twenty is well past the number of
 * crawls anyone switches between in a working session, and the eviction is
 * least-recently-used, so the ones being worked on are the ones that survive.
 */
const MAX_CRAWLS = 20;

/**
 * The largest stored blob that will even be parsed.
 *
 * Twenty crawls of seven short ids is under 2 KB. Anything an order of
 * magnitude past that was not written by this code, and parsing it to find
 * that out is the cost this bound exists to refuse.
 */
const MAX_RAW_LENGTH = 16_384;

/**
 * What is kept in `localStorage`.
 *
 * An array rather than an object map, because the eviction order *is* data:
 * the entries are ordered least- to most-recently touched, and an object would
 * leave that order to a JSON round trip to preserve. No crawl labels and no
 * URLs — a job id and a banner name, both of which the operator already sees.
 */
interface StoredNotices {
  crawls: { id: string; ids: NoticeId[] }[];
}

/** Whether a value out of storage names a banner this build still renders. */
function isNoticeId(value: unknown): value is NoticeId {
  return typeof value === "string" && (NOTICE_IDS as readonly string[]).includes(value);
}

/**
 * The dismissals a previous session left, oldest crawl first.
 *
 * Nothing that comes out of `localStorage` is trusted: it can be from an older
 * build with banners this one dropped, hand-edited, truncated by a quota error
 * mid-write, grown past the cap by a bug, or not JSON at all. Every one of
 * those reads as *nothing dismissed*, which shows every banner — the safe
 * direction, and the same state a first-ever visit is in. A hidden finding is
 * the failure this whole feature has to avoid, so corruption can only ever
 * fail towards saying more, never towards saying less.
 */
function readStoredNotices(): { id: string; ids: NoticeId[] }[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw || raw.length > MAX_RAW_LENGTH) return [];
    const parsed = JSON.parse(raw) as Partial<StoredNotices>;
    if (!Array.isArray(parsed?.crawls)) return [];

    const clean: { id: string; ids: NoticeId[] }[] = [];
    for (const entry of parsed.crawls) {
      if (typeof entry !== "object" || entry === null) return [];
      const { id, ids } = entry as { id?: unknown; ids?: unknown };
      if (typeof id !== "string" || !id) return [];
      if (!Array.isArray(ids)) return [];
      // Unknown names are dropped rather than failing the whole read: a banner
      // retired in a later build must not cost the operator every dismissal
      // they still have a banner for.
      const known = [...new Set(ids.filter(isNoticeId))];
      if (known.length > 0) clean.push({ id, ids: known });
    }
    // Trimmed from the front, so an over-long stored list loses its oldest
    // crawls rather than being thrown away whole.
    return clean.slice(-MAX_CRAWLS);
  } catch {
    return [];
  }
}

function writeStoredNotices(crawls: { id: string; ids: NoticeId[] }[]): void {
  try {
    if (crawls.length === 0) {
      window.localStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ crawls } satisfies StoredNotices));
  } catch {
    // Private mode, a full quota, or storage disabled outright. The dismissal
    // still holds for this session; it only fails to survive a reload, which
    // is a smaller loss than a close button that throws.
  }
}

interface NoticeState {
  /**
   * Which banners are hidden, keyed by crawl id, least-recently-touched first.
   *
   * Key insertion order carries the eviction order, so a dismissal on a crawl
   * already in the map re-inserts it at the end. Reading is by crawl id, which
   * is what makes a dismissal on one crawl invisible to every other one: a
   * different crawl is a different key, and a key with no entry has nothing
   * hidden.
   */
  dismissed: Record<string, NoticeId[]>;
  /** Hide one banner on one crawl. */
  dismiss: (crawlId: string, notice: NoticeId) => void;
  /** Bring every banner hidden on this crawl back. */
  restoreAll: (crawlId: string) => void;
}

/** The map form, for the store, from the ordered form, for storage. */
function toMap(crawls: { id: string; ids: NoticeId[] }[]): Record<string, NoticeId[]> {
  const map: Record<string, NoticeId[]> = {};
  for (const entry of crawls) map[entry.id] = entry.ids;
  return map;
}

/** The ordered form, for storage, from the map form, for the store. */
function toList(map: Record<string, NoticeId[]>): { id: string; ids: NoticeId[] }[] {
  return Object.entries(map).map(([id, ids]) => ({ id, ids }));
}

/*
 * Banner dismissal, in its own store rather than in `useCrawlStore`.
 *
 * It is not crawl data: the crawl store is cleared and re-populated on every
 * job switch, and a dismissal has to outlive that — including outliving the
 * reload that re-fetches the crawl from the adapter.
 *
 * Scoped per crawl *and* per banner, which is the whole point. "This site has
 * 405 pages" and "I looked at 405 pages of this site" are different claims, and
 * the truncation banner is the only thing on screen that distinguishes them. A
 * dismissal that carried across crawls would answer for a crawl the operator
 * never looked at; a dismissal with no way back would delete the finding
 * outright. Neither is a thing this store can do: the key is the job id, and
 * `restoreAll` is always reachable while anything is hidden.
 */
export const useNoticeStore = create<NoticeState>((set) => ({
  dismissed: toMap(readStoredNotices()),

  dismiss: (crawlId, notice) =>
    set((state) => {
      const current = state.dismissed[crawlId] ?? [];
      if (current.includes(notice)) return state;

      // Rebuilt without this crawl, then re-added, so the key lands at the end
      // and the map's insertion order stays least-recently-touched first.
      const rest = Object.entries(state.dismissed).filter(([id]) => id !== crawlId);
      const kept = rest.slice(-(MAX_CRAWLS - 1));
      return { dismissed: { ...Object.fromEntries(kept), [crawlId]: [...current, notice] } };
    }),

  restoreAll: (crawlId) =>
    set((state) => {
      if (!(crawlId in state.dismissed)) return state;
      // Removed rather than emptied. An entry holding an empty list is a crawl
      // occupying one of the twenty slots while hiding nothing.
      const rest: Record<string, NoticeId[]> = {};
      for (const [id, ids] of Object.entries(state.dismissed)) {
        if (id !== crawlId) rest[id] = ids;
      }
      return { dismissed: rest };
    }),
}));

/*
 * One writer, subscribed rather than called from each action.
 *
 * The same reasoning as `useUiStore` and `useCrawlStore`: tests set this state
 * directly, and any action added later would have to remember to persist. A
 * subscription is the one place that cannot be forgotten, and it writes only
 * when the map actually changes, so an unrelated store write costs no storage
 * round trip.
 */
useNoticeStore.subscribe((state, previous) => {
  if (state.dismissed !== previous.dismissed) writeStoredNotices(toList(state.dismissed));
});
