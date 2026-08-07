# ⚡ Rankuno AI Engine — Tech Stack & Cost-Optimization Specification

> **Document ID**: `RKN-TECH-STACK-2026-V1.0`  
> **Status**: Binding Architecture & Technology Specification  
> **Target Cost**: $0.00 Base Compute / Local-First Compute Philosophy  

---

## 1. Executive Cost & Performance Philosophy

To build an enterprise-grade engine capable of processing 10,000 to 20,000+ pages in 15–30 seconds without incurring heavy SaaS or cloud API bills, we follow a strict **Local-First, Edge-Optimized Compute Philosophy**:

1. **Deterministic Speed First (<1ms, $0.00)**: Handle 65–90% of page crawling, parsing, regex classification, and parameter normalization using hyper-fast C-native libraries.
2. **Local Machine Learning Second (15ms, $0.00)**: Run local ONNX / PyTorch models (`DeBERTa-v3`, `BGE-M3`) on local RTX GPU (RTX 4070 Ti Super 16GB VRAM) for edge cases at zero API cost.
3. **Governed LLM Cloud Third (300ms, <$0.01 per run)**: Invoke cloud LLM APIs (Gemini 2.0 Flash / Qwen 2.5) **ONLY** when local confidence drops below 0.85 (<2% of pages).

---

## 2. Layer-by-Layer Tech Stack Specification

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                RANKUNO TECH STACK                                      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Core Runtime       │ Python 3.11+ / Pydantic v2 (`pydantic-core` Rust engine)       │
├───────────────────────┼────────────────────────────────────────────────────────────────┤
│ 2. Web & Scraping     │ `httpx` (HTTP/2), `selectolax` (C-DOM), `trafilatura`, Playwright│
├───────────────────────┼────────────────────────────────────────────────────────────────┤
│ 3. Local ML & AI      │ `DeBERTa-v3-large` (ONNX/TensorRT), `Qwen 2.5 14B` (vLLM/Ollama)│
├───────────────────────┼────────────────────────────────────────────────────────────────┤
│ 4. Cloud Fallback LLM │ Google Gemini 2.0 Flash (Governed via Pydantic `StrictModel`)  │
├───────────────────────┼────────────────────────────────────────────────────────────────┤
│ 5. Storage & Graph    │ SQLite (WAL mode, local graph G), Supabase PostgreSQL, Redis   │
├───────────────────────┼────────────────────────────────────────────────────────────────┤
│ 6. Quality & Security │ `ruff` (C-Rust linter/formatter), `mypy` (strict), `pytest-cov` │
└───────────────────────┴────────────────────────────────────────────────────────────────┘
```

### Layer 1: Core Runtime & Language Engine
- **Python 3.11+ / 3.12+ (CPython with `uv` package manager)**:
  - *Why*: Pydantic v2 is backed by a compiled Rust core (`pydantic-core`), making data validation 20x–50x faster than Pydantic v1.
  - *uv (by Astral)*: Replaces standard pip for 10x–100x faster environment resolution and zero-lockup installations.
  - *Cost*: $0.00

### Layer 2: Fast Scraping, DOM Parsing & Extraction Engine
- **`selectolax` (C-based Modest DOM Parser)**:
  - *Why*: 10x–20x faster than BeautifulSoup and 5x faster than LXML. Parses 20,000 raw HTML pages in under 1 second.
- **`trafilatura`**:
  - *Why*: High-precision main body extraction that strips boilerplate (nav, footer, ads, sidebars) without running heavy rendering engines.
- **`httpx` (Async with HTTP/2 & Connection Pooling)**:
  - *Why*: Asynchronous multi-connection requests with SSL reuse, enabling parallel scraping of 500+ URLs simultaneously.
- **`Playwright` (Headless Chromium)**:
  - *Why*: Reserved exclusively for JavaScript-heavy single page apps (SPAs) or ARIA nav tree parsing when static HTML parsing fails.
  - *Cost*: $0.00

### Layer 3: Local ML Inference & Local LLMs ($0.00 API Cost)
- **`DeBERTa-v3-large-mnli` (ONNX Runtime / TensorRT on local RTX GPU)**:
  - *Why*: Zero-shot natural language classification running locally on RTX 4070 Ti Super (16GB VRAM) at 15ms per page. Replaces expensive LLM calls for intent classification at $0.00 cost.
- **`Qwen 2.5 14B / 32B` (via vLLM / Ollama local server)**:
  - *Why*: Enterprise-grade local open-weights LLM running on local GPU for advanced content analysis and chunking checks without sending data to external APIs.
- **`Google Gemini 2.0 Flash` (Cloud Safety Net)**:
  - *Why*: Used as the ultimate fallback when local confidence is < 0.85. Extrapolates edge cases in 300ms for fractions of a cent (<$0.01 per 10,000 pages).
  - *Cost*: $0.00 Base Cost (Local GPU) + Minimal cloud fallback.

### Layer 4: Storage, Caching & Graph Traversal Engine
- **`SQLite` with WAL (Write-Ahead Logging) Mode (Local Graph Storage)**:
  - *Why*: Website directed graphs $G=(V,E)$ require millions of fast edge reads/writes during a crawl. SQLite in WAL mode handles 100,000+ operations/sec locally on NVMe SSD with zero network latency and $0.00 host cost.
- **`Supabase` (PostgreSQL - Region: Mumbai `ap-south-1`)**:
  - *Why*: Persistent relational storage for client audit results, project configurations, and Schema.org code patches. Uses Free Tier.
- **`Upstash Redis` (Serverless Redis - Region: Mumbai `ap-south-1`)**:
  - *Why*: `TokenBucket` rate-limiting per upstream domain, task queueing, and idempotency locks for `WRITE`/`FINANCIAL` operations.
  - *Cost*: $0.00 (Utilizes free tiers & local NVMe storage).

### Layer 5: Code Governance, Security & Quality Control
- **`ruff`**: Rust-based linter and formatter replacing Flake8, Black, and Isort in < 10ms.
- **`mypy`**: Strict static type checker (`disallow_untyped_defs = True`).
- **`pytest` & `pytest-cov`**: Automated unit & integration testing enforcing $\ge 85\%$ test coverage floor.
- **`scripts/drift_check.py`**: Documentation drift detector ensuring zero technical debt between code and documentation.
  - *Cost*: $0.00

---

## 3. Cost vs Performance Benchmarking Matrix

| Component | Selected Technology | Latency / Speed | Monthly Cost | Primary Benefit |
| :--- | :--- | :--- | :--- | :--- |
| **Data Validation** | Pydantic v2 (`pydantic-core`) | < 0.01ms | $0.00 | Strict typing with C/Rust speed |
| **DOM Parsing** | `selectolax` (Modest C Engine) | 0.5ms / page | $0.00 | Parses 20,000 HTML pages in 1 second |
| **Local Classifier** | DeBERTa-v3 ONNX on RTX GPU | 15ms / page | $0.00 | Zero-cost local ML classification |
| **Local Graph DB** | SQLite WAL on PCIe Gen4 NVMe | < 0.1ms / query | $0.00 | 100k+ graph Ops/sec with zero latency |
| **Cloud Fallback** | Gemini 2.0 Flash | 300ms / page | < $0.05 / run | Safety net invoked only for < 2% edge cases |
| **Rate Limiter** | Upstash Redis (`TokenBucket`) | 2ms | $0.00 (Free Tier) | Protects upstream APIs from 429 errors |

---

## 4. Architectural Advantages Over SaaS Competitors

1. **Zero Recurring SaaS Bills**: Replaces Screaming Frog ($259/yr), Botify ($10k+/yr), and SurferSEO ($500/mo) with in-house local GPU compute.
2. **Hyper-Parallel Streaming Chunks**: Processes URLs in 500-item batch streams with explicit garbage collection, eliminating OOM crashes.
3. **Immediate Code Remediation**: Output feeds directly into automated code generators for Schema.org JSON-LD and HTML patches.

---

*Maintained by the AI Lead & Systems Engineering Team at Rankuno.*
