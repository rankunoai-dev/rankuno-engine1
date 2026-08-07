"""External API connectors.

Every outbound integration lives here and subclasses
`src.integrations.base_client.BaseAPIClient`. Domain modules must never call an
external API directly - they depend on a connector, which is what makes quota,
retry and credential handling uniform and mockable in tests.

Planned connectors (none implemented yet):

* `gsc_client.py` - Google Search Console
* `google_ads_client.py` - Google Ads
* `serp_client.py` - SERP data providers
"""

from src.integrations.base_client import BaseAPIClient

__all__ = ["BaseAPIClient"]
