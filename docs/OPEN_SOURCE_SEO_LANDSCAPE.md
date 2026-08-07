# 🧰 Open-Source SEO & Automation Tooling Landscape

To build Rankuno's SEO Engine rapidly from scratch without reinventing the wheel, we leverage battle-tested open-source libraries and APIs across crawling, content extraction, semantic analysis, and reporting.

---

## 1. Open-Source SEO & Scraping Stack

### A. Technical Crawling & DOM Extraction
- **`advertools` (Python)**: Specialized SEO library for parsing XML sitemaps, `robots.txt`, SERP queries, URL structure analysis, and bulk text analysis.
- **`trafilatura` (Python)**: State-of-the-art web text & main content extraction library. Strips headers, footers, and sidebars automatically to leave pure main-body text.
- **`selectolax` / `beautifulsoup4` (Python)**: Ultra-fast HTML parsing using Cython/Modest engine to extract meta tags, JSON-LD schema, canonical links, and headers.
- **`playwright` / `puppeteer`**: Dynamic headless browsers to crawl JavaScript-rendered pages (React, Next.js, Vue, Angular).

### B. NLP & Keyword Intelligence
- **`sentence-transformers` / `fastembed` (Python)**: Generate semantic vector embeddings locally to cluster thousands of keywords into topical content hubs without expensive API calls.
- **`scikit-learn` (Python)**: HDBSCAN / K-Means / DBSCAN algorithms for automated keyword clustering and intent grouping.
- **`spacy` (Python)**: Entity recognition (NER) to extract brand names, product entities, locations, and search terms from SERP pages.

### C. Technical Performance & Audit
- **Google PageSpeed Insights API**: Programmatic access to Chrome User Experience Report (CrUX) and Lighthouse metrics (LCP, CLS, INP, FCP, TTFB).
- **`axe-core`**: Automated accessibility and HTML compliance auditor for technical SEO audits.

---

## 2. Recommended Integrated API Strategy

When open-source scrapers are blocked or limited by anti-bot measures, we integrate with dedicated data providers:

| Provider Category | Primary Use Case | Recommended APIs |
| :--- | :--- | :--- |
| **Search Engine Results (SERP)** | Live Google top-100 results, PAA (People Also Ask), Featured Snippets | DataForSEO / SerpAPI / DuckDuckGo |
| **First-Party Analytics** | Real client search impression, click, CTR, position, index status data | Google Search Console API |
| **PPC & Ad Metrics** | Campaign metrics, search term reports, keyword planner estimates | Google Ads API |

---

*Maintainers: Keep this document updated as new tools are evaluated and integrated into `src/integrations/`.*
