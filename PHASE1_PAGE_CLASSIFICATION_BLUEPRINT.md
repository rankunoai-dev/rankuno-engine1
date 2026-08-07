# 📐 Rankuno SEO Engine - Phase 1 Page Classification Blueprint

> **Technical Architecture & Data Contract Specification**  
> **Status**: Approved Blueprint  
> **Document ID**: `RKN-P1-2026-V1`  

---

## 1. Executive Overview

Phase 1 of Rankuno's SEO Engine establishes the **Multi-Dimensional Page & URL Classification Infrastructure**. It categorizes website content graphs across 3 complementary interfaces:

```
                               Target Website URL / Crawled DOM
                                              │
               ┌──────────────────────────────┼──────────────────────────────┐
               │                              │                              │
               ▼                              ▼                              ▼
  ┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
  │       INTERFACE 1:       │   │       INTERFACE 2:       │   │       INTERFACE 3:       │
  │ Page Type & Hierarchy    │   │  Theme & Topical Cluster │   │ Semantic Intent &        │
  │ Classification           │   │  Classification          │   │ Conversion Role          │
  ├──────────────────────────┤   ├──────────────────────────┤   ├──────────────────────────┤
  │ - L0 Homepage            │   │ - Business Niche         │   │ - Informational          │
  │ - L1 Primary Nav Hub     │   │ - Topical Silo           │   │ - Commercial Search      │
  │ - L2 Sub-Nav Hub         │   │ - Sub-Niche Product      │   │ - Transactional          │
  │ - L3 Leaf Money Page     │   │ - Entity Mapping         │   │ - Navigational           │
  │ - Utility Pages          │   │                          │   │ - Lead Gen vs Sale       │
  └──────────────────────────┘   └──────────────────────────┘   └──────────────────────────┘
```

---

## 2. Interface 1: Page Type Hierarchy Taxonomy

| Hierarchy Level | Level Name | Primary Page Types Included | Example URL Pattern |
| :--- | :--- | :--- | :--- |
| **`L0_HOMEPAGE`** | Root Entry | Homepage | `https://vitaquest.com/` |
| **`L1_PRIMARY_NAV_HUB`** | Global Parent Hub | Service Category Hub, Blog Hub, Company Hub, Lead Gen Hub | `/manufacturing-services/`, `/capabilities/` |
| **`L2_SUB_NAV_HUB`** | Sub-Category Hub | Sub-Service Category, Product Category Collection, Tag Archive | `/manufacturing-services/capsule-supplements/` |
| **`L3_LEAF_PAGE`** | Money / Execution Page | Service Detail Page (SDP), Product SKU (PDP), Blog Article | `/blog/supplement-manufacturing-trends` |
| **`UTILITY_PAGE`** | Infrastructure | Privacy Policy, Terms, Search Results, Faceted Filters, 404s | `/privacy-policy`, `/shop?color=red` |

---

## 3. The 6-Signal Consensus Architecture

To guarantee zero classification failures on complex or flat websites, Rankuno evaluates 6 independent signal streams:

1. **Signal 1: ARIA Navigation Tree Analysis** — Inspects DOM accessibility attributes (`role="navigation"`, `aria-label="Main menu"`) and nested `<ul>/<li>` HTML parent-child structures. Accurately classifies Level 1 vs Level 2 navigation dropdowns even if hidden behind a **Hamburger toggle** (`display: none`).
2. **Signal 2: CMS API Endpoint Footprints** — Queries public CMS data endpoints (WordPress `/wp-json/wp/v2/pages`, Shopify `/collections.json`, `/products.json`). Provides 100% accurate classification for **Flat URLs** (e.g. `site.com/capsules` off root).
3. **Signal 3: Grouped XML Sitemap Index Parsing** — Parses `sitemap_index.xml` to inspect auto-grouped files (e.g. `product-sitemap.xml`, `category-sitemap.xml`, `post-sitemap.xml`).
4. **Signal 4: Schema.org `@graph` JSON-LD Parsing** — Extracts structured schema types embedded in HTML: `CollectionPage`, `ItemPage`, `Service`, `Product`, `Article`, `AboutPage`.
5. **Signal 5: Internal Link In-Degree Centrality** — Evaluates internal link distribution. Pages linked in site-wide headers/footers (>= 1,000 links) are classified as Level 1 Hubs.
6. **Signal 6: LLM Zero-Shot Backup Classifier** — Passes URL, Title, H1, Breadcrumbs, and text snippets to Gemini 3.6 Flash for intelligent fallback classification when zero structural signals exist.

---

## 4. Pydantic Data Contracts & Schemas

```python
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class HierarchyLevel(str, Enum):
    L0_HOMEPAGE = "L0_HOMEPAGE"
    L1_PRIMARY_NAV_HUB = "L1_PRIMARY_NAV_HUB"
    L2_SUB_NAV_HUB = "L2_SUB_NAV_HUB"
    L3_LEAF_PAGE = "L3_LEAF_PAGE"
    UTILITY_PAGE = "UTILITY_PAGE"


class PrimaryPageType(str, Enum):
    HOMEPAGE = "HOMEPAGE"
    SERVICE_CATEGORY_HUB = "SERVICE_CATEGORY_HUB"
    SERVICE_DETAIL_PAGE = "SERVICE_DETAIL_PAGE"
    PRODUCT_CATEGORY_HUB = "PRODUCT_CATEGORY_HUB"
    PRODUCT_DETAIL_PAGE = "PRODUCT_DETAIL_PAGE"
    BLOG_HUB = "BLOG_HUB"
    BLOG_ARTICLE = "BLOG_ARTICLE"
    COMPANY_ABOUT = "COMPANY_ABOUT"
    COMMERCIAL_LEAD_GEN = "COMMERCIAL_LEAD_GEN"
    FACETED_FILTER = "FACETED_FILTER"
    UTILITY_LEGAL = "UTILITY_LEGAL"
    UNKNOWN = "UNKNOWN"


class SearchIntent(str, Enum):
    INFORMATIONAL = "INFORMATIONAL"
    COMMERCIAL_INVESTIGATION = "COMMERCIAL_INVESTIGATION"
    TRANSACTIONAL = "TRANSACTIONAL"
    NAVIGATIONAL = "NAVIGATIONAL"


class SignalScore(BaseModel):
    source: str
    suggested_level: HierarchyLevel
    suggested_page_type: PrimaryPageType
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


class FullPageIntelligenceProfile(BaseModel):
    url: str
    normalized_path: str
    hierarchy_level: HierarchyLevel
    primary_page_type: PrimaryPageType
    nav_parent_url: Optional[str]
    breadcrumb_path: List[str]
    topical_category: str
    sub_topic: Optional[str]
    search_intent: SearchIntent
    conversion_role: str
    signals_evaluated: List[SignalScore]
    final_confidence_score: float = Field(ge=0.0, le=1.0)
    consensus_method: str
```

---

## 5. Edge-Case Handling & Security Audit Matrix

| Edge Case / Technical Vulnerability | Root Cause / Impact | Rankuno Architectural Guardrail |
| :--- | :--- | :--- |
| **Hamburger / Hidden Mobile Navs** | CSS hides navigation (`display: none`). | Parse DOM ARIA tree (`role="navigation"`) ignoring visual CSS display. |
| **Flat URLs (`site.com/capsules`)** | Directory path depth regex fails. | Query CMS Endpoints (`/collections.json`, `/wp-json/`) & Sitemap index files. |
| **JavaScript SPAs (React/Next.js)** | Empty `<div id="root">` returned. | Playwright headless browser rendering fallback to hydrate dynamic DOM. |
| **Multi-Language Routing (`/en/`, `/es/`)** | Locale prefixes skew category matching. | Path Normalizer: Strip locale prefixes (`/en/services` -> `/services`) prior to matching. |
| **Faceted Filter Query Params** | Filter parameters (`?color=red`) create infinite URLs. | Parameter Normalizer: Group query parameter URLs into `FACETED_FILTER` utility type. |
| **Anti-Bot & Cloudflare Rate Limits** | IP blocks during bulk scraping. | Rotate User-Agent headers, enforce backoff retries, and prefer CMS API endpoints. |
| **API Cost Overflow** | Unbounded LLM fallback API calls. | Rate-limiter & caching layer: LLM invoked only when 5 structural signals are ambiguous. |
