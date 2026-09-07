import { Button, Input, Table, Tag, Tooltip } from "antd";
import { useMemo, useState } from "react";
import { finalUrlOf, landsOnHomepage, redirectHops } from "../../lib/audit";
import { downloadCsv, hostSlug, toCsv } from "../../lib/csv";
import type { FullPageIntelligenceProfile } from "../../types/schema";

/**
 * Sitemap entries that redirect, read as a move rather than as a page.
 *
 * The orphan worklist beside this one answers *how was this found?* — the right
 * question when nothing links to a page. It is the wrong one here: a redirect is
 * only actionable once you can see **where it goes**, and the destination is not
 * a column that worklist has. Rendering redirects through it left the finding's
 * whole point off the screen.
 *
 * Three columns carry the decision. The address the sitemap publishes, the
 * address it resolves to, and the number of hops in between — because a chain of
 * three is a different conversation from a single 301, and Google stops
 * following at five.
 */

export function RedirectTable({
  pages,
  baseUrl,
}: {
  pages: FullPageIntelligenceProfile[];
  baseUrl: string;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const [homeOnly, setHomeOnly] = useState(false);

  const homeCount = useMemo(() => pages.filter(landsOnHomepage).length, [pages]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return pages
      .filter((page) => !homeOnly || landsOnHomepage(page))
      .filter(
        (page) =>
          needle === "" ||
          page.url.toLowerCase().includes(needle) ||
          finalUrlOf(page).toLowerCase().includes(needle),
      );
  }, [pages, query, homeOnly]);

  // Exports what is on screen, as every other worklist in this app does. The
  // destination and the hop count are the two columns the generic finding export
  // cannot carry, and they are the reason this file exists.
  const exportCsv = (): void => {
    const csv = toCsv(
      ["url", "redirects_to", "hops", "lands_on_homepage", "page_type", "hierarchy_level"],
      rows.map((page) => [
        page.url,
        finalUrlOf(page),
        redirectHops(page),
        landsOnHomepage(page) ? "yes" : "no",
        page.primary_page_type,
        page.hierarchy_level,
      ]),
    );
    downloadCsv(`${hostSlug(baseUrl)}-sitemap-redirects.csv`, csv);
  };

  return (
    <div className="au-drill">
      <div className="au-tools">
        {/* Offered only when there is something to filter to. A control that
            always returns an empty table is worse than no control. */}
        {homeCount > 0 && (
          <button
            type="button"
            className={`rk-btn${homeOnly ? " rk-btn-primary" : ""}`}
            aria-pressed={homeOnly}
            onClick={() => setHomeOnly(!homeOnly)}
          >
            Lands on homepage ({homeCount.toLocaleString()})
          </button>
        )}
        <Input.Search
          size="small"
          allowClear
          placeholder="Filter by either address"
          aria-label="Filter redirects by URL"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          style={{ width: 220 }}
        />
        <Button size="small" onClick={exportCsv} disabled={rows.length === 0}>
          Export CSV ({rows.length.toLocaleString()})
        </Button>
      </div>

      <Table<FullPageIntelligenceProfile>
        size="small"
        rowKey="url"
        dataSource={rows}
        pagination={{ pageSize: 25, showSizeChanger: true, size: "small" }}
        columns={[
          {
            title: "Listed in the sitemap",
            dataIndex: "url",
            ellipsis: true,
            render: (url: string) => (
              <a href={url} target="_blank" rel="noreferrer noopener" className="au-url">
                {url}
              </a>
            ),
          },
          {
            title: "Resolves to",
            key: "final",
            ellipsis: true,
            render: (_, page) => {
              const destination = finalUrlOf(page);
              return (
                <span className="au-redirect-to">
                  <span aria-hidden="true">→</span>{" "}
                  <a
                    href={destination}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="au-url"
                  >
                    {destination}
                  </a>
                  {landsOnHomepage(page) && (
                    <Tooltip title="Search engines usually read a redirect to the homepage as the page being gone rather than moved, which loses whatever the original ranked for.">
                      <Tag color="error">homepage</Tag>
                    </Tooltip>
                  )}
                </span>
              );
            },
          },
          {
            title: "Hops",
            key: "hops",
            width: 80,
            align: "right",
            sorter: (a, b) => redirectHops(a) - redirectHops(b),
            defaultSortOrder: "descend",
            render: (_, page) => {
              const hops = redirectHops(page);
              // A chain costs a round trip per hop on every crawl. One is
              // ordinary; more than one is worth an analyst's attention, so it
              // is marked rather than left as a number to scan for.
              return hops > 1 ? <Tag color="warning">{hops}</Tag> : hops || "—";
            },
          },
          {
            title: "Type",
            dataIndex: "primary_page_type",
            width: 180,
            sorter: (a, b) => a.primary_page_type.localeCompare(b.primary_page_type),
          },
        ]}
      />
    </div>
  );
}
