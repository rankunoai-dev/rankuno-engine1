/**
 * GSC Integrated Report — Display crawl results with GSC metrics and navigation context
 *
 * Shows each crawled URL with:
 * - Classification (hierarchy level, page type)
 * - GSC metrics (clicks, impressions, CTR, position)
 * - Navigation context (discovery method, reachability tier)
 *
 * Phase 6 + Phase 8a output in one unified analyst view.
 */

import React, { useState, useMemo } from 'react';
import styles from './GscIntegratedReport.module.css';

interface GscMetrics {
  clicks?: number;
  impressions?: number;
  ctr?: number;
  avgPosition?: number;
}

interface NavigationContext {
  discoveryMethod?: string;
  reachabilityTier?: string;
  sourceAuthority?: string;
  pathQuality?: string;
}

interface CrawlPage {
  url: string;
  hierarchyLevel: string;
  primaryPageType: string;
  gscMetrics?: GscMetrics;
  navigationContext?: NavigationContext;
}

interface GscIntegratedReportProps {
  pages: CrawlPage[];
  totalPages: number;
  baseUrl: string;
}

type SortField = 'url' | 'clicks' | 'impressions' | 'ctr' | 'position';
type SortOrder = 'asc' | 'desc';

/**
 * Format metrics with thousands separator
 */
const formatMetric = (value: number | undefined, type: 'number' | 'percent' | 'position' = 'number'): string => {
  if (value === undefined || value === null) return '—';

  if (type === 'percent') {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (type === 'position') {
    return value.toFixed(1);
  }

  return value.toLocaleString();
};

/**
 * Determine metric health color based on value
 * - Good: high CTR, low position, high clicks
 * - Warning: mid-range
 * - Critical: low CTR, high position, low clicks
 */
const getMetricClass = (value: number | undefined, metric: 'clicks' | 'ctr' | 'position'): string => {
  if (value === undefined) return '';

  const good = styles.good ?? '';
  const warning = styles.warning ?? '';
  const critical = styles.critical ?? '';

  switch (metric) {
    case 'clicks':
      return value > 50 ? good : value > 10 ? warning : critical;
    case 'ctr':
      return value > 0.05 ? good : value > 0.02 ? warning : critical;
    case 'position':
      return value < 15 ? good : value < 25 ? warning : critical;
    default:
      return '';
  }
};

/**
 * Format tier label for display
 */
const formatTier = (tier: string | undefined): string => {
  if (!tier) return '—';
  return tier
    .replace('TIER_0_HERO', 'Hero')
    .replace('TIER_1_STANDARD', 'Std')
    .replace('TIER_2_DEEP', 'Deep')
    .replace('TIER_3_METADATA', 'Meta')
    .replace('TIER_4_ORPHANED', 'Orphan');
};

/**
 * Format discovery method label
 */
const formatDiscovery = (method: string | undefined): string => {
  if (!method) return '—';
  return method
    .replace('PRIMARY_NAV', 'Primary')
    .replace('SECONDARY_NAV', 'Secondary')
    .replace('BODY_LINK', 'Body')
    .replace('BREADCRUMB', 'Breadcrumb')
    .replace('SITEMAP_ONLY', 'Sitemap')
    .replace('ORPHANED', 'Orphan');
};

export const GscIntegratedReport: React.FC<GscIntegratedReportProps> = ({
  pages,
  totalPages,
  baseUrl,
}) => {
  const [sortField, setSortField] = useState<SortField>('clicks');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [searchFilter, setSearchFilter] = useState('');

  /**
   * Filter and sort pages
   */
  const sortedPages = useMemo(() => {
    let filtered = pages;

    // Filter by URL search
    if (searchFilter) {
      const lower = searchFilter.toLowerCase();
      filtered = pages.filter((p) => p.url.toLowerCase().includes(lower));
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      let aVal: number = 0;
      let bVal: number = 0;

      switch (sortField) {
        case 'clicks':
          aVal = a.gscMetrics?.clicks ?? 0;
          bVal = b.gscMetrics?.clicks ?? 0;
          break;
        case 'impressions':
          aVal = a.gscMetrics?.impressions ?? 0;
          bVal = b.gscMetrics?.impressions ?? 0;
          break;
        case 'ctr':
          aVal = (a.gscMetrics?.ctr ?? 0) * 100;
          bVal = (b.gscMetrics?.ctr ?? 0) * 100;
          break;
        case 'position':
          aVal = a.gscMetrics?.avgPosition ?? 100;
          bVal = b.gscMetrics?.avgPosition ?? 100;
          break;
        case 'url':
          return sortOrder === 'asc' ? a.url.localeCompare(b.url) : b.url.localeCompare(a.url);
      }

      return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
    });

    return sorted;
  }, [pages, sortField, sortOrder, searchFilter]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className={styles.sortIcon}>⇅</span>;
    return <span className={styles.sortIcon}>{sortOrder === 'asc' ? '↑' : '↓'}</span>;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>Crawl Results with GSC Integration</h2>
        <p className={styles.subtitle}>
          {sortedPages.length} of {totalPages} pages • Click headers to sort
        </p>
      </div>

      <div className={styles.controls}>
        <input
          type="text"
          placeholder="Filter by URL..."
          className={styles.searchInput}
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
        />
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th onClick={() => handleSort('url')} style={{ cursor: 'pointer' }}>
                URL <SortIcon field="url" />
              </th>
              <th>Level</th>
              <th>Type</th>
              <th>Discovery</th>
              <th>Reach</th>
              <th onClick={() => handleSort('clicks')} style={{ cursor: 'pointer' }}>
                Clicks <SortIcon field="clicks" />
              </th>
              <th onClick={() => handleSort('impressions')} style={{ cursor: 'pointer' }}>
                Impr. <SortIcon field="impressions" />
              </th>
              <th onClick={() => handleSort('ctr')} style={{ cursor: 'pointer' }}>
                CTR <SortIcon field="ctr" />
              </th>
              <th onClick={() => handleSort('position')} style={{ cursor: 'pointer' }}>
                Pos. <SortIcon field="position" />
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedPages.map((page, idx) => (
              <tr key={`${page.url}-${idx}`} className={styles.row}>
                <td className={styles.urlCell}>
                  <a
                    href={page.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={page.url}
                    className={styles.urlLink}
                  >
                    {page.url.replace(baseUrl, '')}
                  </a>
                </td>
                <td className={styles.levelCell}>{page.hierarchyLevel}</td>
                <td className={styles.typeCell}>{page.primaryPageType}</td>
                <td className={styles.contextCell}>
                  <span className={styles.tag}>{formatDiscovery(page.navigationContext?.discoveryMethod)}</span>
                </td>
                <td className={styles.contextCell}>
                  <span className={styles.tag}>{formatTier(page.navigationContext?.reachabilityTier)}</span>
                </td>
                <td className={`${styles.metricCell} ${getMetricClass(page.gscMetrics?.clicks, 'clicks')}`}>
                  {formatMetric(page.gscMetrics?.clicks)}
                </td>
                <td className={styles.metricCell}>{formatMetric(page.gscMetrics?.impressions)}</td>
                <td className={`${styles.metricCell} ${getMetricClass(page.gscMetrics?.ctr, 'ctr')}`}>
                  {formatMetric(page.gscMetrics?.ctr, 'percent')}
                </td>
                <td className={`${styles.metricCell} ${getMetricClass(page.gscMetrics?.avgPosition, 'position')}`}>
                  {formatMetric(page.gscMetrics?.avgPosition, 'position')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sortedPages.length === 0 && (
        <div className={styles.emptyState}>
          <p>No pages match your filter. Try adjusting your search.</p>
        </div>
      )}
    </div>
  );
};

export default GscIntegratedReport;
