"""Tests des dates ERPNext : heure du serveur (Europe/Paris par defaut) -> UTC (sans reseau)."""
from __future__ import annotations

from datetime import datetime, timezone

from hub.connectors.erpnext import ERPNextConnector, _parse_server_datetime, _server_text


def connecteur(fuseau=None):
    if fuseau is None:
        return ERPNextConnector("http://x", "k", "s")
    return ERPNextConnector("http://x", "k", "s", server_tz=fuseau)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_fuseau_par_defaut():
    assert str(connecteur().server_tz) == "Europe/Paris"


def test_heure_d_ete():
    assert connecteur().record_modified_at({"modified": "2026-07-01 14:00:00"}) == utc(2026, 7, 1, 12, 0)


def test_heure_d_hiver():
    assert connecteur().record_modified_at({"modified": "2026-12-01 13:00:00"}) == utc(2026, 12, 1, 12, 0)


def test_valeur_reelle_de_sku001():
    # constate : modified = 14:11:21 cote serveur, alors que la synchro l'a lu a 12:11:52 UTC
    record = {"modified": "2026-10-09 14:11:21.503990"}
    assert connecteur().record_modified_at(record) == utc(2026, 10, 9, 12, 11, 21, 503990)


def test_date_deja_avec_fuseau_respectee():
    record = {"modified": "2026-10-09T14:11:21+00:00"}
    assert connecteur().record_modified_at(record) == utc(2026, 10, 9, 14, 11, 21)


def test_aller_retour_entre_instant_et_texte_du_serveur():
    fuseau = connecteur().server_tz
    instant = utc(2026, 11, 3, 9, 15, 30, 250000)
    texte = _server_text(instant, fuseau)
    assert texte == "2026-11-03 10:15:30.250000"
    assert _parse_server_datetime(texte, fuseau) == instant


def test_heure_repetee_du_passage_a_l_heure_d_hiver_lue_comme_heure_d_ete():
    # Le 25 octobre 2026, 02:30 existe deux fois. On choisit la premiere (heure d'ete) :
    # limite connue, erreur d'au plus une heure sur cette seule heure.
    record = {"modified": "2026-10-25 02:30:00"}
    assert connecteur().record_modified_at(record) == utc(2026, 10, 25, 0, 30)


def test_fuseau_configurable():
    record = {"modified": "2026-07-01 14:00:00"}
    assert connecteur("UTC").record_modified_at(record) == utc(2026, 7, 1, 14, 0)


def test_from_env_lit_le_fuseau_optionnel(monkeypatch):
    monkeypatch.setenv("ERPNEXT_URL", "http://x")
    monkeypatch.setenv("ERPNEXT_API_KEY", "k")
    monkeypatch.setenv("ERPNEXT_API_SECRET", "s")
    monkeypatch.setenv("ERPNEXT_TIMEZONE", "UTC")
    assert str(ERPNextConnector.from_env().server_tz) == "UTC"


def test_from_env_sans_variable_de_fuseau(monkeypatch):
    monkeypatch.setenv("ERPNEXT_URL", "http://x")
    monkeypatch.setenv("ERPNEXT_API_KEY", "k")
    monkeypatch.setenv("ERPNEXT_API_SECRET", "s")
    monkeypatch.delenv("ERPNEXT_TIMEZONE", raising=False)
    assert str(ERPNextConnector.from_env().server_tz) == "Europe/Paris"


def test_normalize_item_en_utc():
    item = connecteur().normalize_item({"name": "SKU001", "modified": "2026-10-09 14:11:21.503990"})
    assert item.source_modified_at == utc(2026, 10, 9, 12, 11, 21, 503990)


def test_normalize_invoice_en_utc():
    invoice = connecteur().normalize_invoice({"name": "F1", "modified": "2026-07-01 14:00:00"})
    assert invoice.source_modified_at == utc(2026, 7, 1, 12, 0)


def test_ligne_repli_sur_la_date_de_la_facture():
    ligne = connecteur().normalize_invoice_line(
        {"name": "L1", "_invoice_id": "F1", "_invoice_modified": "2026-12-01 13:00:00"}
    )
    source_modified_at = ligne.source_modified_at
    assert source_modified_at == utc(2026, 12, 1, 12, 0)