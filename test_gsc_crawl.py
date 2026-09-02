#!/usr/bin/env python3
"""Test crawl with GSC enrichment."""

from src.modules.seo.page_classifier.tool import PageClassificationTool, PageClassificationInput
from src.core.config import get_settings

# Verify OAuth credentials are loaded
settings = get_settings()
print("=== CREDENTIAL CHECK ===")
client_id = settings.google_oauth_client_id or "MISSING"
if client_id != "MISSING":
    client_id = client_id[:20] + "..."
print(f"OAuth Client ID: {client_id}")
print(f"OAuth Client Secret: {'SET' if settings.google_oauth_client_secret else 'MISSING'}")
print(f"OAuth Refresh Token: {'SET' if settings.google_oauth_refresh_token else 'MISSING'}")
print()

# Create crawl request
payload = PageClassificationInput(
    base_url="https://rankuno.com",
    gsc_property_url="http://rankuno.com/",  # Use exact registered property URL
    max_pages=50,
)

print("=== CRAWL REQUEST ===")
print(f"Base URL: {payload.base_url}")
print(f"GSC Property: {payload.gsc_property_url}")
print(f"Max Pages: {payload.max_pages}")
print(f"Async Mode: {payload.use_async_crawl}")
print()

# Run crawl
tool = PageClassificationTool()
print("=== STARTING CRAWL ===")
result = tool.run(payload)

print()
print("=== CRAWL RESULTS ===")
print(f"Pages Classified: {result.summary.pages_classified}")
print(f"Escalation Rate: {result.summary.escalation_rate:.2%}")
print(
    f"Discovery: {result.discovery.from_sitemap} sitemap + {result.discovery.from_dom} DOM + {result.discovery.from_cms} CMS"
)
print()

# Check GSC enrichment
pages_with_gsc = [p for p in result.pages if p.gsc_clicks is not None]
print("=== GSC ENRICHMENT ===")
print(f"Pages with GSC data: {len(pages_with_gsc)}/{len(result.pages)}")
if pages_with_gsc:
    sample = pages_with_gsc[0]
    print("Sample page:")
    print(f"  URL: {sample.url}")
    print(f"  Clicks: {sample.gsc_clicks}")
    print(f"  Impressions: {sample.gsc_impressions}")
    print(f"  Position: {sample.gsc_avg_position}")
    print(f"  CTR: {sample.gsc_ctr:.2%}")
else:
    print("❌ No GSC data enriched")

print()
print("=== TOP PAGES BY CLICKS ===")
for p in sorted(result.pages, key=lambda x: x.gsc_clicks or 0, reverse=True)[:5]:
    clicks = p.gsc_clicks or 0
    impr = p.gsc_impressions or 0
    url_short = p.url[:50]
    print(f"{url_short:50} | Clicks: {clicks:4} | Impressions: {impr:5}")
