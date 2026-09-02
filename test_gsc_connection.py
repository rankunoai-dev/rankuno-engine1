#!/usr/bin/env python3
"""Test GSC API connection with detailed diagnostics."""

from src.core.config import get_settings
from src.integrations.gsc_token_manager import GscTokenManager
from src.integrations.gsc_client import GscApiClient

print("=" * 70)
print("GSC CREDENTIALS & CONNECTION TEST")
print("=" * 70)

# Load credentials
settings = get_settings()
print("\n1. CREDENTIAL CHECK")
print("-" * 70)
print(f"OAuth Client ID: {settings.google_oauth_client_id[:30]}..." if settings.google_oauth_client_id else "❌ MISSING")
print(f"OAuth Client Secret: {'✅ SET' if settings.google_oauth_client_secret else '❌ MISSING'}")
print(f"OAuth Refresh Token: {'✅ SET' if settings.google_oauth_refresh_token else '❌ MISSING'}")

if not all([settings.google_oauth_client_id, settings.google_oauth_client_secret, settings.google_oauth_refresh_token]):
    print("\n❌ Missing credentials! Cannot proceed.")
    exit(1)

# Test 1: Token refresh
print("\n2. TOKEN REFRESH TEST")
print("-" * 70)
try:
    token_manager = GscTokenManager(settings=settings)
    token = token_manager.get_or_refresh_token()
    print(f"✅ Token refresh successful!")
    print(f"   Access token: {token[:30]}...")
    print(f"   Token length: {len(token)} chars")
except Exception as e:
    print(f"❌ Token refresh failed: {e}")
    exit(1)

# Test 2: GSC Client authentication
print("\n3. GSC CLIENT AUTHENTICATION TEST")
print("-" * 70)
try:
    gsc_client = GscApiClient(settings=settings)
    print(f"✅ GSC Client initialized successfully!")
    account_email = gsc_client._token_manager.get_account_email()
    print(f"   Authenticated as: {account_email}")
except Exception as e:
    print(f"❌ GSC Client initialization failed: {e}")
    exit(1)

# Test 3: List accessible properties
print("\n4. GSC PROPERTY ACCESS TEST")
print("-" * 70)
try:
    properties = gsc_client.list_accessible_properties()
    print(f"✅ Successfully queried GSC API!")
    print(f"   Accessible properties: {len(properties)}")
    for prop in properties[:5]:
        print(f"      - {prop.site_url} ({prop.permission_level})")
    if len(properties) > 5:
        print(f"      ... and {len(properties) - 5} more")
except Exception as e:
    print(f"❌ Property list query failed: {e}")
    exit(1)

# Test 4: Query rankuno.com specifically
print("\n5. RANKUNO.COM PROPERTY TEST")
print("-" * 70)
rankuno_props = [p for p in properties if "rankuno.com" in p.site_url]
if rankuno_props:
    for prop in rankuno_props:
        print(f"✅ Found property: {prop.site_url}")
        print(f"   Permission: {prop.permission_level}")
else:
    print(f"⚠️  rankuno.com NOT found in accessible properties")
    print(f"   Available properties: {[p.site_url for p in properties]}")

# Test 5: Fetch GSC analytics for rankuno.com
print("\n6. GSC ANALYTICS QUERY TEST")
print("-" * 70)
try:
    response = gsc_client.fetch_analytics(
        property_url="https://rankuno.com",
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    print(f"✅ GSC analytics query successful!")
    print(f"   Total rows returned: {len(response.rows)}")
    if response.rows:
        sample = response.rows[0]
        print(f"   Sample row:")
        print(f"      Page: {sample.page}")
        print(f"      Clicks: {sample.clicks}")
        print(f"      Impressions: {sample.impressions}")
        print(f"      Position: {sample.position}")
        print(f"      CTR: {sample.ctr:.2%}")
except Exception as e:
    print(f"❌ GSC analytics query failed: {e}")
    exit(1)

print("\n" + "=" * 70)
print("✅ ALL TESTS PASSED - CREDENTIALS ARE VALID & WORKING!")
print("=" * 70)
