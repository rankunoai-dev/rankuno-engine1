"""Circuit breaker pattern for PostgreSQL connection resilience.

This module implements the circuit breaker pattern to gracefully handle
PostgreSQL outages. When a database connection fails repeatedly, the circuit
opens to stop making requests and falls back to disk storage. After a timeout,
it transitions to half-open state to probe for recovery.

States:
- CLOSED: Normal operation, all requests pass through.
- OPEN: Too many failures; requests fail immediately, fallback is used.
- HALF_OPEN: Probing for recovery; the next request is a probe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["CircuitBreakerState", "CircuitBreaker"]


class CircuitBreakerState(StrEnum):
    """States of the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker for PostgreSQL resilience.

    After 5 consecutive failures, the circuit opens and refuses new requests,
    triggering fallback to disk storage. After 30 seconds in the open state,
    the circuit transitions to half-open and allows one probe request to test
    for recovery.

    Attributes:
        failure_threshold: Number of consecutive failures before opening.
            Default: 5.
        recovery_timeout_s: Time in seconds before attempting recovery probe
            from open state. Default: 30.
    """

    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0

    def __post_init__(self) -> None:
        """Initialize the circuit breaker state."""
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float | None = None

    def record_failure(self, error: Exception) -> None:
        """Record a failure and potentially open the circuit.

        Args:
            error: The exception that was raised during the failed operation.
                Used for logging context (currently just accepted, not stored).
        """
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state is CircuitBreakerState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitBreakerState.OPEN
        elif self._state is CircuitBreakerState.HALF_OPEN:
            # A probe failed; go back to open state
            self._state = CircuitBreakerState.OPEN
            self._failure_count = 1  # Reset to 1 because this was one probe

    def record_success(self) -> None:
        """Record a successful operation and close the circuit if needed.

        If the circuit is half-open, a success closes it and resets
        the failure counter.
        """
        if self._state is CircuitBreakerState.HALF_OPEN:
            # Probe succeeded; we are recovered
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
        elif self._state is CircuitBreakerState.CLOSED:
            # Normal operation: keep failure counter low
            # (no-op since we only increment on failure)
            pass

    def is_open(self) -> bool:
        """Check if the circuit is currently open.

        If the circuit is open but the recovery timeout has elapsed,
        transition to half-open state and return False (allow one probe).

        Returns:
            True if the circuit is open and the recovery timeout has not
            elapsed. False if closed or half-open (allows requests).
        """
        if self._state is CircuitBreakerState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout_s:
                    self._state = CircuitBreakerState.HALF_OPEN
                    return False

            return True

        return False

    def state(self) -> CircuitBreakerState:
        """Return the current state of the circuit breaker.

        Returns:
            The current CircuitBreakerState (CLOSED, OPEN, or HALF_OPEN).
        """
        # Trigger state transition check if needed
        self.is_open()
        return self._state
