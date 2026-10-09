"""Org GSC accounts through the `GscAccountStore` seam (ADR 0036).

The security conditions from the audit, one class each: canaries never leak,
cross-org refusals are indistinguishable, a store outage is a 503 and never a
fall-back, input is bounded without echo, and writes are rate-limited and
audited. The Postgres store runs against the recording fake from the core
tests, so the routes are exercised without the disk org existing at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import Settings
from src.core.errors import GscAccountStoreUnavailableError
from src.core.gsc_account_store import DiskGscAccountStore, GscAccountSummary, UpsertOutcome
from src.core.gsc_credential_crypto import GscCredentialCipher
from src.core.postgres_gsc_account_store import PostgresGscAccountStore
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import DiskJobStore, DiskOrgConfigStore
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import DEFAULT_TEST_OPERATOR_ID, TEST_SESSION_SECRET, auth_headers
from tests.core.test_postgres_gsc_account_store import _FakeConnection, _FakeDB

PUBLIC_IP = "93.184.216.34"
CANARY_TOKEN = "1//0gCANARYrefreshTOKENneverLEAK"  # noqa: S105 - fake canary
CANARY_SECRET = "GOCSPX-CANARYsecretNEVERleak"  # noqa: S105 - fake canary
KEY = bytes(range(32))


class _UnavailableStore:
    """A `GscAccountStore` whose database is down: every call fails closed."""

    def __init__(self) -> None:
        self.calls = 0

    def _fail(self) -> Any:
        self.calls += 1
        raise GscAccountStoreUnavailableError

    def list_accounts(self, org_id: str) -> list[GscAccountSummary]:
        return self._fail()

    def account_names(self, org_id: str) -> frozenset[str]:
        return self._fail()

    def get_credential(self, org_id: str, account_name: str) -> GscAccountCredential | None:
        return self._fail()

    def upsert(
        self, org_id: str, account_name: str, credential: GscAccountCredential, *, operator_id: str
    ) -> UpsertOutcome:
        return self._fail()

    def delete(self, org_id: str, account_name: str) -> bool:
        return self._fail()


class _StubTool:
    """Never crawls: intake is what these tests exercise."""

    def __init__(self, **_kwargs: object) -> None:
        """Accept the real tool's arguments."""

    def run(self, _payload: object) -> object:
        class _Result:
            ok = True
            data: dict[str, object] = {"base_url": "https://e.com/"}
            error = None

        return _Result()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt"),
        # A same-named `.env.local` profile: the trap a fail-open store falls into.
        "gsc_accounts": {"acme": {"refresh_token": "rt-env-acme"}},
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    value = _settings()
    monkeypatch.setattr(server_module, "get_settings", lambda: value)
    monkeypatch.setattr(server_module, "PageClassificationTool", _StubTool)
    return value


@pytest.fixture
def fake_db() -> _FakeDB:
    return _FakeDB()


@pytest.fixture
def pg_store(fake_db: _FakeDB) -> PostgresGscAccountStore:
    return PostgresGscAccountStore(
        GscCredentialCipher(KEY),
        connection_factory=lambda: _FakeConnection(fake_db),  # type: ignore[arg-type, return-value]
    )


def _client(tmp_path: Path, store: Any, *, org_id: str = "org-a") -> TestClient:
    org_store = DiskOrgConfigStore(tmp_path / "orgs")
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=org_store,
        session_secret=TEST_SESSION_SECRET,
        gsc_account_store=store,
    )
    return TestClient(app, headers=auth_headers(org_id=org_id))


def _accounts(org_id: str = "org-a") -> str:
    return f"{API_PREFIX}/orgs/{org_id}/gsc-accounts"


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "account_name": "acme",
        "refresh_token": CANARY_TOKEN,
        "client_id": "123-abc.apps.googleusercontent.com",
        "client_secret": CANARY_SECRET,
    }
    body.update(overrides)
    return body


def _assert_no_canary(text: str) -> None:
    assert CANARY_TOKEN not in text
    assert CANARY_SECRET not in text


class TestPostgresBackedRoutes:
    """The routes need no disk org: Postgres creates its own parent row."""

    def test_create_list_delete_without_a_disk_org(
        self, tmp_path: Path, settings: Settings, pg_store: PostgresGscAccountStore
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            created = client.post(_accounts(), json=_body())
            assert created.status_code == 201, created.text
            assert created.json() == {
                "account_name": "acme",
                "client_id": "123-abc.apps.googleusercontent.com",
                "has_secret_override": True,
            }
            listed = client.get(_accounts())
            assert listed.json()["accounts"][0]["account_name"] == "acme"
            picker = client.get(f"{API_PREFIX}/gsc/accounts")
            assert picker.json() == {"accounts": ["acme"]}
            assert client.delete(f"{_accounts()}/acme").status_code == 204
            assert client.delete(f"{_accounts()}/acme").status_code == 404
            for response in (created, listed, picker):
                _assert_no_canary(response.text)

    def test_api_and_crawl_resolution_read_the_same_store(
        self, tmp_path: Path, settings: Settings, pg_store: PostgresGscAccountStore
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            client.post(_accounts(), json=_body())
        creds = settings.resolve_gsc_account("acme", org_id="org-a", account_store=pg_store)
        # The org's account, not the same-named `.env.local` profile.
        assert creds.refresh_token.get_secret_value() == CANARY_TOKEN


class TestCanariesNeverLeak:
    def test_missing_field_422_does_not_echo_the_body(
        self, tmp_path: Path, settings: Settings, pg_store: PostgresGscAccountStore
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            body = _body()
            del body["account_name"]
            response = client.post(_accounts(), json=body)
        assert response.status_code == 422
        _assert_no_canary(response.text)
        detail = response.json()["detail"]
        assert detail and all("input" not in item and "ctx" not in item for item in detail)
        assert detail[0]["loc"] == ["body", "account_name"]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"account_name": "abc\n"},
            {"account_name": "a" * 65},
            {"account_name": "Acme"},
            {"refresh_token": "x" * 2049},
            {"refresh_token": "has space"},
            {"refresh_token": ""},
            {"client_secret": "s" * 513},
            {"client_id": "c" * 257},
            {"client_id": "bad id!"},
        ],
        ids=[
            "trailing-newline",
            "name-too-long",
            "uppercase",
            "token-too-long",
            "token-space",
            "token-empty",
            "secret-too-long",
            "client-id-too-long",
            "client-id-charset",
        ],
    )
    def test_bad_input_is_422_without_echo(
        self,
        tmp_path: Path,
        settings: Settings,
        pg_store: PostgresGscAccountStore,
        fake_db: _FakeDB,
        overrides: dict[str, object],
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            response = client.post(_accounts(), json=_body(**overrides))
        assert response.status_code == 422, response.text
        _assert_no_canary(response.text)
        for value in overrides.values():
            if isinstance(value, str) and len(value) > 3:
                assert value not in response.text
        assert fake_db.rows == {}

    def test_delete_path_name_is_validated(
        self, tmp_path: Path, settings: Settings, pg_store: PostgresGscAccountStore
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            response = client.delete(f"{_accounts()}/Bad%20Name")
        assert response.status_code == 422
        assert "Bad Name" not in response.text

    def test_logs_and_503_carry_no_secret(
        self,
        tmp_path: Path,
        settings: Settings,
        pg_store: PostgresGscAccountStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG), _client(tmp_path, pg_store) as client:
            client.post(_accounts(), json=_body())
            client.post(_accounts(), json=_body())
            client.get(_accounts())
            client.delete(f"{_accounts()}/acme")
        for record in caplog.records:
            _assert_no_canary(str(record.__dict__))
        with _client(tmp_path, _UnavailableStore()) as client:
            response = client.post(_accounts(), json=_body())
        assert response.status_code == 503
        _assert_no_canary(response.text)


class TestAuditAndRateLimit:
    def test_create_then_replace_then_delete_are_audited(
        self,
        tmp_path: Path,
        settings: Settings,
        pg_store: PostgresGscAccountStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO), _client(tmp_path, pg_store) as client:
            client.post(_accounts(), json=_body())
            client.post(_accounts(), json=_body())
            client.delete(f"{_accounts()}/acme")
        events = [r for r in caplog.records if r.getMessage().startswith("org_gsc_account_")]
        assert [r.getMessage() for r in events] == [
            "org_gsc_account_created",
            "org_gsc_account_replaced",
            "org_gsc_account_deleted",
        ]
        for record in events:
            assert record.org == "org-a"  # type: ignore[attr-defined]
            assert record.account == "acme"  # type: ignore[attr-defined]
            assert record.operator_id == DEFAULT_TEST_OPERATOR_ID  # type: ignore[attr-defined]

    @pytest.mark.parametrize("method", ["post", "delete"])
    def test_writes_are_rate_limited(
        self,
        tmp_path: Path,
        settings: Settings,
        pg_store: PostgresGscAccountStore,
        fake_db: _FakeDB,
        method: str,
    ) -> None:
        with _client(tmp_path, pg_store) as client:
            limiter = client.app.state.api.principal_rate_limiter  # type: ignore[attr-defined]
            limiter.get_or_create(
                f"principal:{DEFAULT_TEST_OPERATOR_ID}", requests_per_minute=1, burst=1
            )
            if method == "post":
                first = client.post(_accounts(), json=_body())
                second = client.post(_accounts(), json=_body(account_name="beta"))
            else:
                first = client.delete(f"{_accounts()}/acme")
                second = client.delete(f"{_accounts()}/acme")
        assert first.status_code in (201, 404)
        assert second.status_code == 429
        assert ("org-a", "beta") not in fake_db.rows


class TestCrossOrgIsIndistinguishable:
    """C3: a 403 for another org reveals nothing about whether it exists."""

    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_existing_and_missing_targets_answer_identically(
        self,
        tmp_path: Path,
        settings: Settings,
        pg_store: PostgresGscAccountStore,
        fake_db: _FakeDB,
        method: str,
    ) -> None:
        with _client(tmp_path, pg_store, org_id="org-b") as victim:
            assert victim.post(_accounts("org-b"), json=_body()).status_code == 201
        before = dict(fake_db.rows)

        def call(client: TestClient, org: str) -> Any:
            if method == "get":
                return client.get(_accounts(org))
            if method == "post":
                return client.post(_accounts(org), json=_body())
            return client.delete(f"{_accounts(org)}/acme")

        with _client(tmp_path, pg_store, org_id="org-a") as attacker:
            real = call(attacker, "org-b")
            missing = call(attacker, "org-zzz")
        assert real.status_code == missing.status_code == 403
        assert real.content == missing.content
        assert fake_db.rows == before


class TestStoreUnavailableFailsClosed:
    """C4: 503 everywhere, and never the same-named `.env.local` profile."""

    def test_every_account_route_is_503(self, tmp_path: Path, settings: Settings) -> None:
        down = _UnavailableStore()
        with _client(tmp_path, down) as client:
            responses = [
                client.get(_accounts()),
                client.post(_accounts(), json=_body()),
                client.delete(f"{_accounts()}/acme"),
                client.get(f"{API_PREFIX}/gsc/accounts"),
            ]
        assert [r.status_code for r in responses] == [503, 503, 503, 503]
        assert all(r.json()["detail"] == str(GscAccountStoreUnavailableError()) for r in responses)

    def test_intake_is_503_and_creates_no_job(self, tmp_path: Path, settings: Settings) -> None:
        jobs_before: list[object]
        with _client(tmp_path, _UnavailableStore(), org_id="default") as client:
            jobs_before = list(client.app.state.api.store.list_jobs())  # type: ignore[attr-defined]
            response = client.post(
                f"{API_PREFIX}/jobs",
                json={
                    "base_url": "https://e.com/",
                    "max_pages": 5,
                    "crawl_dom": False,
                    "gsc_account": "acme",
                },
            )
            jobs_after = list(client.app.state.api.store.list_jobs())  # type: ignore[attr-defined]
        # "acme" exists in `.env.local`; a fail-open store would have let it through.
        assert response.status_code == 503
        assert jobs_after == jobs_before

    def test_no_disk_write_on_outage(self, tmp_path: Path, settings: Settings) -> None:
        with _client(tmp_path, _UnavailableStore()) as client:
            orgs_file = tmp_path / "orgs" / "org_configs.json"
            before = orgs_file.read_bytes()
            client.post(_accounts(), json=_body())
            client.delete(f"{_accounts()}/acme")
        assert orgs_file.read_bytes() == before


class TestDiskSelection:
    """C1 and test 14: with no Postgres, the disk store over the org store is used."""

    def test_injected_org_store_is_wrapped(self, tmp_path: Path, settings: Settings) -> None:
        org_store = DiskOrgConfigStore(tmp_path / "orgs")
        org_store.create(OrgConfig(org_id="org-a", display_name="A"))
        app = create_app(
            store=DiskJobStore(tmp_path / "jobs"),
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_store,
            session_secret=TEST_SESSION_SECRET,
        )
        account_store = app.state.api.gsc_account_store
        assert isinstance(account_store, DiskGscAccountStore)
        assert account_store.org_store is org_store
        with TestClient(app, headers=auth_headers(org_id="org-a")) as client:
            assert client.post(_accounts(), json=_body()).status_code == 201
        stored = org_store.get("org-a").gsc_accounts["acme"]
        assert stored.refresh_token.get_secret_value() == CANARY_TOKEN

    def test_default_is_the_settings_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("DATABASE_URL", "POSTGRES_URL", "DATABASE_PRIVATE_URL", "POSTGRES_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        value = _settings(org_config_path=tmp_path / "orgs")
        monkeypatch.setattr(server_module, "get_settings", lambda: value)
        app = create_app(
            store=DiskJobStore(tmp_path / "jobs"),
            session_secret=TEST_SESSION_SECRET,
        )
        assert app.state.api.gsc_account_store is value.gsc_account_store
        assert isinstance(value.gsc_account_store, DiskGscAccountStore)
