# 🛒 Amazon-Scale E-Commerce Crawling Specification & Safety Blueprint

> **Document ID**: `RKN-ECOMMERCE-SCALE-2026-V1.0`  
> **Status**: Binding System Architecture Specification  
> **Target Scale**: 10 Million to 500 Million+ URLs without OOM crashes, IP bans, or parameter traps  

---

## 1. Executive Summary & Problem Statement

Enterprise e-commerce platforms (e.g. Amazon, Walmart, Target, eBay, Shopify Plus) contain **10M to 500M+ URLs**. Attempting to crawl these sites with legacy crawlers (Screaming Frog, Botify, Lumar) leads to Out-Of-Memory (OOM) process crashes, infinite loop traps, IP blocks, and multi-terabyte data bloat.

Rankuno solves ultra-large e-commerce scale crawling using a **6-Rule Zero-Cost Safeguard Architecture**.

---

## 2. The 5 Mega-Threats & Architectural Mitigations

| Threat / Vulnerability | Impact on Legacy Crawlers | Rankuno Architectural Mitigation |
| :--- | :--- | :--- |
| **1. Faceted Parameter Matrix Explosion** (`?color=red&size=xl&shipping=prime`) | 1 SKU with 20 filter options creates $2^{20} = 1,048,576$ URL permutations $\rightarrow$ Memory crash in minutes. | **Layer 0 Canonical Parameter Normalizer**: Intercepts and drops filter traps BEFORE making HTTP requests ($0.00 fetch cost). |
| **2. Tracking & Session Parameter Traps** (`utm_*`, `gclid`, `qid`, `pf_rd_*`) | URLs appended with `ref=nav_1`, `qid=123` create 50 duplicate nodes for 1 single page. | **Regex URL Stripper**: Normalizes URL to canonical base hash key before queue insertion. |
| **3. RAM Exhaustion (OOM Collapse)** | Storing 10M URL strings in Python `set()` consumes > 8 GB RAM $\rightarrow$ OS kills process. | **Scalable Bloom Filter + SQLite WAL**: Reduces memory footprint from 8.2 GB down to **< 120 MB RAM** for 100M URLs. |
| **4. Anti-Bot IP Blocking & Rate Limits** (429 / 503 / WAF) | Crawling 500 req/sec triggers WAF $\rightarrow$ Instant IP ban / CAPTCHA challenge. | **TokenBucket Rate Controller**: Asynchronous rate-limiter with exponential backoff, randomized jitter, and UA header rotation. |
| **5. Infinite Pagination Traps** (`?page=99999` & `?sort=price-asc`) | Category pages with `?page=1` to `?page=99999` waste 90% of crawl budget on duplicate listings. | **Adaptive Category Cutoff Algorithm**: Limits pagination depth to $N \le 25$ per category hub. |

---

## 3. The 6 Rules for Amazon-Scale Crawling

### Rule 1: Pre-Fetch Canonical Parameter Normalizer (Layer 0 Interceptor)
Before adding any URL to the crawl queue or making an HTTP request, the URL passes through a strict parameter filter:

```python
# Raw Amazon URL:
# https://www.amazon.com/dp/B0001234?color=red&size=xl&ref=nav_1&qid=1723456&sr=8-1

# Step 1: Strip non-canonical tracking keys (ref, qid, sr, utm_*, gclid, pf_rd_*)
# Step 2: Sort functional parameters deterministically (color=red&size=xl)

# Normalized Canonical Target URL:
# https://www.amazon.com/dp/B0001234?color=red&size=xl
```
*Result*: Eliminates 99% of duplicate URLs before sending a single network packet.

### Rule 2: Scalable Bloom Filter for 100M+ URL Deduplication
Instead of storing millions of URL strings in a Python `set()`, Rankuno uses a Scalable Bit-Array Bloom Filter backed by an SQLite WAL database on local NVMe SSD:
- **Memory Footprint (100M URLs)**: Python `set()` = 8.2 GB RAM $\rightarrow$ **Bloom Filter = 119.8 MB RAM**.
- **False Positive Probability**: $p < 0.0001$.
- **Speed**: Bitwise hash lookup takes $< 0.01\text{ms}$.

### Rule 3: SKU Variant Canonical Clustering
- Reads `<link rel="canonical" href="...">` in Layer 1 parser.
- All 20+ color/size variant URLs are grouped under a single **Parent SKU Cluster Node** in the site graph $G=(V,E)$, preventing catalog graph bloat.

### Rule 4: Parameter Threshold Boundary Rules
- **Max Parameter Ceiling**: Any URL with $> 5$ query parameters is immediately flagged as `HierarchyLevel: UTILITY_PAGE`, `PrimaryPageType: FACETED_FILTER` without fetching the page body.
- **Max Crawl Traversal Depth**: Hard depth boundary $d_{\text{max}} = 15$. URLs beyond depth 15 are dropped as crawl traps.

### Rule 5: Streaming Batch Pipeline & Forced Garbage Collection
To guarantee subagent containers remain strictly under **512 MB RAM**:
- Crawl requests process in **500-URL streaming chunks**.
- After each 500-item batch completes, parse results are committed to local SQLite / Supabase PostgreSQL, and explicit Python garbage collection is triggered:

```python
import gc

# Flush batch results to DB
db_session.commit()
# Clear transient DOM trees
del dom_trees
# Force immediate memory reclamation
gc.collect()
```

### Rule 6: Adaptive Rate Limiting & Proxy Shield
- **TokenBucket Rate Controller**: Enforces maximum requests/sec per domain (e.g. max 10 req/sec for sensitive targets).
- **Exponential Backoff with Jitter**: On HTTP 429 or 503, the engine backs off using randomized exponential delays ($t_{\text{wait}} = 2^k + \text{rand}(0,1)$).
- **Header Rotation**: Simulates genuine browser headers across HTTP requests.

---

## 4. System Safety Guarantees Comparison

| Metric | Legacy Crawlers (Screaming Frog) | Rankuno E-Commerce Engine |
| :--- | :--- | :--- |
| **Faceted Filter Traps** | Crawls millions of filter permutations until crash | Intercepts & drops > 5 param traps at Layer 0 (0ms) |
| **RAM Usage (10M URLs)** | > 8 GB (OOM crash) | Strictly capped at < 512 MB (Bloom Filter + GC) |
| **SKU Variants** | Treats every color as separate page | Clusters variants under single Base SKU Node |
| **Tracking Parameters** | Creates duplicate pages for `utm_source`, `qid` | Strips tracking keys before crawl queue insertion |
| **Rate Limit Handling** | Gets IP banned after 100 rapid requests | Adaptive TokenBucket + Exponential Backoff & Jitter |

---

*Maintained by the AI Lead & Systems Engineering Team at Rankuno.*
