"""Tests de la lecture incrementale d'Odoo (sans reseau)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hub.connectors.odoo import MOVE_TYPES, OdooConnector

SINCE = datetime(2026, 10, 6, 17, 26, 20, tzinfo=timezone.utc)
SINCE_TEXTE = "2026-10-06 17:26:20"
CLAUSE_SINCE = ["write_date", ">=", SINCE_TEXTE]


def fabrique():
    """Connecteur dont _call est un faux qui enregistre les appels."""
    connecteur = OdooConnector("http://x", "db", "u", "p")
    appels: list[dict] = []

    def faux_call(modele, methode, *args, **kwargs):
        appels.append({"modele": modele, "args": args, "kwargs": kwargs})
        if modele == "res.company":
            return [{"partner_id": [1, "Ma societe"]}]
        return []

    connecteur._call = faux_call
    return connecteur, appels


def domaine(appels, modele):
    """Domaine du dernier appel sur ce modele."""
    return [a for a in appels if a["modele"] == modele][-1]["args"][0]


def test_marge_par_defaut():
    assert OdooConnector.overlap == timedelta(minutes=5)


def test_customers_sans_since_inchange():
    connecteur, appels = fabrique()
    connecteur.fetch_customers()
    assert domaine(appels, "res.partner") == [
        ["is_company", "=", True], ["id", "not in", [1]],
    ]


def test_customers_avec_since():
    connecteur, appels = fabrique()
    connecteur.fetch_customers(since=SINCE)
    assert domaine(appels, "res.partner") == [
        ["is_company", "=", True], ["id", "not in", [1]], CLAUSE_SINCE,
    ]


def test_since_avec_fuseau_converti_en_utc():
    connecteur, appels = fabrique()
    deux_heures = timezone(timedelta(hours=2))
    connecteur.fetch_items(since=datetime(2026, 10, 6, 19, 26, 20, tzinfo=deux_heures))
    assert domaine(appels, "product.product") == [CLAUSE_SINCE]


def test_invoices_sans_since_inchange():
    connecteur, appels = fabrique()
    connecteur.fetch_invoices()
    assert domaine(appels, "account.move") == [["move_type", "in", MOVE_TYPES]]


def test_invoices_avec_since():
    connecteur, appels = fabrique()
    connecteur.fetch_invoices(since=SINCE)
    assert domaine(appels, "account.move") == [["move_type", "in", MOVE_TYPES], CLAUSE_SINCE]


def test_items_sans_since_inchange():
    connecteur, appels = fabrique()
    connecteur.fetch_items()
    assert domaine(appels, "product.product") == []


def test_items_avec_since():
    connecteur, appels = fabrique()
    connecteur.fetch_items(since=SINCE)
    assert domaine(appels, "product.product") == [CLAUSE_SINCE]


def test_lignes_sans_liste_lit_toutes_les_lignes():
    connecteur, appels = fabrique()
    connecteur.fetch_invoice_lines()
    assert domaine(appels, "account.move.line") == [
        ["move_id.move_type", "in", MOVE_TYPES], ["display_type", "=", "product"],
    ]


def test_lignes_limitees_aux_factures_donnees():
    connecteur, appels = fabrique()
    connecteur.fetch_invoice_lines([{"id": 4}, {"id": 7}])
    assert domaine(appels, "account.move.line") == [
        ["move_id.move_type", "in", MOVE_TYPES],
        ["display_type", "=", "product"],
        ["move_id", "in", [4, 7]],
    ]


def test_lignes_liste_vide_aucun_appel():
    connecteur, appels = fabrique()
    assert connecteur.fetch_invoice_lines([]) == []
    assert appels == []


def test_record_modified_at_lit_write_date_en_utc():
    connecteur = OdooConnector("http://x", "db", "u", "p")
    assert connecteur.record_modified_at({"write_date": "2026-10-06 17:26:20"}) == SINCE


def test_record_modified_at_vide():
    assert OdooConnector("http://x", "db", "u", "p").record_modified_at({"write_date": False}) is None