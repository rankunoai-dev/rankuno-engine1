/**
 * Example: How to integrate GscIntegratedReport into your crawl results view
 *
 * This shows the data structure and integration pattern.
 */

import GscIntegratedReport from './GscIntegratedReport';

/**
 * Example crawl result with GSC data and navigation context
 * This is what the API returns after Phase 6 (GSC) + Phase 8a (Navigation Context)
 */
const EXAMPLE_CRAWL_RESULT = {
  baseUrl: 'https://rankuno.com',
  totalPages: 83,
  pages: [
    {
      url: 'https://rankuno.com/',
      hierarchyLevel: 'L0_HOMEPAGE',
      primaryPageType: 'HOMEPAGE',
      gscMetrics: {
        clicks: 156,
        impressions: 2340,
        ctr: 0.067,
        avgPosition: 12.3,
      },
      navigationContext: {
        discoveryMethod: 'PRIMARY_NAV',
        reachabilityTier: 'TIER_0_HERO',
        sourceAuthority: 'FROM_HOMEPAGE',
        pathQuality: 'LOGICAL_HIERARCHY',
      },
    },
    {
      url: 'https://rankuno.com/case-study/',
      hierarchyLevel: 'L2_SUB_NAV_HUB',
      primaryPageType: 'CASE_STUDY',
      gscMetrics: {
        clicks: 89,
        impressions: 1204,
        ctr: 0.074,
        avgPosition: 14.7,
      },
      navigationContext: {
        discoveryMethod: 'PRIMARY_NAV',
        reachabilityTier: 'TIER_1_STANDARD',
        sourceAuthority: 'FROM_MAIN_HUB',
        pathQuality: 'LOGICAL_HIERARCHY',
      },
    },
    {
      url: 'https://rankuno.com/about/',
      hierarchyLevel: 'L1_PRIMARY_NAV_HUB',
      primaryPageType: 'COMPANY_ABOUT',
      gscMetrics: {
        clicks: 12,
        impressions: 450,
        ctr: 0.027,
        avgPosition: 27.1,
      },
      navigationContext: {
        discoveryMethod: 'SECONDARY_NAV',
        reachabilityTier: 'TIER_0_HERO',
        sourceAuthority: 'FROM_FOOTER',
        pathQuality: 'LOGICAL_HIERARCHY',
      },
    },
    {
      url: 'https://rankuno.com/blog/article-1/',
      hierarchyLevel: 'L3_LEAF_PAGE',
      primaryPageType: 'BLOG_ARTICLE',
      gscMetrics: {
        clicks: 234,
        impressions: 3156,
        ctr: 0.074,
        avgPosition: 11.8,
      },
      navigationContext: {
        discoveryMethod: 'BODY_LINK',
        reachabilityTier: 'TIER_2_DEEP',
        sourceAuthority: 'FROM_CONTENT',
        pathQuality: 'LATERAL_LINKED',
      },
    },
    {
      url: 'https://rankuno.com/solutions/',
      hierarchyLevel: 'L1_PRIMARY_NAV_HUB',
      primaryPageType: 'SERVICE_CATEGORY_HUB',
      gscMetrics: {
        clicks: 3,
        impressions: 287,
        ctr: 0.01,
        avgPosition: 42.5,
      },
      navigationContext: {
        discoveryMethod: 'PRIMARY_NAV',
        reachabilityTier: 'TIER_1_STANDARD',
        sourceAuthority: 'FROM_MAIN_HUB',
        pathQuality: 'DISCONNECTED',
      },
    },
  ],
};

/**
 * Example 1: Basic integration in a crawl results page
 */
export function CrawlResultsPage() {
  const crawlResult = EXAMPLE_CRAWL_RESULT;

  return (
    <div style={{ padding: '2rem', maxWidth: '1400px', margin: '0 auto' }}>
      <h1>Crawl Results: rankuno.com</h1>

      {/* Your other crawl summary components here */}
      <div style={{ marginBottom: '2rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        <div style={{ padding: '1rem', background: '#f0f9ff', borderRadius: '8px' }}>
          <div style={{ fontSize: '0.85rem', color: '#64748b' }}>Total Pages</div>
          <div style={{ fontSize: '2rem', fontWeight: '600' }}>{crawlResult.totalPages}</div>
        </div>
        <div style={{ padding: '1rem', background: '#f0fdf4', borderRadius: '8px' }}>
          <div style={{ fontSize: '0.85rem', color: '#64748b' }}>Classified</div>
          <div style={{ fontSize: '2rem', fontWeight: '600' }}>83</div>
        </div>
        <div style={{ padding: '1rem', background: '#fef3c7', borderRadius: '8px' }}>
          <div style={{ fontSize: '0.85rem', color: '#64748b' }}>Total Clicks</div>
          <div style={{ fontSize: '2rem', fontWeight: '600' }}>494</div>
        </div>
      </div>

      {/* The integrated report */}
      <GscIntegratedReport
        pages={crawlResult.pages}
        totalPages={crawlResult.totalPages}
        baseUrl={crawlResult.baseUrl}
      />
    </div>
  );
}

/**
 * Example 2: How to transform API response to component props
 *
 * Your API returns something like:
 * {
 *   "base_url": "https://rankuno.com",
 *   "summary": { "pages_classified": 83, ... },
 *   "pages": [
 *     {
 *       "url": "https://rankuno.com/...",
 *       "hierarchy_level": "L0_HOMEPAGE",
 *       "primary_page_type": "HOMEPAGE",
 *       "gsc_clicks": 156,
 *       "gsc_impressions": 2340,
 *       "gsc_ctr": 0.067,
 *       "gsc_avg_position": 12.3,
 *       "navigation_discovery_method": "PRIMARY_NAV",
 *       "navigation_reachability_tier": "TIER_0_HERO",
 *       "navigation_source_authority": "FROM_HOMEPAGE",
 *       "navigation_path_quality": "LOGICAL_HIERARCHY"
 *     },
 *     ...
 *   ]
 * }
 *
 * Transform it like this:
 */
export function transformApiResponseToComponent(apiResponse: any) {
  return {
    baseUrl: apiResponse.base_url,
    totalPages: apiResponse.summary?.pages_classified || apiResponse.pages.length,
    pages: apiResponse.pages.map((page: any) => ({
      url: page.url,
      hierarchyLevel: page.hierarchy_level,
      primaryPageType: page.primary_page_type,
      gscMetrics: {
        clicks: page.gsc_clicks,
        impressions: page.gsc_impressions,
        ctr: page.gsc_ctr,
        avgPosition: page.gsc_avg_position,
      },
      navigationContext: {
        discoveryMethod: page.navigation_discovery_method,
        reachabilityTier: page.navigation_reachability_tier,
        sourceAuthority: page.navigation_source_authority,
        pathQuality: page.navigation_path_quality,
      },
    })),
  };
}

/**
 * Example 3: In your LiveCrawlModal or results view
 */
export function ExampleIntegration() {
  // Simulate API response
  const apiResponse = EXAMPLE_CRAWL_RESULT;

  // Transform to component props
  const componentProps = {
    pages: apiResponse.pages,
    totalPages: apiResponse.pages.length,
    baseUrl: apiResponse.baseUrl,
  };

  return (
    <div>
      <h2>Crawl Results</h2>
      <GscIntegratedReport {...componentProps} />
    </div>
  );
}

export default CrawlResultsPage;
