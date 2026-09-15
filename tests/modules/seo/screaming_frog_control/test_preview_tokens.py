"""Tests for `PreviewTokenStore` — the preview -> confirm HITL exchange."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.core.schemas import RiskClass, ToolMetadata
from src.modules.seo.screaming_frog_control.preview_tokens import (
    PreviewTokenStore,
    make_approval_callback,
)

_BINDING = {"org_id": "default", "seed_url": "https://example.com/", "template_name": "acme"}


class TestMintAndPeek:
    def test_a_freshly_minted_token_peeks_valid(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        assert store.peek(record.token, **_BINDING) is True

    def test_peek_does_not_consume(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        store.peek(record.token, **_BINDING)
        assert store.peek(record.token, **_BINDING) is True

    def test_unknown_token_is_invalid(self) -> None:
        store = PreviewTokenStore()
        assert store.peek("not-a-real-token", **_BINDING) is False

    def test_wrong_org_fails_the_exact_binding_check(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        mismatched = {**_BINDING, "org_id": "someone-else"}
        assert store.peek(record.token, **mismatched) is False

    def test_wrong_seed_url_fails_the_exact_binding_check(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        mismatched = {**_BINDING, "seed_url": "https://not-the-approved-url.example/"}
        assert store.peek(record.token, **mismatched) is False

    def test_wrong_template_fails_the_exact_binding_check(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        mismatched = {**_BINDING, "template_name": "different-template"}
        assert store.peek(record.token, **mismatched) is False

    def test_none_template_is_a_distinct_valid_binding(self) -> None:
        store = PreviewTokenStore()
        binding = {**_BINDING, "template_name": None}
        record = store.mint(**binding)
        assert store.peek(record.token, **binding) is True


class TestConsume:
    def test_consume_burns_a_valid_token_exactly_once(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        assert store.consume(record.token, **_BINDING) is True
        assert store.consume(record.token, **_BINDING) is False

    def test_consume_of_an_unknown_token_is_false(self) -> None:
        store = PreviewTokenStore()
        assert store.consume("nope", **_BINDING) is False

    def test_a_consumed_token_also_fails_a_later_peek(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        store.consume(record.token, **_BINDING)
        assert store.peek(record.token, **_BINDING) is False


class TestExpiry:
    def test_an_expired_token_is_invalid(self) -> None:
        store = PreviewTokenStore(ttl_s=-1.0)  # already expired the instant it is minted
        record = store.mint(**_BINDING)
        assert store.peek(record.token, **_BINDING) is False
        assert store.consume(record.token, **_BINDING) is False

    def test_expires_at_reflects_the_configured_ttl(self) -> None:
        store = PreviewTokenStore(ttl_s=60.0)
        before = datetime.now(UTC)
        record = store.mint(**_BINDING)
        assert record.expires_at - before <= timedelta(seconds=61)
        assert record.expires_at - before >= timedelta(seconds=59)


class TestMakeApprovalCallback:
    def test_callback_returns_true_only_for_a_matching_valid_token(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        callback = make_approval_callback(store, token=record.token, **_BINDING)
        metadata = ToolMetadata(
            name="seo.screaming_frog_control", summary="test", risk_class=RiskClass.WRITE
        )

        assert callback(metadata, "some context") is True
        # Calling it again proves it actually consumed the token, not just peeked.
        assert callback(metadata, "some context") is False

    def test_callback_denies_a_mismatched_binding(self) -> None:
        store = PreviewTokenStore()
        record = store.mint(**_BINDING)
        wrong_binding = {**_BINDING, "seed_url": "https://attacker.example/"}
        callback = make_approval_callback(store, token=record.token, **wrong_binding)
        metadata = ToolMetadata(
            name="seo.screaming_frog_control", summary="test", risk_class=RiskClass.WRITE
        )

        assert callback(metadata, "context") is False
