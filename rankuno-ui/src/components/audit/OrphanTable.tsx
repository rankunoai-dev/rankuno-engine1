import { Button, Input, Segmented, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { orphanKind, type OrphanKind } from "../../lib/audit";
import { downloadCsv, hostSlug, toCsv } from "../../lib/csv";
import type { FullPageIntelligenceProfile } from "../../types/schema";

/**
 * The full orphan list, as a worklist rather than a statistic.
 *
 * The finding card above it says how many there are; this says which ones. An
 * analyst handing work to a content team needs the URLs, the section each one
 * belongs to and a file they can open in a spreadsheet — a count and five
 * examples is a claim, not a deliverable.
 *
 * Filtered by discovery source first, because that is the only filter that
 * changes the recommendation. A sitemap orphan is published and unlinked and
 * should be linked or de-listed. A CMS-only orphan was never published at all,
 * and telling a client to "add internal links" to a page no sitemap carries is
 * advice that will not survive contact with their developer.
 */

const KIND_LABEL: Record<OrphanKind, string> = {
    sitemap: "Sitemap",
    cms: "CMS only",
    unlinked: "Crawl only",
};

const KIND_COLOUR: Record<OrphanKind, string> = {
    sitemap: "warning",
    cms: "default",
    unlinked: "default",
};

const KIND_HELP: Record<OrphanKind, string> = {
    sitemap:
        "Listed in a sitemap and linked from nowhere. Published to search engines, hidden from visitors — the finding worth acting on.",
    cms: "Present in the CMS database only. Never published in a sitemap and never linked, so it may be a draft or a retired record.",
    unlinked:
        "Reached during the crawl but holding no inbound link of its own. Usually a page whose only linker was never fetched — check before reporting it.",
};

type Filter = "all" | OrphanKind;

/**
 * Whether this crawl recorded which path found each URL.
 *
 * Crawls stored before the profile carried these flags deserialise with all
 * three false, which is indistinguishable from "found by no path at all" — so
 * every orphan in an old result would be labelled `Crawl only` and the split
 * would read as a finding about the site instead of a gap in the data. A view
 * that quietly mislabels a thousand pages is worse than one that declines to
 * split them, so the control is withdrawn and the reason is stated.
 */
function hasProvenance(pages: readonly FullPageIntelligenceProfile[]): boolean {
    return pages.some(
        (item) =>
            item.discovery_sources.sitemap ||
            item.discovery_sources.dom_link ||
            item.discovery_sources.cms_api,
    );
}

export function OrphanTable({
    pages,
    baseUrl,
}: {
    pages: FullPageIntelligenceProfile[];
    baseUrl: string;
}): JSX.Element {
    const [filter, setFilter] = useState<Filter>("all");
    const [query, setQuery] = useState("");
    const known = useMemo(() => hasProvenance(pages), [pages]);

    const counts = useMemo(() => {
        const tally: Record<OrphanKind, number> = {
            sitemap: 0,
            cms: 0,
            unlinked: 0,
        };
        for (const page of pages) tally[orphanKind(page)] += 1;
        return tally;
    }, [pages]);

    const rows = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return pages
            .filter((page) => filter === "all" || orphanKind(page) === filter)
            .filter(
                (page) =>
                    needle === "" || page.url.toLowerCase().includes(needle),
            );
    }, [pages, filter, query]);

    // Exports what is on screen, not the whole set. An analyst who filtered to
    // sitemap orphans and then exported everything would send a client 1,000 rows
    // they deliberately excluded, and nothing in the file would say so.
    const exportCsv = (): void => {
        const csv = toCsv(
            [
                "url",
                "orphan_kind",
                "page_type",
                "hierarchy_level",
                "sitemap_source",
                "topical_category",
            ],
            rows.map((page) => [
                page.url,
                orphanKind(page),
                page.primary_page_type,
                page.hierarchy_level,
                page.sitemap_source,
                page.topical_category,
            ]),
        );
        downloadCsv(
            `${hostSlug(baseUrl)}-orphans${filter === "all" ? "" : `-${filter}`}.csv`,
            csv,
        );
    };

    // Withdrawn rather than blanked when the crawl predates the flags: a column
    // of identical grey tags is a claim about the site that the data cannot make.
    const kindColumn: ColumnsType<FullPageIntelligenceProfile> = known
        ? [
              {
                  title: "Why",
                  key: "kind",
                  width: 120,
                  filters: (["sitemap", "cms", "unlinked"] as const).map(
                      (kind) => ({
                          text: KIND_LABEL[kind],
                          value: kind,
                      }),
                  ),
                  onFilter: (value, page) => orphanKind(page) === value,
                  render: (_, page) => {
                      const kind = orphanKind(page);
                      return (
                          <Tooltip title={KIND_HELP[kind]}>
                              <Tag color={KIND_COLOUR[kind]}>
                                  {KIND_LABEL[kind]}
                              </Tag>
                          </Tooltip>
                      );
                  },
              },
          ]
        : [];

    return (
        <div className="au-drill">
            {!known && (
                <p className="au-stale">
                    This crawl ran before the engine recorded which path found
                    each URL, so these orphans cannot be split into published
                    and unpublished. Re-crawl the site to get that breakdown — a
                    reparse cannot recover it, because the information was never
                    stored.
                </p>
            )}

            <div className="au-tools">
                {known && (
                    <Segmented
                        size="small"
                        value={filter}
                        onChange={(value) => setFilter(value as Filter)}
                        options={[
                            {
                                label: `All ${pages.length.toLocaleString()}`,
                                value: "all",
                            },
                            {
                                label: `Sitemap ${counts.sitemap.toLocaleString()}`,
                                value: "sitemap",
                            },
                            {
                                label: `CMS only ${counts.cms.toLocaleString()}`,
                                value: "cms",
                            },
                            {
                                label: `Crawl only ${counts.unlinked.toLocaleString()}`,
                                value: "unlinked",
                            },
                        ]}
                    />
                )}
                <Input.Search
                    size="small"
                    allowClear
                    placeholder="Filter by URL"
                    aria-label="Filter orphans by URL"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    style={{ width: 220 }}
                />
                <Button
                    size="small"
                    onClick={exportCsv}
                    disabled={rows.length === 0}
                >
                    Export CSV ({rows.length.toLocaleString()})
                </Button>
            </div>

            <Table<FullPageIntelligenceProfile>
                size="small"
                rowKey="url"
                dataSource={rows}
                pagination={{
                    pageSize: 25,
                    showSizeChanger: true,
                    size: "small",
                }}
                columns={[
                    {
                        title: "URL",
                        dataIndex: "url",
                        ellipsis: true,
                        render: (url: string) => (
                            <a
                                href={url}
                                target="_blank"
                                rel="noreferrer noopener"
                                className="au-url"
                            >
                                {url}
                            </a>
                        ),
                    },
                    ...kindColumn,
                    {
                        title: "Type",
                        dataIndex: "primary_page_type",
                        width: 190,
                        sorter: (a, b) =>
                            a.primary_page_type.localeCompare(
                                b.primary_page_type,
                            ),
                    },
                    {
                        title: "Sitemap",
                        dataIndex: "sitemap_source",
                        width: 210,
                        ellipsis: true,
                        // Which grouped sitemap listed it, which on a large site is also
                        // which content team owns it.
                        render: (source: string | null) =>
                            source ?? <span className="au-more">—</span>,
                    },
                ]}
            />
        </div>
    );
}
