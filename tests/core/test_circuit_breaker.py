"""Tests for the circuit breaker pattern implementation."""

from __future__ import annotations

import time

from src.core.circuit_breaker import CircuitBreaker, CircuitBreakerState


class TestCircuitBreakerBasics:
    """Basic circuit breaker state management tests."""

    def test_initial_state_closed(self) -> None:
        """Circuit breaker should start in CLOSED state."""
        breaker = CircuitBreaker()
        assert breaker.state() == CircuitBreakerState.CLOSED
        assert not breaker.is_open()

    def test_single_failure_keeps_closed(self) -> None:
        """A single failure should not open the circuit."""
        breaker = CircuitBreaker()
        breaker.record_failure(RuntimeError("test"))
        assert breaker.state() == CircuitBreakerState.CLOSED
        assert not breaker.is_open()

    def test_threshold_failures_open_circuit(self) -> None:
        """After 5 failures, the circuit should open."""
        breaker = CircuitBreaker(failure_threshold=5)
        for i in range(4):
            breaker.record_failure(RuntimeError(f"failure {i}"))
            assert breaker.state() == CircuitBreakerState.CLOSED

        # 5th failure opens the circuit
        breaker.record_failure(RuntimeError("failure 5"))
        assert breaker.state() == CircuitBreakerState.OPEN
        assert breaker.is_open()

    def test_custom_failure_threshold(self) -> None:
        """Custom failure threshold should be respected."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure(RuntimeError("1"))
        breaker.record_failure(RuntimeError("2"))
        assert breaker.state() == CircuitBreakerState.CLOSED

        breaker.record_failure(RuntimeError("3"))
        assert breaker.state() == CircuitBreakerState.OPEN


class TestCircuitBreakerRecovery:
    """Tests for circuit breaker recovery mechanism."""

    def test_recovery_timeout_transition_to_half_open(self) -> None:
        """After recovery timeout, open circuit should transition to half-open."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        # Fail once to open
        breaker.record_failure(RuntimeError("fail"))
        assert breaker.state() == CircuitBreakerState.OPEN
        assert breaker.is_open()

        # Wait for recovery timeout
        time.sleep(0.15)

        # is_open() should trigger transition to half-open
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

    def test_probe_success_closes_circuit(self) -> None:
        """A successful operation in half-open state should close the circuit."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        # Fail to open
        breaker.record_failure(RuntimeError("fail"))
        assert breaker.state() == CircuitBreakerState.OPEN

        # Wait for recovery and transition to half-open
        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        # Success in half-open closes the circuit
        breaker.record_success()
        assert breaker.state() == CircuitBreakerState.CLOSED
        assert not breaker.is_open()

    def test_probe_failure_reopens_circuit(self) -> None:
        """A failed operation in half-open state should reopen the circuit."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        # Fail to open
        breaker.record_failure(RuntimeError("fail"))
        assert breaker.state() == CircuitBreakerState.OPEN

        # Wait for recovery and transition to half-open
        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        # Failure in half-open reopens the circuit
        breaker.record_failure(RuntimeError("probe failed"))
        assert breaker.state() == CircuitBreakerState.OPEN
        assert breaker.is_open()

    def test_success_in_closed_state_is_noop(self) -> None:
        """record_success() in CLOSED state should be a no-op."""
        breaker = CircuitBreaker()
        assert breaker.state() == CircuitBreakerState.CLOSED

        breaker.record_success()
        assert breaker.state() == CircuitBreakerState.CLOSED


class TestCircuitBreakerTiming:
    """Tests for circuit breaker timeout and timing behavior."""

    def test_default_recovery_timeout(self) -> None:
        """Default recovery timeout should be 30 seconds."""
        breaker = CircuitBreaker()
        assert breaker.recovery_timeout_s == 30.0

    def test_custom_recovery_timeout(self) -> None:
        """Custom recovery timeout should be used."""
        breaker = CircuitBreaker(recovery_timeout_s=5.0)
        assert breaker.recovery_timeout_s == 5.0

    def test_timeout_before_recovery_keeps_open(self) -> None:
        """Before timeout elapsed, circuit should remain open."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0)

        breaker.record_failure(RuntimeError("fail"))
        assert breaker.is_open()

        # Check immediately after: should still be open
        time.sleep(0.1)
        assert breaker.is_open()

    def test_timeout_after_recovery_allows_probe(self) -> None:
        """After timeout elapsed, circuit should allow probe (return False)."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        breaker.record_failure(RuntimeError("fail"))
        assert breaker.is_open()

        time.sleep(0.15)
        # After timeout, is_open() returns False (allows probe)
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

    def test_multiple_probes_before_success(self) -> None:
        """Multiple failed probes should keep circuit open."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        breaker.record_failure(RuntimeError("initial fail"))
        assert breaker.state() == CircuitBreakerState.OPEN

        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        # Multiple failed probes
        for i in range(3):
            breaker.record_failure(RuntimeError(f"probe fail {i}"))
            assert breaker.state() == CircuitBreakerState.OPEN
            time.sleep(0.15)
            breaker.is_open()
            assert breaker.state() == CircuitBreakerState.HALF_OPEN

    def test_failure_count_reset_on_success(self) -> None:
        """Failure count should reset after successful recovery."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.1)

        # Fail twice (but not yet at threshold)
        breaker.record_failure(RuntimeError("fail 1"))
        breaker.record_failure(RuntimeError("fail 2"))
        assert breaker.state() == CircuitBreakerState.OPEN

        # Recover
        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        breaker.record_success()
        assert breaker.state() == CircuitBreakerState.CLOSED

        # Now it should take 2 more failures to open again
        breaker.record_failure(RuntimeError("new fail 1"))
        assert breaker.state() == CircuitBreakerState.CLOSED

        breaker.record_failure(RuntimeError("new fail 2"))
        assert breaker.state() == CircuitBreakerState.OPEN


class TestCircuitBreakerEdgeCases:
    """Edge case and boundary condition tests."""

    def test_state_method_triggers_recovery_check(self) -> None:
        """state() method should check for recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        breaker.record_failure(RuntimeError("fail"))
        assert breaker.state() == CircuitBreakerState.OPEN

        time.sleep(0.15)
        # Calling state() should trigger the recovery check
        state = breaker.state()
        assert state == CircuitBreakerState.HALF_OPEN

    def test_is_open_idempotent_before_recovery(self) -> None:
        """Multiple is_open() calls before recovery should return True."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0)

        breaker.record_failure(RuntimeError("fail"))
        assert breaker.is_open()
        assert breaker.is_open()
        assert breaker.is_open()
        assert breaker.state() == CircuitBreakerState.OPEN

    def test_is_open_idempotent_after_recovery(self) -> None:
        """Multiple is_open() calls after recovery should transition once."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        breaker.record_failure(RuntimeError("fail"))
        time.sleep(0.15)

        # First call transitions to half-open
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        # Second call should remain half-open (no transition)
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

    def test_failure_updates_timestamp(self) -> None:
        """Each failure should update the last_failure_time."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_s=1.0)

        breaker.record_failure(RuntimeError("fail 1"))
        time.sleep(0.1)
        breaker.record_failure(RuntimeError("fail 2"))
        time.sleep(0.1)
        breaker.record_failure(RuntimeError("fail 3"))

        # Wait a bit and verify circuit is open
        assert breaker.is_open()
        assert breaker.state() == CircuitBreakerState.OPEN

        # Sleep past the original timeout but before the new one
        time.sleep(0.95)
        # Should still be open because last failure was ~0.1s ago
        assert breaker.is_open()


class TestCircuitBreakerIntegration:
    """Integration tests for realistic usage patterns."""

    def test_fallback_activation_pattern(self) -> None:
        """Typical fallback activation: open circuit triggers disk fallback."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.5)

        # Primary (PostgreSQL) fails
        breaker.record_failure(RuntimeError("postgres connection failed"))
        assert not breaker.is_open()  # Still operational

        # Keep failing
        breaker.record_failure(RuntimeError("postgres still down"))
        assert breaker.is_open()  # Fallback activates

        # Wait for recovery probe
        time.sleep(0.55)
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.HALF_OPEN

        # Probe succeeds
        breaker.record_success()
        assert not breaker.is_open()
        assert breaker.state() == CircuitBreakerState.CLOSED

    def test_cascading_failures_and_recovery(self) -> None:
        """Multiple failure cycles should not accumulate state."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.1)

        # First cycle: fail and recover
        breaker.record_failure(RuntimeError("fail"))
        time.sleep(0.15)
        breaker.is_open()
        breaker.record_success()
        assert breaker.state() == CircuitBreakerState.CLOSED

        # Second cycle: fail and recover
        breaker.record_failure(RuntimeError("fail again"))
        time.sleep(0.15)
        breaker.is_open()
        breaker.record_success()
        assert breaker.state() == CircuitBreakerState.CLOSED

        # Circuit should still work normally
        assert not breaker.is_open()
