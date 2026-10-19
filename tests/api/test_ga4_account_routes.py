"""GA4 access routes and crawl intake (ADR 0038).

Two properties are tested throughout: an organisation reads and changes only
its own GA4 state (a foreign org and an unknown org get the same refusal), and
no token, secret or response body reaches a browser or a log. The GA4 store and
the Google connector are fakes, so no test contacts Google or a database.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import ga4_account_routes as routes
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.errors import (
    Ga4AccessStoreUnavailableError,
    Ga4NotAuthorizedError,
    Ga4UnavailableError,
)
from src.core.ga4_access_store import Ga4AccessSummary
from src.core.state_store import DiskJobStore, DiskOrgConfigStore
from src.core.url_safety import UrlSafetyPolicy
from src.integrations.ga4_schemas import Ga4AccessToken, Ga4PropertyChoice, Ga4PropertyList

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"
TOKEN_CANARY = "1//0gROUTE-GA4-TOKEN-CANARY"  # noqa: S105 - fake canary
BODY_CANARY = "GOOGLE-ERROR-BODY-CANARY"
PROPERTY = "123456789"
OTHER_PROPERTY = "987654321"
GSC_REASON = "not authorized, re-add the account"


class MemoryGa4Store:
    """An in-memory `Ga4AccessStore`, keyed by org, with a switch for outages."""

    def __init__(self) -> None:
        """Test double: the store starts empty."""
        self.rows: dict[str, dict[str, Any]] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise Ga4AccessStoreUnavailableError

    def status(self, org_id: str) -> Ga4AccessSummary:
        self._check()
        row = self.rows.get(org_id)
        if row is None:
            return Ga4AccessSummary(has_credential=False, property_id=None)
        return Ga4AccessSummary(has_credential=True, property_id=row["property_id"])

    def refresh_token(self, org_id: str) -> SecretStr | None:
        self._check()
        row = self.rows.get(org_id)
        return None if row is None else SecretStr(row["token"])

    def set_credential(self, org_id: str, refresh_token: SecretStr, *, operator_id: str) -> None:
        self._check()
        self.rows[org_id] = {"token": refresh_token.get_secret_value(), "property_id": None}

    def set_property(self, org_id: str, property_id: str, *, operator_id: str) -> bool:
        self._check()
        if org_id not in self.rows:
            return False
        self.rows[org_id]["property_id"] = property_id
        return True

    def delete(self, org_id: str, *, operator_id: str) -> bool:
        self._check()
        return self.rows.pop(org_id, None) is not None


class FakeGoogle:
    """Scripted behaviour for the connector the routes construct."""

    refresh_error: Exception | None = None
    list_error: Exception | None = None
    listing = Ga4PropertyList(
        properties=(Ga4PropertyChoice(property_id=PROPERTY, display_name="Acme site"),),
        truncated=False,
    )


class FakeGa4Client:
    def __init__(self, settings: object = None) -> None:
        """Test double: the connector needs no setup here."""
        return

    def refresh_access_token(self, refresh_token: SecretStr) -> Ga4AccessToken:
        if FakeGoogle.refresh_error is not None:
            raise FakeGoogle.refresh_error
        return Ga4AccessToken(access_token=SecretStr("ACCESS"))

    def list_properties(self, token: Ga4AccessToken) -> Ga4PropertyList:
        if FakeGoogle.list_error is not None:
            raise FakeGoogle.list_error
        return FakeGoogle.listing


class StubResult:
    ok = True
    data: dict[str, object] = {"base_url": SAFE_URL}
    error: str | None = None


class StubTool:
    """A `PageClassificationTool` that returns instantly instead of crawling."""

    def __init__(self, **_kwargs: object) -> None:
        """Accept and ignore the real tool's constructor arguments."""

    def run(self, _payload: object) -> StubResult:
        return StubResult()


@pytest.fixture(autouse=True)
def _reset_google(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeGoogle.refresh_error = None
    FakeGoogle.list_error = None
    FakeGoogle.listing = Ga4PropertyList(
        properties=(Ga4PropertyChoice(property_id=PROPERTY, display_name="Acme site"),),
        truncated=False,
    )
    monkeypatch.setattr(routes, "Ga4ApiClient", FakeGa4Client)


@pytest.fixture
def memory() -> MemoryGa4Store:
    return MemoryGa4Store()


@pytest.fixture
def client(tmp_path, memory: MemoryGa4Store, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=DiskOrgConfigStore(tmp_path / "orgs"),
        session_secret=TEST_SESSION_SECRET,
        ga4_access_store=memory,
    )
    with TestClient(app, headers=auth_headers()) as test_client:
        yield test_client


def _as(org_id: str) -> dict[str, str]:
    return auth_headers(org_id=org_id)


# ---- auth and tenancy ---------------------------------------------------------


def test_every_route_requires_a_session(client: TestClient) -> None:
    # A client with no default Authorization header: per-request headers merge
    # with the fixture's, so the anonymous case needs its own client.
    anonymous = TestClient(client.app)
    assert anonymous.get(f"{API_PREFIX}/orgs/default/ga4").status_code == 401
    assert anonymous.get(f"{API_PREFIX}/ga4/mapping").status_code == 401
    assert anonymous.get(f"{API_PREFIX}/orgs/default/ga4/properties").status_code == 401
    assert (
        anonymous.put(
            f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": "x"}
        ).status_code
        == 401
    )


def test_a_foreign_org_and_an_unknown_org_get_the_same_refusal(client: TestClient) -> None:
    foreign = client.get(f"{API_PREFIX}/orgs/globex/ga4")
    unknown = client.get(f"{API_PREFIX}/orgs/ghost-org/ga4")
    assert foreign.status_code == unknown.status_code == 403
    assert foreign.json() == unknown.json() == {"detail": "access denied"}


def test_a_foreign_org_cannot_store_a_credential_or_map_a_property(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["globex"] = {"token": "theirs", "property_id": None}
    put_credential = client.put(
        f"{API_PREFIX}/orgs/globex/ga4/credential", json={"refresh_token": TOKEN_CANARY}
    )
    put_property = client.put(
        f"{API_PREFIX}/orgs/globex/ga4/property", json={"property_id": PROPERTY}
    )
    delete = client.delete(f"{API_PREFIX}/orgs/globex/ga4")
    assert put_credential.status_code == put_property.status_code == delete.status_code == 403
    assert memory.rows["globex"] == {"token": "theirs", "property_id": None}


def test_a_foreign_org_gets_no_listing_from_my_credential(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    assert client.get(f"{API_PREFIX}/orgs/globex/ga4/properties").status_code == 403


# ---- status and the credential ------------------------------------------------


def test_a_new_org_is_not_configured(client: TestClient) -> None:
    body = client.get(f"{API_PREFIX}/orgs/default/ga4").json()
    assert body == {"status": "not_configured", "property_id": None}


def test_saving_a_credential_the_scope_gate_refuses_stores_nothing(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    FakeGoogle.refresh_error = Ga4NotAuthorizedError()
    response = client.put(
        f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": TOKEN_CANARY}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": GSC_REASON}
    assert memory.rows == {}
    assert TOKEN_CANARY not in response.text


def test_saving_a_credential_while_google_is_down_stores_nothing(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    FakeGoogle.refresh_error = Ga4UnavailableError()
    response = client.put(
        f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": TOKEN_CANARY}
    )
    assert response.status_code == 503
    assert memory.rows == {}


def test_a_verified_credential_is_stored_unmapped_and_never_echoed(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    response = client.put(
        f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": TOKEN_CANARY}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "unmapped", "property_id": None}
    assert memory.rows["default"]["token"] == TOKEN_CANARY
    assert TOKEN_CANARY not in response.text


@pytest.mark.parametrize("bad", ["has space", "x" * 2049, "tab\there", ""])
def test_a_malformed_token_is_refused_and_not_echoed(client: TestClient, bad: str) -> None:
    response = client.put(f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": bad})
    assert response.status_code == 422
    if bad:
        assert bad not in response.text


def test_without_a_store_every_write_is_503_and_the_read_is_not_configured(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=DiskOrgConfigStore(tmp_path / "orgs"),
        session_secret=TEST_SESSION_SECRET,
        ga4_access_store=None,
    )
    with TestClient(app, headers=auth_headers()) as test_client:
        assert (
            test_client.get(f"{API_PREFIX}/orgs/default/ga4").json()["status"] == "not_configured"
        )
        put = test_client.put(
            f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": TOKEN_CANARY}
        )
        assert put.status_code == 503
        assert put.json() == {"detail": "GA4 is not configured on this server"}


def test_a_store_outage_is_a_fixed_503(client: TestClient, memory: MemoryGa4Store) -> None:
    memory.down = True
    response = client.get(f"{API_PREFIX}/orgs/default/ga4")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


# ---- the property picker ------------------------------------------------------


def test_the_picker_says_not_configured_when_no_credential_is_stored(client: TestClient) -> None:
    body = client.get(f"{API_PREFIX}/orgs/default/ga4/properties").json()
    assert body["status"] == "not_configured"
    assert body["properties"] == []
    assert body["reason"]


def test_the_picker_lists_what_the_stored_credential_can_see(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    body = client.get(f"{API_PREFIX}/orgs/default/ga4/properties").json()
    assert body == {
        "status": "ok",
        "reason": "",
        "truncated": False,
        "properties": [{"property_id": PROPERTY, "display_name": "Acme site"}],
    }
    assert TOKEN_CANARY not in client.get(f"{API_PREFIX}/orgs/default/ga4/properties").text


def test_a_gsc_only_credential_says_not_authorized_not_empty(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    FakeGoogle.list_error = Ga4NotAuthorizedError()
    body = client.get(f"{API_PREFIX}/orgs/default/ga4/properties").json()
    assert body["status"] == "not_authorized"
    assert body["reason"] == GSC_REASON
    assert body["properties"] == []


def test_an_outage_on_the_picker_is_unavailable_not_empty(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    FakeGoogle.list_error = Ga4UnavailableError()
    body = client.get(f"{API_PREFIX}/orgs/default/ga4/properties").json()
    assert body["status"] == "unavailable"
    assert body["reason"]
    assert BODY_CANARY not in client.get(f"{API_PREFIX}/orgs/default/ga4/properties").text


def test_a_truncated_listing_says_so(client: TestClient, memory: MemoryGa4Store) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    FakeGoogle.listing = Ga4PropertyList(properties=(), truncated=True)
    assert client.get(f"{API_PREFIX}/orgs/default/ga4/properties").json()["truncated"] is True


def test_mapping_a_visible_property_is_mapped(client: TestClient, memory: MemoryGa4Store) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    response = client.put(f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": PROPERTY})
    assert response.status_code == 200
    assert response.json() == {"status": "mapped", "property_id": PROPERTY}
    assert client.get(f"{API_PREFIX}/ga4/mapping").json()["property_id"] == PROPERTY


def test_mapping_a_property_the_credential_cannot_see_is_refused(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    response = client.put(
        f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": OTHER_PROPERTY}
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "that property is not visible to the stored GA4 credential"
    }
    assert memory.rows["default"]["property_id"] is None


def test_a_property_missing_from_a_truncated_listing_is_not_guessed(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    FakeGoogle.listing = Ga4PropertyList(properties=(), truncated=True)
    response = client.put(
        f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": OTHER_PROPERTY}
    )
    assert response.status_code == 422
    assert "listed GA4 properties" in response.json()["detail"]


def test_mapping_without_a_credential_is_refused(client: TestClient) -> None:
    response = client.put(f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": PROPERTY})
    assert response.status_code == 422
    assert "no GA4 credential" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["0123", "12 3", "properties/1", "123\n", "9" * 21])
def test_a_malformed_property_id_is_refused_at_the_boundary(
    client: TestClient, memory: MemoryGa4Store, bad: str
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    response = client.put(f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": bad})
    assert response.status_code == 422
    assert memory.rows["default"]["property_id"] is None


def test_removal_clears_the_credential_and_the_mapping(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": PROPERTY}
    assert client.delete(f"{API_PREFIX}/orgs/default/ga4").status_code == 204
    assert client.get(f"{API_PREFIX}/orgs/default/ga4").json()["status"] == "not_configured"
    assert client.delete(f"{API_PREFIX}/orgs/default/ga4").status_code == 404


def test_the_crawl_form_reads_its_own_orgs_mapping(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["globex"] = {"token": "theirs", "property_id": OTHER_PROPERTY}
    assert client.get(f"{API_PREFIX}/ga4/mapping").json()["status"] == "not_configured"
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": PROPERTY}
    assert client.get(f"{API_PREFIX}/ga4/mapping").json() == {
        "status": "mapped",
        "property_id": PROPERTY,
    }
    globex = client.get(f"{API_PREFIX}/ga4/mapping", headers=_as("globex"))
    assert globex.json() == {"status": "mapped", "property_id": OTHER_PROPERTY}


# ---- audit ----------------------------------------------------------------------


def test_each_write_is_audited_with_org_operator_and_action_only(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    client.put(f"{API_PREFIX}/orgs/default/ga4/credential", json={"refresh_token": TOKEN_CANARY})
    client.put(f"{API_PREFIX}/orgs/default/ga4/property", json={"property_id": PROPERTY})
    client.delete(f"{API_PREFIX}/orgs/default/ga4")
    records = [r for r in caplog.records if r.getMessage() == "org_ga4_access_audit"]
    assert [getattr(r, "action", None) for r in records] == [
        "credential_saved",
        "property_mapped",
        "access_removed",
    ]
    for record in records:
        assert getattr(record, "org", None) == "default"
        assert getattr(record, "operator_id", None) == "test-operator"
    assert TOKEN_CANARY not in caplog.text
    assert PROPERTY not in caplog.text


# ---- crawl intake ---------------------------------------------------------------


def _post_job(client: TestClient, **overrides: object) -> Any:
    body = {"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False, **overrides}
    return client.post(f"{API_PREFIX}/jobs", json=body)


def test_a_crawl_naming_an_unmapped_property_is_refused_with_a_fixed_reason(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": None}
    response = _post_job(client, ga4_property_id=PROPERTY)
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "the requested GA4 property is not mapped for this organisation"
    )


def test_a_crawl_naming_another_orgs_property_is_refused(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": PROPERTY}
    response = _post_job(client, ga4_property_id=OTHER_PROPERTY)
    assert response.status_code == 400


def test_a_crawl_naming_the_mapped_property_is_admitted(
    client: TestClient, memory: MemoryGa4Store
) -> None:
    memory.rows["default"] = {"token": TOKEN_CANARY, "property_id": PROPERTY}
    response = _post_job(client, ga4_property_id=PROPERTY)
    assert response.status_code < 400, response.text


def test_a_crawl_without_ga4_is_unaffected(client: TestClient) -> None:
    response = _post_job(client)
    assert response.status_code < 400, response.text


def test_a_crawl_naming_a_property_with_no_store_is_refused(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=DiskOrgConfigStore(tmp_path / "orgs"),
        session_secret=TEST_SESSION_SECRET,
        ga4_access_store=None,
    )
    with TestClient(app, headers=auth_headers()) as test_client:
        response = _post_job(test_client, ga4_property_id=PROPERTY)
        assert response.status_code == 400
        assert response.json() == {"detail": "GA4 is not configured on this server"}
