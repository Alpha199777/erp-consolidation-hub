from hub.models import Customer, clean


def test_false_devient_none():
    assert clean(False) is None


def test_none_reste_none():
    assert clean(None) is None


def test_chaine_vide_devient_none():
    assert clean("") is None


def test_espaces_deviennent_none():
    assert clean("   ") is None


def test_texte_est_nettoye_des_espaces():
    assert clean("  Acme ") == "Acme"


def test_zero_reste_zero():
    assert clean(0) == 0


def test_customer_garde_le_payload_brut():
    raw = {"id": 10, "name": "Acme"}
    c = Customer("odoo", "10", "Acme", None, None, None, None, None, raw)
    assert c.payload is raw
    assert c.source_id == "10"