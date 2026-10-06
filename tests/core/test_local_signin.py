"""Tests for `LocalSigninGate`: at most once, within the TTL, never after lockout (ADR 0033)."""

from __future__ import annotations

import threading

from pydantic import SecretStr
from src.core.local_signin import MAX_FAILURES, LocalSigninGate, SigninOutcome

TOKEN = "ab" * 32
WRONG = "cd" * 32


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _gate(clock: _Clock | None = None, ttl_s: float = 300.0) -> LocalSigninGate:
    return LocalSigninGate(SecretStr(TOKEN), ttl_s=ttl_s, clock=clock or _Clock())


def test_the_right_token_is_accepted_once() -> None:
    gate = _gate()
    assert gate.redeem(TOKEN) is SigninOutcome.OK
    assert gate.redeem(TOKEN) is SigninOutcome.CONSUMED


def test_a_wrong_token_is_a_mismatch_and_leaves_the_link_usable() -> None:
    gate = _gate()
    assert gate.redeem(WRONG) is SigninOutcome.MISMATCH
    assert gate.redeem(TOKEN) is SigninOutcome.OK


def test_five_mismatches_disarm_the_gate_for_good() -> None:
    gate = _gate()
    for _ in range(MAX_FAILURES):
        assert gate.redeem(WRONG) is SigninOutcome.MISMATCH
    assert gate.redeem(TOKEN) is SigninOutcome.LOCKED
    assert gate.redeem(WRONG) is SigninOutcome.LOCKED


def test_the_link_expires_after_its_ttl() -> None:
    clock = _Clock()
    gate = _gate(clock)
    clock.now += 300.0
    assert gate.redeem(TOKEN) is SigninOutcome.EXPIRED
    clock.now -= 1.0  # a clock that went back does not revive a dropped digest
    assert gate.redeem(TOKEN) is SigninOutcome.EXPIRED


def test_just_inside_the_ttl_is_accepted() -> None:
    clock = _Clock()
    gate = _gate(clock)
    clock.now += 299.9
    assert gate.redeem(TOKEN) is SigninOutcome.OK


def test_the_gate_holds_no_plaintext_token() -> None:
    gate = _gate()
    for value in vars(gate).values():
        assert TOKEN not in repr(value)
        assert TOKEN.encode() != value


def test_success_clears_the_digest() -> None:
    gate = _gate()
    gate.redeem(TOKEN)
    assert gate._digest is None


def test_racing_requests_with_the_right_token_succeed_exactly_once() -> None:
    gate = _gate()
    start = threading.Barrier(20)
    outcomes: list[SigninOutcome] = []
    lock = threading.Lock()

    def attempt() -> None:
        start.wait()
        outcome = gate.redeem(TOKEN)
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(SigninOutcome.OK) == 1
    assert outcomes.count(SigninOutcome.CONSUMED) == 19
