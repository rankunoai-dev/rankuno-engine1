"""Tests for the signal weight profiles and the site-profile selection seam."""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.schemas import SIGNAL_WEIGHTS, SignalSource
from src.modules.seo.page_classifier.weights import (
    ADAPTIVE_WEIGHTS_ENABLED,
    DEFAULT_PROFILE,
    WEIGHT_PROFILES,
    CmsFamily,
    SiteProfile,
    WeightProfileReport,
    get_weight_profile,
    resolve_profile_name,
)


class TestProfileIntegrity:
    def test_all_four_profiles_are_declared(self):
        assert set(WEIGHT_PROFILES) == {DEFAULT_PROFILE, "wordpress", "shopify", "headless"}

    @pytest.mark.parametrize("name", ["default", "wordpress", "shopify", "headless"])
    def test_every_profile_sums_to_one(self, name):
        """A vector that does not sum to 1.0 silently rescales every confidence."""
        assert sum(WEIGHT_PROFILES[name].values()) == pytest.approx(1.0)

    @pytest.mark.parametrize("name", ["default", "wordpress", "shopify", "headless"])
    def test_no_negative_weights(self, name):
        assert all(w >= 0.0 for w in WEIGHT_PROFILES[name].values())

    def test_default_is_the_specified_baseline(self):
        """The only calibrated vector; it must stay identical to the blueprint."""
        assert WEIGHT_PROFILES[DEFAULT_PROFILE] == SIGNAL_WEIGHTS

    def test_profiles_are_immutable(self):
        with pytest.raises(TypeError):
            WEIGHT_PROFILES["shopify"][SignalSource.ARIA_NAV_TREE] = 0.9  # type: ignore[index]

    def test_headless_drops_the_cms_signal_entirely(self):
        """No content API exists, so its weight must redistribute, not linger."""
        assert WEIGHT_PROFILES["headless"][SignalSource.CMS_API_ENDPOINT] == pytest.approx(0.0)
        assert (
            WEIGHT_PROFILES["headless"][SignalSource.ARIA_NAV_TREE]
            > SIGNAL_WEIGHTS[SignalSource.ARIA_NAV_TREE]
        )

    def test_shopify_trusts_the_content_api_most(self):
        cms = WEIGHT_PROFILES["shopify"][SignalSource.CMS_API_ENDPOINT]
        assert cms == max(WEIGHT_PROFILES["shopify"].values())
        assert cms > SIGNAL_WEIGHTS[SignalSource.CMS_API_ENDPOINT]


class TestProfileResolution:
    @pytest.mark.parametrize(
        ("family", "expected"),
        [
            (CmsFamily.WORDPRESS, "wordpress"),
            (CmsFamily.SHOPIFY, "shopify"),
            (CmsFamily.HEADLESS, "headless"),
            (CmsFamily.UNKNOWN, DEFAULT_PROFILE),
        ],
    )
    def test_maps_cms_family_to_profile(self, family, expected):
        assert resolve_profile_name(SiteProfile(cms_family=family)) == expected

    def test_unprofiled_site_uses_the_default(self):
        assert resolve_profile_name(None) == DEFAULT_PROFILE

    def test_client_side_rendering_wins_over_unknown_cms(self):
        """If the content API is unreachable, what generated the markup is moot."""
        profile = SiteProfile(cms_family=CmsFamily.UNKNOWN, renders_client_side=True)
        assert resolve_profile_name(profile) == "headless"

    def test_known_cms_survives_client_side_rendering(self):
        """A headless WordPress still exposes /wp-json, so keep its profile."""
        profile = SiteProfile(cms_family=CmsFamily.WORDPRESS, renders_client_side=True)
        assert resolve_profile_name(profile) == "wordpress"

    def test_site_profile_exposes_its_own_name(self):
        assert SiteProfile(cms_family=CmsFamily.SHOPIFY).weight_profile_name == "shopify"


class TestSeamBehaviour:
    def test_adaptive_selection_is_off_until_calibrated(self):
        """Four uncalibrated vectors would be worse than one specified baseline."""
        assert ADAPTIVE_WEIGHTS_ENABLED is False

    @pytest.mark.parametrize(
        "profile",
        [
            None,
            SiteProfile(cms_family=CmsFamily.SHOPIFY),
            SiteProfile(cms_family=CmsFamily.WORDPRESS),
            SiteProfile(cms_family=CmsFamily.UNKNOWN, renders_client_side=True),
        ],
    )
    def test_every_site_currently_gets_the_default_vector(self, profile):
        assert get_weight_profile(profile) == WEIGHT_PROFILES[DEFAULT_PROFILE]

    def test_seam_returns_a_usable_vector_with_no_arguments(self):
        weights = get_weight_profile()
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_enabling_adaptation_selects_per_profile(self, monkeypatch):
        """Proves the seam is real: flipping one flag changes the vector."""
        monkeypatch.setattr(
            "src.modules.seo.page_classifier.weights.ADAPTIVE_WEIGHTS_ENABLED", True
        )
        selected = get_weight_profile(SiteProfile(cms_family=CmsFamily.SHOPIFY))
        assert selected == WEIGHT_PROFILES["shopify"]
        assert selected != WEIGHT_PROFILES[DEFAULT_PROFILE]


class TestReporting:
    def test_reports_applied_and_detected_separately(self):
        """A reviewer must be able to tell weighting from genuine difference."""
        report = WeightProfileReport.for_site(SiteProfile(cms_family=CmsFamily.SHOPIFY))
        assert report.detected_profile_name == "shopify"
        assert report.profile_name == DEFAULT_PROFILE
        assert report.adaptive_enabled is False

    def test_unprofiled_site_reports_default_for_both(self):
        report = WeightProfileReport.for_site(None)
        assert report.profile_name == report.detected_profile_name == DEFAULT_PROFILE
