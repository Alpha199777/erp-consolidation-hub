from hub.connectors.odoo import ENV_KEYS, OdooConnector

ACME = {
    "id": 10,
    "name": "Acme Corporation",
    "email": "acme_corp@yourcompany.example.com",
    "phone": "(603)-996-3829",
    "city": "Pleasant Hill",
    "zip": "94523",
    "country_id": [233, "United States"],
    "write_date": "2026-09-30 10:44:31",
}


def make():
    return OdooConnector("http://localhost:8069", "erp_demo", "admin", "admin")


def test_normalize_client_complet():
    c = make().normalize(ACME)
    assert c.source == "odoo"
    assert c.source_id == "10"
    assert c.name == "Acme Corporation"
    assert c.postal_code == "94523"
    assert c.country == "United States"
    assert c.payload == ACME


def test_normalize_valeurs_vides_odoo():
    record = {"id": 99, "name": "Sans contact", "email": False, "phone": False,
              "city": False, "zip": False, "country_id": False}
    c = make().normalize(record)
    assert c.email is None
    assert c.phone is None
    assert c.city is None
    assert c.postal_code is None
    assert c.country is None


def test_from_env_sans_variables_est_ignore(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert OdooConnector.from_env() is None


def test_from_env_avec_variables(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.setenv(key, "x")
    assert OdooConnector.from_env() is not None


def test_ping_false_si_serveur_injoignable():
    assert OdooConnector("http://localhost:1", "x", "x", "x").ping() is False