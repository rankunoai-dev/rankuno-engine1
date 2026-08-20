import { Button, Input, Table, Tag, Tooltip } from "antd";
import { useMemo, useState } from "react";
import { suggestedSurvivor } from "../../lib/audit";
import { downloadCsv, hostSlug, toCsv } from "../../lib/csv";
import type { FullPageIntelligenceProfile } from "../../types/schema";

/**
 * Duplicate URL sets, one row per page rather than one row per URL.
 *
 * The unit of work is the cluster. An analyst does not decide 1,920 URLs; they
 * decide 262 pages, and for each one the question is which address survives and
 * which get pointed at it. A flat list loses exactly the relationship the
 * finding is about, which is why the drill-down expands into members instead of
 * listing every URL at the top level.
 *
 * The export follows the same shape: every URL is a row, but the rows are
 * ordered by cluster and carry the cluster's id, so opening it in a spreadsheet
 * shows the copies of a page adjacent to each other rather than scattered
 * across 1,920 lines.
 */

interface GroupRow {
  key: string;
  /** Stable 1-based id, so a spreadsheet row can be discussed by number. */
  id: number;
  survivor: FullPageIntelligenceProfile;
  members: FullPageIntelligenceProfile[];
  /**
   * Whether the copies contradict each other about their own parent section.
   *
   * Called out because it changes what fixing this costs. Where the breadcrumbs
   * agree, a canonical tag settles it. Where they disagree, the site is also
   * publishing two different answers to "what section is this in?", and picking
   * a survivor picks one of those answers too.
   */
  conflicting: boolean;
}

function trailOf(page: FullPageIntelligenceProfile): string {
  return page.breadcrumb_path.join(" › ");
}

export function DuplicateTable({
  groups,
  baseUrl,
}: {
  groups: FullPageIntelligenceProfile[][];
  baseUrl: string;
}): JSX.Element {
  const [query, setQuery] = useState("");

  const rows = useMemo<GroupRow[]>(() => {
    return groups.flatMap((members, index) => {
      const survivor = suggestedSurvivor(members);
      if (!survivor) return [];
      const trails = new Set(members.map(trailOf).filter((trail) => trail !== ""));
      return [
        {
          key: survivor.url,
          id: index + 1,
          survivor,
          members,
          conflicting: trails.size > 1,
        },
      ];
    });
  }, [groups]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return rows;
    return rows.filter((row) =>
      row.members.some((page) => page.url.toLowerCase().includes(needle)),
    );
  }, [rows, query]);

  // One row per URL, ordered by cluster. The `group` column is what clubs the
  // copies together once the file is open — sorting or filtering on it in a
  // spreadsheet keeps a page's addresses in one block.
  const exportCsv = (): void => {
    const csv = toCsv(
      [
        "group",
        "action",
        "url",
        "inbound_internal_links",
        "page_type",
        "breadcrumb",
        "breadcrumbs_disagree",
      ],
      visible.flatMap((row) =>
        row.members.map((page) => [
          row.id,
          page.url === row.survivor.url ? "keep (suggested)" : "redirect or canonical",
          page.url,
          page.inbound_internal_links_count,
          page.primary_page_type,
          trailOf(page),
          row.conflicting ? "yes" : "no",
        ]),
      ),
    );
    downloadCsv(`${hostSlug(baseUrl)}-duplicate-urls.csv`, csv);
  };

  const urlCount = visible.reduce((sum, row) => sum + row.members.length, 0);

  return (
    <div className="au-drill">
      <div className="au-tools">
        <Input.Search
          size="small"
          allowClear
          placeholder="Filter by URL"
          aria-label="Filter duplicate sets by URL"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          style={{ width: 220 }}
        />
        <Button size="small" onClick={exportCsv} disabled={visible.length === 0}>
          Export CSV ({urlCount.toLocaleString()} URLs)
        </Button>
        <span className="au-hint">
          Opens in Excel. One row per URL, grouped so a page&rsquo;s copies sit together.
        </span>
      </div>

      <Table<GroupRow>
        size="small"
        rowKey="key"
        dataSource={visible}
        pagination={{ pageSize: 20, showSizeChanger: true, size: "small" }}
        expandable={{
          // Expanded rather than nested columns: the members differ only by
          // address, so showing them under the survivor reads as the choice it
          // actually is.
          expandedRowRender: (row) => (
            <ul className="au-members">
              {row.members.map((page) => (
                <li key={page.url}>
                  <Tag color={page.url === row.survivor.url ? "success" : "default"}>
                    {page.url === row.survivor.url ? "keep" : "point here"}
                  </Tag>
                  <a href={page.url} target="_blank" rel="noreferrer noopener" className="au-url">
                    {page.url}
                  </a>
                  <span className="au-member-meta">
                    {page.inbound_internal_links_count} inbound
                    {trailOf(page) !== "" && ` · ${trailOf(page)}`}
                  </span>
                </li>
              ))}
            </ul>
          ),
        }}
        columns={[
          { title: "#", dataIndex: "id", width: 60 },
          {
            title: (
              <Tooltip
                title={
                  "Suggested by inbound internal links, then shortest path — not read " +
                  "from rel=canonical, because a site that had set that correctly would " +
                  "not show this finding. Check it before acting."
                }
              >
                Keep (suggested)
              </Tooltip>
            ),
            key: "survivor",
            ellipsis: true,
            render: (_, row) => (
              <a
                href={row.survivor.url}
                target="_blank"
                rel="noreferrer noopener"
                className="au-url"
              >
                {row.survivor.url}
              </a>
            ),
          },
          {
            title: "Copies",
            key: "copies",
            width: 90,
            sorter: (a, b) => a.members.length - b.members.length,
            defaultSortOrder: "descend",
            render: (_, row) => row.members.length,
          },
          {
            title: "Breadcrumbs",
            key: "conflict",
            width: 130,
            filters: [
              { text: "Disagree", value: true },
              { text: "Agree", value: false },
            ],
            onFilter: (value, row) => row.conflicting === value,
            render: (_, row) =>
              row.conflicting ? (
                <Tag color="warning">disagree</Tag>
              ) : (
                <span className="au-more">—</span>
              ),
          },
        ]}
      />
    </div>
  );
}
