import type { DashModel } from "../../lib/dashboardModel";
import { reasonLabel, type TreeOverlay } from "../../lib/treeOverlay";
import { useDashboardStore } from "../../store/useDashboardStore";

interface Props {
  model: DashModel;
  overlay: TreeOverlay;
}

/**
 * What sits under OTHERS, and whether anyone is arriving there from search.
 *
 * OTHERS is the residue: pages neither the header menu nor a breadcrumb places.
 * A page there with real Search Console traffic is the finding this panel
 * exists for — either the site has a page people want that no navigation
 * reaches, or the engine put it in the wrong place. Both are the analyst's
 * work, and the two are told apart by opening the page in the inspector.
 *
 * A page under OTHERS that Screaming Frog also missed is the compound case:
 * unplaced *and* unseen by the industry tool. Marked on the row.
 */
export function OthersInsight({ model, overlay }: Props): JSX.Element {
  const crossCheckOn = useDashboardStore((state) => state.crossCheckOn);
  const setFocus = useDashboardStore((state) => state.setFocus);
  const showMisses = crossCheckOn && overlay.crossCheck;
  const { others } = overlay;

  if (!others.applicable) {
    return (
      <div className="xothers">
        <h3>OTHERS</h3>
        <div className="xnote">
          Not applicable: this tree is grouped by URL path, so every page has a position and
          there is no OTHERS bucket. Switch to navigation grouping on a crawl with a parsed
          menu.
        </div>
      </div>
    );
  }

  return (
    <div className="xothers">
      <h3>OTHERS · pages no navigation places</h3>
      <div className="xothers-totals">
        <span>
          <b>{others.pages.toLocaleString()}</b> pages
        </span>
        {showMisses && (
          <span className={others.missed > 0 ? "warn" : ""}>
            <b>{others.missed.toLocaleString()}</b> missed by Screaming Frog
          </span>
        )}
        {overlay.gsc && (
          <span className={others.clicks > 0 ? "warn" : ""}>
            <b>{others.clicks.toLocaleString()}</b> clicks · {Math.round(others.clickShare * 1000) / 10}%
            of the site's
          </span>
        )}
      </div>

      {/* The tree's OTHERS row shows its own subtree only; every locale root
          has an OTHERS of its own beneath it, and this panel counts them all.
          Naming the split is what stops the two figures reading as a bug. */}
      {others.byRoot.length > 1 && (
        <div className="xothers-roots">
          <span className="dim">across {others.byRoot.length} roots:</span>
          {others.byRoot.map((root) => (
            <button
              key={root.i}
              type="button"
              className="xroot"
              title={`${root.pages.toLocaleString()} OTHERS pages under ${root.label}${showMisses ? ` · ${root.missed.toLocaleString()} missed by Screaming Frog` : ""}${overlay.gsc ? ` · ${root.clicks.toLocaleString()} clicks` : ""}. Click to focus.`}
              onClick={() => setFocus(root.i, model)}
            >
              <b>{root.label}</b> {root.pages.toLocaleString()}
              {overlay.gsc && <span className="dim"> · {root.clicks.toLocaleString()} clicks</span>}
            </button>
          ))}
        </div>
      )}

      <table className="xtable">
        <thead>
          <tr>
            <th>Bucket</th>
            <th className="num">Pages</th>
            {showMisses && <th className="num">Missed by SF</th>}
            {overlay.gsc && <th className="num">Clicks</th>}
            {overlay.gsc && <th className="num">Impressions</th>}
            {overlay.gsc && <th className="num">With GSC rows</th>}
          </tr>
        </thead>
        <tbody>
          {others.buckets.map((bucket) => (
            <tr key={bucket.label}>
              <td>{bucket.label}</td>
              <td className="num">{bucket.pages.toLocaleString()}</td>
              {showMisses && (
                <td className={`num${bucket.missed > 0 ? " warn" : ""}`}>
                  {bucket.missed.toLocaleString()}
                </td>
              )}
              {overlay.gsc && <td className="num">{bucket.clicks.toLocaleString()}</td>}
              {overlay.gsc && <td className="num">{bucket.impressions.toLocaleString()}</td>}
              {overlay.gsc && <td className="num dim">{bucket.gscPages.toLocaleString()}</td>}
            </tr>
          ))}
        </tbody>
      </table>

      {overlay.gsc ? (
        <>
          <h4>
            Most clicked OTHERS pages
            <span className="dim"> · why is each one here?</span>
          </h4>
          {others.topPages.length === 0 ? (
            <div className="xnote">No OTHERS page has a click. The bucket is unplaced, and unvisited.</div>
          ) : (
            <table className="xtable">
              <thead>
                <tr>
                  <th className="num">Clicks</th>
                  <th className="num">Impr.</th>
                  <th>Page</th>
                  <th>Bucket</th>
                  {showMisses && <th>Screaming Frog</th>}
                </tr>
              </thead>
              <tbody>
                {others.topPages.map((page) => (
                  <tr key={page.i}>
                    <td className="num">
                      <b>{page.clicks.toLocaleString()}</b>
                    </td>
                    <td className="num dim">{page.impressions.toLocaleString()}</td>
                    <td>
                      <button
                        type="button"
                        className="xlink"
                        title="Open in the inspector"
                        onClick={() => setFocus(page.i, model)}
                      >
                        {pathOf(page.url)}
                      </button>
                      {page.locale && <span className="xlocale">{page.locale}</span>}
                    </td>
                    <td>{page.type}</td>
                    {showMisses && (
                      <td>
                        {page.mark === "missed" && (
                          <span className="xmark xmark-missed" title={page.reason ?? ""}>
                            missed · {reasonLabel(page.reason ?? "unknown")}
                          </span>
                        )}
                        {page.mark === "added" && (
                          <span className="xmark xmark-added">added from SF</span>
                        )}
                        {page.mark === "none" && <span className="dim">found by both</span>}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ) : (
        <div className="xnote">
          No Search Console figures on this crawl. Connect the property under Jobs and re-run
          the crawl to see which OTHERS pages carry traffic.
        </div>
      )}
    </div>
  );
}

function pathOf(url: string): string {
  try {
    const { pathname, search } = new URL(url);
    return `${pathname}${search}`;
  } catch {
    return url;
  }
}
