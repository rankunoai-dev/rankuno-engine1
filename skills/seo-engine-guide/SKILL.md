---
name: seo-engine-guide
description: Master reference for SEO engineering, technical audit mechanics, SERP scraping, keyword clustering, and digital marketing API integrations for Rankuno.
---

# 🔍 Rankuno SEO Engine & Domain Engineering Guide

## 1. Core SEO Engineering Pillars

### A. Technical SEO Audit Engine
- **Crawling & Rendering**: Simulating user-agents, parsing DOM trees, handling JavaScript rendering (Playwright/Puppeteer).
- **Indexing & Canonicalization**: Checking `robots.txt`, XML sitemaps, canonical tags, `noindex`/`nofollow` directives, `hreflang` attributes.
- **Core Web Vitals & Performance**: LCP (Largest Contentful Paint), INP (Interaction to Next Paint), CLS (Cumulative Layout Shift) via PageSpeed Insights API.
- **Schema & Structured Data**: Validating JSON-LD, Microdata, OpenGraph tags, JSON schema validation.

### B. Keyword Intelligence & Intent Clustering Engine
- **Keyword Research**: Volume, CPC, Keyword Difficulty (KD), Search Intent (Informational, Navigational, Commercial, Transactional).
- **Semantic Clustering**: Grouping keywords by vector embeddings or TF-IDF / N-gram co-occurrence to construct topical authority clusters.
- **Content Gap Analysis**: Comparing target domain keywords against competitor rankings to find missing search opportunities.

### C. Content Brief & On-Page Optimization Engine
- **SERP Analyzer**: Extracting top 10 search results for a keyword, calculating word count, readability scores, H1-H3 heading hierarchies, keyword density.
- **AI Content Brief Generator**: Producing structured briefs (Primary KW, Secondary KWs, Target Length, Questions to Answer, Schema types).
- **On-Page Auditor**: Checking title tag lengths (50-60 chars), meta descriptions (150-160 chars), image alt attributes, internal link distributions.

### D. Rank & Analytics Data Engine
- **Google Search Console (GSC) API**: Pulling impression data, click-through-rate (CTR), average position, URL inspection metrics.
- **Rank Tracking Synthesis**: Tracking ranking shifts over time, identifying keyword cannibalization (multiple pages competing for the same query).

---

## 2. Essential Open-Source Python & JS Libraries for SEO

| Library | Category | Use Case in Rankuno SEO Engine |
| :--- | :--- | :--- |
| `advertools` | SEO Data Analytics | Parsing XML sitemaps, robots.txt, SERP analysis, keyword generating, URL parsing |
| `trafilatura` | Web Scraping / Content Extraction | Extracting clean text, markdown, and metadata from HTML pages without clutter |
| `playwright` / `puppeteer` | Browser Automation | Headless rendering of JS-heavy SPA sites for technical audits |
| `beautifulsoup4` / `selectolax` | HTML Parsing | Fast DOM extraction for meta tags, headings, schema JSON-LD |
| `spacy` / `sentence-transformers` | NLP & Semantic Embeddings | Keyword clustering and semantic similarity matching |
| `pydantic` | Data Validation | Enforcing strict schemas for audit reports, briefs, and keyword objects |

---

## 3. Human-in-the-Loop (HITL) Controls in SEO Automation

- **Read Operations (Automated)**: Auditing URLs, analyzing SERPs, pulling GSC stats, clustering keywords.
- **Draft Operations (AI-Assisted)**: Generating content briefs, meta description suggestions, schema markups, technical fix recommendations.
- **Write Operations (Human Approval Required)**: Modifying live site code, pushing automatic metadata updates via CMS API, submitting disavow files.
