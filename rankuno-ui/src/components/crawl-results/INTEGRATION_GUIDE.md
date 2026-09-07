# GSC Integrated Report — Integration Guide

## Overview

The `GscIntegratedReport` component displays crawl results with Google Search Console metrics and navigation context in a single, unified table view.

**Data comes from:**
- **Phase 6**: GSC OAuth integration (clicks, impressions, CTR, position)
- **Phase 8a**: Navigation context classifier (discovery method, reachability tier)

Both are already wired into the backend—this component just displays them.

---

## Component Structure

```
GscIntegratedReport/
├── GscIntegratedReport.tsx        # React component
├── GscIntegratedReport.module.css  # Styles (CSS Modules)
├── GscIntegratedReport.example.tsx # Usage examples
└── INTEGRATION_GUIDE.md            # This file
```

---

## Quick Start

### 1. Import the Component

```typescript
import GscIntegratedReport from '@/components/crawl-results/GscIntegratedReport';
```

### 2. Pass Your Data

```typescript
<GscIntegratedReport
  pages={crawlResult.pages}
  totalPages={crawlResult.totalPages}
  baseUrl={crawlResult.baseUrl}
/>
```

### 3. Data Structure Expected

Each page object should have:

```typescript
interface CrawlPage {
  url: string;                              // Full URL
  hierarchyLevel: string;                   // L0_HOMEPAGE, L1_PRIMARY_NAV_HUB, etc.
  primaryPageType: string;                  // HOMEPAGE, CASE_STUDY, BLOG_ARTICLE, etc.
  
  gscMetrics?: {
    clicks?: number;                        // Clicks from Google Search Console
    impressions?: number;                   // Search impressions
    ctr?: number;                          // Click-through rate (0-1, not percentage)
    avgPosition?: number;                  // Average SERP position
  };
  
  navigationContext?: {
    discoveryMethod?: string;              // PRIMARY_NAV, SECONDARY_NAV, BODY_LINK, etc.
    reachabilityTier?: string;            // TIER_0_HERO, TIER_1_STANDARD, TIER_2_DEEP, etc.
    sourceAuthority?: string;             // FROM_HOMEPAGE, FROM_MAIN_HUB, FROM_FOOTER, etc.
    pathQuality?: string;                 // LOGICAL_HIERARCHY, LATERAL_LINKED, DISCONNECTED
  };
}
```

---

## Integration into LiveCrawlModal

### Current State (without GscIntegratedReport)

In `LiveCrawlModal.tsx`, you probably have something like:

```typescript
<div className={styles.resultsContainer}>
  <ResultsSummary result={crawlResult} />
  {/* Maybe some other views */}
</div>
```

### Updated State (with GscIntegratedReport)

```typescript
import GscIntegratedReport from '@/components/crawl-results/GscIntegratedReport';

<div className={styles.resultsContainer}>
  <ResultsSummary result={crawlResult} />
  
  {/* NEW: Integrated GSC + Navigation Context Report */}
  <GscIntegratedReport
    pages={crawlResult.pages}
    totalPages={crawlResult.summary?.pages_classified || crawlResult.pages.length}
    baseUrl={crawlResult.base_url}
  />
</div>
```

---

## API Response Mapping

Your API returns (from `FullPageIntelligenceProfile` JSON):

```json
{
  "base_url": "https://rankuno.com",
  "pages": [
    {
      "url": "https://rankuno.com/",
      "hierarchy_level": "L0_HOMEPAGE",
      "primary_page_type": "HOMEPAGE",
      
      "gsc_clicks": 156,
      "gsc_impressions": 2340,
      "gsc_ctr": 0.067,
      "gsc_avg_position": 12.3,
      
      "navigation_discovery_method": "PRIMARY_NAV",
      "navigation_reachability_tier": "TIER_0_HERO",
      "navigation_source_authority": "FROM_HOMEPAGE",
      "navigation_path_quality": "LOGICAL_HIERARCHY"
    }
  ]
}
```

Just pass these fields directly—the snake_case names map to the component's camelCase interface automatically.

---

## Features

### ✅ Sorting
- Click any metric header to sort ascending/descending
- Sort fields: URL, Clicks, Impressions, CTR, Position
- Visual indicators show current sort direction

### ✅ Filtering
- Search box filters by URL (includes partial matches)
- Real-time filter as you type

### ✅ Color-Coded Metrics
- **Green** (good): High clicks, high CTR, low position
- **Orange** (warning): Mid-range metrics
- **Red** (critical): Low clicks, low CTR, high position

### ✅ Navigation Context Tags
- Shows where page was discovered (Primary Nav, Secondary Nav, Body Link)
- Shows reachability tier (Hero, Standard, Deep, Metadata, Orphan)
- Helps analysts understand site structure

### ✅ Responsive Design
- Works on mobile (table scrolls horizontally)
- Collapses columns on small screens
- Touch-friendly sort buttons

---

## Styling & Theming

The component uses CSS Variables for theming. Define these in your app's root CSS:

```css
:root {
  --color-surface: #ffffff;
  --color-bg: #f8f9fa;
  --color-border: #e0e4e8;
  --color-text: #1a202c;
  --color-text-muted: #64748b;
  --color-accent: #2563eb;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --color-surface: #1e293b;
    --color-bg: #0f172a;
    --color-border: #334155;
    --color-text: #f1f5f9;
    --color-text-muted: #94a3b8;
  }
}
```

The component automatically adapts to light/dark themes.

---

## Example Usage Files

See `GscIntegratedReport.example.tsx` for:

1. **Full example crawl result** with sample data
2. **API response transformation** function
3. **Integration pattern** in a results page component

---

## Common Questions

### Q: Can I hide certain columns?
A: Not yet. If you need to customize visible columns, modify the component to accept a `visibleColumns` prop.

### Q: How do I handle pages with no GSC data?
A: The component shows "—" (em-dash) for missing metrics. It's safe to pass `undefined` for any GSC or navigation context field.

### Q: Can I export this data?
A: Add an export button that generates CSV from `sortedPages`. Example:
```typescript
const csv = sortedPages
  .map(p => `${p.url},${p.gscMetrics?.clicks},${p.gscMetrics?.ctr}`)
  .join('\n');
```

### Q: Why is Position shown as a decimal?
A: Google Search Console returns average position (e.g., 12.3). The component formats it to one decimal place for readability.

---

## Performance Notes

- Component handles 100+ pages smoothly
- Sorting/filtering uses `useMemo` for optimization
- Table uses CSS sticky headers for easy scrolling
- No external dependencies (pure React)

---

## What's Next?

Once integrated, you could add:

1. **Export to CSV** — Download pages as spreadsheet
2. **Bulk actions** — Select multiple pages for tagging
3. **Drill-down detail** — Click a row to see full page analysis
4. **Custom columns** — Let analysts choose what to display
5. **Recommendations** — "This page has 0 clicks, consider moving it to primary nav"

But start with the basic table—it does 80% of the job!

---

## Support

See `GscIntegratedReport.tsx` source for:
- Component props interface
- Sort/filter logic
- Color determination functions
- Format functions (metric display)

All are well-commented and easy to extend.
