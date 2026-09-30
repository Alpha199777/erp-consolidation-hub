import pytest
import requests

from hub.connectors.dolibarr import DolibarrConnector


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else []

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def rec(id_, client, **kw):
    base = {"id": str(id_), "name": f"Tiers {id_}", "client": client, "status": "1",
            "email": None, "phone": None, "town": None, "zip": None,
            "country_code": None}
    base.update(kw)
    return base


def make_fake_get(records):
    """Simule l'API : découpe `records` en pages, 404 quand la page est vide."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params})
        page, limit = params.get("page", 0), params["limit"]
        chunk = records[page * limit:(page + 1) * limit]
        if not chunk:
            return FakeResponse(404, {"error": "No thirdparties found"})
        return FakeResponse(200, chunk)

    return fake_get, calls


def connector(page_size=100):
    return DolibarrConnector("http://x", "secret", page_size=page_size)


# --- from_env -----------------------------------------------------------

def test_from_env_returns_none_when_variables_missing(monkeypatch):
    monkeypatch.delenv("DOLIBARR_URL", raising=False)
    monkeypatch.delenv("DOLIBARR_API_KEY", raising=False)
    assert DolibarrConnector.from_env() is None
    monkeypatch.setenv("DOLIBARR_URL", "http://x")
    assert DolibarrConnector.from_env() is None


def test_from_env_builds_connector(monkeypatch):
    monkeypatch.setenv("DOLIBARR_URL", "http://x/")
    monkeypatch.setenv("DOLIBARR_API_KEY", "k")
    c = DolibarrConnector.from_env()
    assert c.api_key == "k"
    assert c.base == "http://x/api/index.php"


# --- normalize ----------------------------------------------------------

def test_normalize_maps_fields():
    c = connector().normalize(
        rec(7, "1", name="Teclib", email="a@b.fr", phone="0102",
            town="Paris", zip="75001", country_code="FR"))
    assert c.source == "dolibarr"
    assert c.source_id == "7"
    assert c.name == "Teclib"
    assert c.email == "a@b.fr"
    assert c.city == "Paris"
    assert c.postal_code == "75001"
    assert c.country == "FR"


def test_normalize_empty_values_become_none():
    c = connector().normalize(rec(1, "1", email="", phone="  ", town=None, zip=""))
    assert c.email is None
    assert c.phone is None
    assert c.city is None
    assert c.postal_code is None


def test_normalize_keeps_raw_payload():
    record = rec(3, "3", address="1 rue X", phone_mobile="06")
    assert connector().normalize(record).payload == record


# --- fetch_customers ----------------------------------------------------

def test_fetch_keeps_only_customers(monkeypatch):
    records = [rec(1, "1"), rec(2, "3"), rec(3, "0"), rec(4, "2")]
    fake, _ = make_fake_get(records)
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    assert [r["id"] for r in connector().fetch_customers()] == ["1", "2"]


def test_fetch_keeps_closed_customers(monkeypatch):
    fake, _ = make_fake_get([rec(1, "1", status="0")])
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    assert len(connector().fetch_customers()) == 1


def test_fetch_paginates_with_partial_last_page(monkeypatch):
    fake, calls = make_fake_get([rec(i, "1") for i in range(5)])
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    assert len(connector(page_size=2).fetch_customers()) == 5
    assert len(calls) == 3


def test_fetch_paginates_until_404(monkeypatch):
    fake, calls = make_fake_get([rec(i, "1") for i in range(4)])
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    assert len(connector(page_size=2).fetch_customers()) == 4
    assert len(calls) == 3  # la 3e page renvoie 404


def test_fetch_empty_returns_empty_list(monkeypatch):
    fake, _ = make_fake_get([])
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    assert connector().fetch_customers() == []


def test_fetch_sends_api_key_header(monkeypatch):
    fake, calls = make_fake_get([rec(1, "1")])
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", fake)
    connector().fetch_customers()
    assert calls[0]["headers"]["DOLAPIKEY"] == "secret"


def test_fetch_raises_on_unauthorized(monkeypatch):
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get",
                        lambda *a, **k: FakeResponse(401))
    with pytest.raises(requests.HTTPError):
        connector().fetch_customers()


# --- ping ---------------------------------------------------------------

def test_ping_true_on_200(monkeypatch):
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get",
                        lambda *a, **k: FakeResponse(200))
    assert connector().ping() is True


def test_ping_false_on_401(monkeypatch):
    monkeypatch.setattr("hub.connectors.dolibarr.requests.get",
                        lambda *a, **k: FakeResponse(401))
    assert connector().ping() is False


def test_ping_false_when_server_unreachable(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("hub.connectors.dolibarr.requests.get", boom)
    assert connector().ping() is False