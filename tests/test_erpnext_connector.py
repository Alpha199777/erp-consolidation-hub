import pytest
import requests

from hub.connectors.erpnext import ERPNextConnector


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def rec(i, **kw):
    base = {"name": f"Client {i}", "customer_name": f"Client {i}", "email_id": "",
            "mobile_no": "", "disabled": 0, "customer_type": "Company",
            "modified": "2026-09-30 15:15:32.185497"}
    base.update(kw)
    return base


def make_fake_get(records):
    """Simule l'API : découpe `records` en pages via limit_start / limit_page_length."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params})
        start, size = params["limit_start"], params["limit_page_length"]
        return FakeResponse(200, {"data": records[start:start + size]})

    return fake_get, calls


def connector(page_size=100):
    return ERPNextConnector("http://x", "key", "secret", page_size=page_size)


# --- from_env -----------------------------------------------------------

def test_from_env_returns_none_when_a_variable_is_missing(monkeypatch):
    for name in ("ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET"):
        monkeypatch.setenv("ERPNEXT_URL", "http://x")
        monkeypatch.setenv("ERPNEXT_API_KEY", "k")
        monkeypatch.setenv("ERPNEXT_API_SECRET", "s")
        monkeypatch.delenv(name)
        assert ERPNextConnector.from_env() is None


def test_from_env_builds_connector(monkeypatch):
    monkeypatch.setenv("ERPNEXT_URL", "http://x/")
    monkeypatch.setenv("ERPNEXT_API_KEY", "k")
    monkeypatch.setenv("ERPNEXT_API_SECRET", "s")
    c = ERPNextConnector.from_env()
    assert c.url == "http://x"
    assert c.api_key == "k"
    assert c.api_secret == "s"


# --- normalize ----------------------------------------------------------

def test_normalize_maps_fields():
    c = connector().normalize(
        rec(1, name="CUST-1", customer_name="Grant Plastics Ltd.",
            email_id="a@b.fr", mobile_no="0102"))
    assert c.source == "erpnext"
    assert c.source_id == "CUST-1"
    assert c.name == "Grant Plastics Ltd."
    assert c.email == "a@b.fr"
    assert c.phone == "0102"


def test_normalize_empty_values_become_none_and_address_fields_are_none():
    c = connector().normalize(rec(1, email_id="", mobile_no="  "))
    assert c.email is None
    assert c.phone is None
    assert c.city is None
    assert c.postal_code is None
    assert c.country is None


def test_normalize_keeps_raw_payload():
    record = rec(2, customer_group="Demo Customer Group")
    assert connector().normalize(record).payload == record


# --- fetch_customers ----------------------------------------------------

def test_fetch_returns_all_customers_including_disabled(monkeypatch):
    fake, _ = make_fake_get([rec(1), rec(2, disabled=1)])
    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake)
    assert len(connector().fetch_customers()) == 2


def test_fetch_paginates_with_partial_last_page(monkeypatch):
    fake, calls = make_fake_get([rec(i) for i in range(5)])
    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake)
    assert len(connector(page_size=2).fetch_customers()) == 5
    assert len(calls) == 3


def test_fetch_paginates_until_empty_page(monkeypatch):
    fake, calls = make_fake_get([rec(i) for i in range(4)])
    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake)
    assert len(connector(page_size=2).fetch_customers()) == 4
    assert len(calls) == 3  # la 3e page est vide


def test_fetch_empty_returns_empty_list(monkeypatch):
    fake, _ = make_fake_get([])
    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake)
    assert connector().fetch_customers() == []


def test_fetch_sends_token_header(monkeypatch):
    fake, calls = make_fake_get([rec(1)])
    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake)
    connector().fetch_customers()
    assert calls[0]["headers"]["Authorization"] == "token key:secret"


def test_fetch_raises_on_unauthorized(monkeypatch):
    monkeypatch.setattr("hub.connectors.erpnext.requests.get",
                        lambda *a, **k: FakeResponse(401))
    with pytest.raises(requests.HTTPError):
        connector().fetch_customers()


# --- ping ---------------------------------------------------------------

def test_ping_true_on_200_and_uses_authenticated_endpoint(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return FakeResponse(200, {"message": "admin"})

    monkeypatch.setattr("hub.connectors.erpnext.requests.get", fake_get)
    assert connector().ping() is True
    assert seen["url"].endswith("frappe.auth.get_logged_user")


@pytest.mark.parametrize("status", [401, 403])
def test_ping_false_when_credentials_refused(monkeypatch, status):
    monkeypatch.setattr("hub.connectors.erpnext.requests.get",
                        lambda *a, **k: FakeResponse(status))
    assert connector().ping() is False


def test_ping_false_when_server_unreachable(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("hub.connectors.erpnext.requests.get", boom)
    assert connector().ping() is False