# ADR 0010: GSC API Integration Security, Quota & Account Safety Controls

**Status**: APPROVED  
**Date**: 2026-09-01  
**Scope**: Risk Analysis & Hardened Safeguards for Direct Google Search Console (GSC) API Integration

---

## 🎯 Context & Problem Statement

Integrating Rankuno directly with the Google Search Console API using an official company Google Account requires **zero-risk guarantees**. 

We must identify every possible scenario where Google could rate-limit, block, flag, or suspend an OAuth client or Google Account when making API calls across multiple client properties, and implement mandatory code-level safeguards.

---

## 🛡️ Risk Analysis & Mandatory Engine Safeguards

### 1. Quota Abuse & Request Storms (HTTP 429 Throttling)
* **Google's Rule**: Google Search Console API enforces strict quota limits:
  * **1,200 Queries Per Minute (QPM)** per property.
  * **1,200 QPM** per Google Cloud project.
* **The Risk**: Sending rapid concurrent requests across multiple client sites could exceed Google's quota, leading to API throttling.
* **Engine Safeguard**:
  * All outbound GSC API requests must subclass `BaseAPIClient` (`src/integrations/base_client.py`).
  * Enforce client-side token bucket rate limiting (`requests_per_minute = 60`) that bottlenecks requests **before** they leave your machine.
  * Wrap all API calls in exponential backoff retries (`tenacity`) to gracefully handle transient network pauses.

---

### 2. Accidental Mutation or Data Modification Risk
* **Google's Rule**: Google API scopes determine what an OAuth application can do.
* **The Risk**: If an app requests full write permissions (`webmasters`), accidental bugs could modify sitemaps or settings on client properties.
* **Engine Safeguard**:
  * Rankuno **strictly requests READ-ONLY permissions**:
    `https://www.googleapis.com/auth/webmasters.readonly`
  * The `webmasters.readonly` scope makes it **physically impossible** for Rankuno to alter, delete, submit, or modify any client property, sitemap, or search setting on Google Search Console.

---

### 3. Credential Leakage & Security Scans
* **Google's Rule**: Google automated security bots scan public code repositories for exposed API keys and secrets, revoking compromised credentials instantly.
* **Engine Safeguard**:
  * All OAuth secrets and refresh tokens are wrapped in Pydantic `SecretStr`.
  * Tokens are saved exclusively in local, gitignored files (`.env.local` or OS keyring), **never** stored in public repositories or `.jobs/` JSON files.

---

### 4. Unverified OAuth App Warnings & Suspensions
* **Google's Rule**: Public OAuth applications requesting sensitive scopes without verification get flagged or limited to 100 test users.
* **Engine Safeguard**:
  * For agency/company internal use, configure the Google Cloud OAuth Consent Screen as **"Internal"** (scoped to your company's Google Workspace domain).
  * Internal OAuth apps skip Google verification entirely, operate with 100% trust, and have zero user caps.

---

## 📐 Implementation Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Google Cloud Console                      │
│ - Scopes: webmasters.readonly ONLY                          │
│ - User Type: Internal (Company Google Workspace Domain)     │
└──────────────────────────────┬──────────────────────────────┘
                               │ OAuth 2.0 Token
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 src/integrations/base_client.py             │
│ - Client-Side Token Bucket (60 QPM bottleneck)              │
│ - Exponential Backoff Retries (tenacity)                    │
│ - Read-Only Enforcement                                     │
└──────────────────────────────┬──────────────────────────────┘
                               │ Emits GscPageMetrics
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                Rankuno Pure Domain Engine                   │
│ - url_identity.py (Resolution Index)                        │
│ - aggregator.py (Section Rollups)                           │
│ - opportunity_scorer.py (Analyst Insights)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Safety Checklist Before Code Execution

1. [x] **Scope**: Set to `webmasters.readonly` ONLY.
2. [x] **Rate Limiter**: Token bucket enforced in `base_client.py` (60 QPM).
3. [x] **Credentials**: Stored in `SecretStr` / `.env.local` (gitignored).
4. [x] **OAuth Type**: Configured as "Internal" in Google Cloud Console.
