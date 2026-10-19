/**
 * The URLs under one directory-tree category, as a CSV.
 *
 * Built from the in-memory model rather than by reading the rendered rows: the
 * list is windowed, so the DOM holds about 25 of 20,000 rows and says nothing
 * about the rest. Walking `kids` reaches every descendant regardless of which
 * sections the analyst has expanded.
 *
 * Client-side for the same reason as `csv.ts`: the rows are already loaded, and
 * a second server-side definition of "the URLs under this category" would be a
 * second place for the two to disagree.
 */
import { toCsv } from "./csv";
import type { DashModel, DashNode } from "./dashboardModel";

/** Column headers. Each maps to a real field: see `categoryCsv` for the source of each cell. */
export const CATEGORY_CSV_HEADERS = ["URL", "Path", "Hierarchy level", "Page type"] as const;

/**
 * Every URL-bearing node at or below `root`, in document order.
 *
 * `kind !== "group"` is the test for "is a URL": a grouping node's `url` is a
 * path the tree invented to hold children, not an address the crawl fetched.
 * A page or a quarantined defaulter is a URL and is included; a group is not.
 * Iterative, for the same stack-depth reason as `buildDashModel`.
 */
export function categoryPages(model: DashModel, root: number): DashNode[] {
  const out: DashNode[] = [];
  const stack: number[] = [root];
  while (stack.length > 0) {
    const node = model.nodes[stack.pop()!];
    if (!node) continue;
    if (node.kind !== "group") out.push(node);
    // Pushed in reverse so the stack pops children in their own order.
    for (let k = node.kids.length - 1; k >= 0; k -= 1) stack.push(node.kids[k]!);
  }
  return out;
}

/**
 * A cell that a spreadsheet would evaluate as a formula is prefixed with `'`.
 *
 * `csv.ts` quotes delimiters but does not neutralise formulas, and crawled
 * paths are attacker-influenced text: a `=` or `@` at the start of a cell opens
 * as a formula in Excel. Applied here, not in `csv.ts`, so the existing exports
 * keep their bytes.
 */
function neutralise(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
}

/**
 * The CSV for the category rooted at `root`: one header row, then one row per URL.
 *
 * Cells are the node's own fields. `Path` is `normalized_path` and the last two
 * columns are the profile's `hierarchy_level` and `primary_page_type`. A
 * quarantined defaulter has no profile, so its last three cells are empty
 * rather than invented.
 */
export function categoryCsv(model: DashModel, root: number): string {
  const rows = categoryPages(model, root).map((node) =>
    [
      node.url,
      node.profile?.normalized_path ?? "",
      node.profile?.hierarchy_level ?? "",
      node.profile?.primary_page_type ?? "",
    ].map(neutralise),
  );
  return toCsv(CATEGORY_CSV_HEADERS, rows);
}

/** `urls-<slug>.csv` for a category label, with a stable fallback for an empty slug. */
export function categoryFilename(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `urls-${slug || "category"}.csv`;
}
