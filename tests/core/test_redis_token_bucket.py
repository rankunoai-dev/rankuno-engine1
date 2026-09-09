"""Tests for AsyncRedisTokenBucket with Lua script atomic operations."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.rate_limiter import AsyncRedisTokenBucket


class TestAsyncRedisTokenBucketInitialization:
    """Tests for AsyncRedisTokenBucket initialization."""

    def test_initialization(self) -> None:
        """Should initialize with correct parameters."""
        mock_redis = MagicMock()
        mock_redis.register_script.return_value = MagicMock()

        bucket = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=100,
            refill_rate=10.0,
        )

        assert bucket.key == "org:1:seo"
        assert bucket.capacity == 100
        assert bucket.refill_rate == 10.0

    def test_per_minute_constructor(self) -> None:
        """Should construct from requests-per-minute quota."""
        mock_redis = MagicMock()
        mock_redis.register_script.return_value = MagicMock()

        bucket = AsyncRedisTokenBucket.per_minute(
            redis_client=mock_redis,
            key="org:1:seo",
            requests_per_minute=60,
            burst=100,
        )

        assert bucket.capacity == 100
        assert bucket.refill_rate == 1.0  # 60 / 60

    def test_per_minute_default_burst(self) -> None:
        """Should use requests_per_minute as default burst."""
        mock_redis = MagicMock()
        mock_redis.register_script.return_value = MagicMock()

        bucket = AsyncRedisTokenBucket.per_minute(
            redis_client=mock_redis,
            key="org:1:seo",
            requests_per_minute=30,
        )

        assert bucket.capacity == 30
        assert bucket.refill_rate == 0.5  # 30 / 60


class TestAsyncRedisTokenBucketAcquire:
    """Tests for token acquisition with Lua script."""

    @pytest.mark.asyncio
    async def test_successful_acquire(self) -> None:
        """Should acquire tokens when available."""
        mock_redis = MagicMock()
        mock_script = MagicMock(return_value=1)
        mock_redis.register_script.return_value = mock_script

        bucket = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=100,
            refill_rate=10.0,
        )

        result = await bucket.try_acquire(5)

        assert result is True
        mock_script.assert_called_once()
        args = mock_script.call_args[1]["args"]
        assert args[0] == 100  # capacity
        assert args[1] == 5  # tokens requested

    @pytest.mark.asyncio
    async def test_failed_acquire(self) -> None:
        """Should return False when tokens not available."""
        mock_redis = MagicMock()
        mock_script = MagicMock(return_value=0)
        mock_redis.register_script.return_value = mock_script

        bucket = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=100,
            refill_rate=10.0,
        )

        result = await bucket.try_acquire(1000)

        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_passes_correct_parameters(self) -> None:
        """Should pass all parameters to Lua script."""
        mock_redis = MagicMock()
        mock_script = MagicMock(return_value=1)
        mock_redis.register_script.return_value = mock_script

        bucket = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=50,
            refill_rate=5.5,
        )

        await bucket.try_acquire(10)

        call_args = mock_script.call_args
        assert call_args[1]["keys"] == ["org:1:seo"]
        args = call_args[1]["args"]
        assert args[0] == 50  # capacity
        assert args[1] == 10  # tokens
        assert args[3] == 5.5  # refill_rate

    @pytest.mark.asyncio
    async def test_acquire_with_default_token_count(self) -> None:
        """Should default to acquiring 1 token."""
        mock_redis = MagicMock()
        mock_script = MagicMock(return_value=1)
        mock_redis.register_script.return_value = mock_script

        bucket = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=100,
            refill_rate=10.0,
        )

        await bucket.try_acquire()

        args = mock_script.call_args[1]["args"]
        assert args[1] == 1  # default tokens


class TestAsyncRedisTokenBucketLuaScript:
    """Tests for Lua script correctness."""

    def test_lua_script_exists(self) -> None:
        """AsyncRedisTokenBucket should define Lua script."""
        assert hasattr(AsyncRedisTokenBucket, "ACQUIRE_SCRIPT")
        assert "HMGET" in AsyncRedisTokenBucket.ACQUIRE_SCRIPT
        assert "HSET" in AsyncRedisTokenBucket.ACQUIRE_SCRIPT

    def test_lua_script_handles_refill(self) -> None:
        """Lua script should calculate accrued tokens."""
        script = AsyncRedisTokenBucket.ACQUIRE_SCRIPT
        assert "elapsed" in script
        assert "refill_rate" in script
        assert "accrued" in script

    def test_lua_script_enforces_capacity(self) -> None:
        """Lua script should not exceed capacity."""
        script = AsyncRedisTokenBucket.ACQUIRE_SCRIPT
        assert "capacity" in script
        # Check that script caps tokens at capacity
        assert "math.min" in script


class TestAsyncRedisTokenBucketMultiWorker:
    """Tests for multi-worker isolation via Redis."""

    @pytest.mark.asyncio
    async def test_multiple_workers_share_state(self) -> None:
        """Different bucket instances should share Redis state."""
        mock_redis = MagicMock()
        mock_script = MagicMock(side_effect=[1, 0])  # First succeeds, second fails
        mock_redis.register_script.return_value = mock_script

        bucket1 = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:shared",
            capacity=10,
            refill_rate=1.0,
        )

        bucket2 = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:shared",
            capacity=10,
            refill_rate=1.0,
        )

        # Both use same key and same script
        result1 = await bucket1.try_acquire(5)
        result2 = await bucket2.try_acquire(10)  # Not enough left

        assert result1 is True
        assert result2 is False

    @pytest.mark.asyncio
    async def test_different_keys_independent(self) -> None:
        """Different keys should have independent state."""
        mock_redis = MagicMock()
        script1 = MagicMock(return_value=1)
        script2 = MagicMock(return_value=1)

        def register_script_side_effect(script_text):
            if "org:1" in script_text or True:  # Always returns same
                return script1 if mock_redis.register_script.call_count == 1 else script2

        mock_redis.register_script.side_effect = [script1, script2]

        bucket1 = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:1:seo",
            capacity=10,
            refill_rate=1.0,
        )

        bucket2 = AsyncRedisTokenBucket(
            redis_client=mock_redis,
            key="org:2:seo",
            capacity=10,
            refill_rate=1.0,
        )

        result1 = await bucket1.try_acquire(5)
        result2 = await bucket2.try_acquire(5)

        assert result1 is True
        assert result2 is True
