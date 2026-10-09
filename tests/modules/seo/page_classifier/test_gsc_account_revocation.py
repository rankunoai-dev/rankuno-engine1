"""Enrichment resolves the GSC account lazily, and fails closed (ADR 0037, C4/C6).

Credentials are resolved when enrichment starts, never snapshotted at intake,
so deleting an account between intake and enrichment revokes it for that
crawl. A store that cannot answer, or a row that cannot be decrypted, makes
enrichment `failed`, never the default credentials and never a same-named
`.env.local` profile. No network: the token endpoint is patched to explode.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import GscAccountStoreUnavailableError, GscCredentialDecryptionError
from src.core.gsc_account_store import DiskGscAccountStore
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import DiskOrgConfigStore
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool
from tests.core.test_gsc_account_store import _Store

PAGE = FullPageIntelligenceProfile(
    url="https://example.com/a",
    canonical_url="https://example.com/a",
    normalized_path="/a/",
    hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
    primary_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
    depth_from_l0=1,
    search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
    signals_evaluated=(
        SignalScore(
            source=SignalSource.SCHEMA_JSONLD,
            suggested_level=HierarchyLevel.L3_LEAF_PAGE,
            suggested_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
            confidence=0.9,
        ),
    ),
    final_confidence_score=0.9,
    consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
)


def _settings(store: object, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt-must-not-be-used"),
    }
    base.update(overrides)
    settings = Settings(**base)
    settings._gsc_account_store = store  # type: ignore[assignment]
    return settings


def _enrich(settings: Settings, account: str) -> object:
    payload = PageClassificationInput(
        base_url="https://example.com",
        gsc_property_url="https://example.com",
        gsc_account=account,
    )
    tool = PageClassificationTool(org_id="org-a")

    def no_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the token endpoint must never be called")

    with (
        patch("src.integrations.base_client.get_settings", lambda: settings),
        patch("src.integrations.gsc_token_manager.requests.post", no_network),
    ):
        _pages, report = tool._enrich_with_gsc((PAGE,), payload)
    return report


def test_a_delete_after_intake_revokes_the_account(tmp_path) -> None:
    org_store = DiskOrgConfigStore(tmp_path / "orgs")
    org_store.create(OrgConfig(org_id="org-a", display_name="A"))
    store = DiskGscAccountStore(org_store)
    store.upsert(
        "org-a",
        "solo",
        GscAccountCredential(refresh_token=SecretStr("rt-solo")),
        operator_id="op",
    )
    settings = _settings(store)
    # Intake accepted it: the name was known then.
    assert "solo" in settings.gsc_account_names_for_org("org-a")
    store.delete("org-a", "solo")

    report = _enrich(settings, "solo")
    assert report.status == "failed"  # type: ignore[attr-defined]
    assert report.reason == "ConfigurationError"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (GscAccountStoreUnavailableError(), "GscAccountStoreUnavailableError"),
        (GscCredentialDecryptionError("acme"), "GscCredentialDecryptionError"),
    ],
)
def test_store_failures_fail_enrichment_not_fall_back(error: Exception, reason: str) -> None:
    # "acme" also exists in `.env.local`: a fail-open path would use it.
    settings = _settings(
        _Store(error=error), gsc_accounts={"acme": {"refresh_token": "rt-env-acme"}}
    )
    report = _enrich(settings, "acme")
    assert report.status == "failed"  # type: ignore[attr-defined]
    assert report.reason == reason  # type: ignore[attr-defined]
