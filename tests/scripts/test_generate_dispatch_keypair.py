"""`scripts/generate_dispatch_keypair.py`: labelled output, and nothing on disk (ADR 0028)."""

from __future__ import annotations

import os

import scripts.generate_dispatch_keypair as generate_dispatch_keypair
from pydantic import SecretStr
from src.core.worker_dispatch_keys import DispatchSigningKey


def _values(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line and " " not in line)


def test_prints_a_matching_labelled_keypair_and_writes_no_files(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert generate_dispatch_keypair.main([]) == 0
    out = capsys.readouterr().out
    assert os.listdir(tmp_path) == [], "the private key must never be written to disk"

    values = _values(out)
    private = DispatchSigningKey.from_secret(
        SecretStr(values["WORKER_DISPATCH_SIGNING_PRIVATE_KEY"])
    )
    assert private.public_key_b64 == values["WORKER_DISPATCH_VERIFY_KEY"]
    assert private.kid == values["kid"]
    assert out.index("SECRET") < out.index("WORKER_DISPATCH_SIGNING_PRIVATE_KEY")
    assert out.index("PUBLIC") < out.index("WORKER_DISPATCH_VERIFY_KEY")


def test_each_run_generates_a_fresh_key(capsys):
    generate_dispatch_keypair.main([])
    first = _values(capsys.readouterr().out)["kid"]
    generate_dispatch_keypair.main([])
    assert _values(capsys.readouterr().out)["kid"] != first
