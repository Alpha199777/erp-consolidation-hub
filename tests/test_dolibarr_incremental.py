"""Tests de la lecture incrementale de Dolibarr (sans reseau)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from hub.connectors.dolibarr import DolibarrConnector

SINCE = datetime(2026, 10, 6, 17, 26, 20, tzinfo=timezone.utc)
FILTRE = "(t.tms:>:'2026-10-06 17:26:20')"


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else []

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def fabrique(pages=None, page_size=100):
    """Connecteur dont _get est un faux : une page par appel, puis 404 (page vide)."""
    connecteur = DolibarrConnector("http://x", "cle", page_size=page_size)
    appels: list[dict] = []
    reponses = pages if pages is not None else [[]]

    def faux_get(path, **params):
        appels.append({"path": path, "params": params})
        index = len(appels) - 1
        if index < len(reponses):
            return FakeResponse(200, reponses[index])
        return FakeResponse(404)

    connecteur._get = faux_get
    return connecteur, appels


def test_marge_par_defaut():
    assert DolibarrConnector.overlap == timedelta(days=1)


def test_customers_sans_since_pas_de_filtre():
    connecteur, appels = fabrique([[{"id": "1", "client": "1"}]])
    assert len(connecteur.fetch_customers()) == 1
    assert "sqlfilters" not in appels[0]["params"]


def test_customers_avec_since():
    connecteur, appels = fabrique([[{"id": "1", "client": "1"}]])
    connecteur.fetch_customers(since=SINCE)
    assert appels[0]["path"] == "thirdparties"
    assert appels[0]["params"]["sqlfilters"] == FILTRE


def test_since_avec_fuseau_converti_en_utc():
    connecteur, appels = fabrique()
    deux_heures = timezone(timedelta(hours=2))
    connecteur.fetch_items(since=datetime(2026, 10, 6, 19, 26, 20, tzinfo=deux_heures))
    assert appels[0]["params"]["sqlfilters"] == FILTRE


def test_since_sans_fuseau_lu_comme_utc():
    connecteur, appels = fabrique()
    connecteur.fetch_items(since=datetime(2026, 10, 6, 17, 26, 20))
    assert appels[0]["params"]["sqlfilters"] == FILTRE


def test_filtre_envoye_a_chaque_page():
    pages = [
        [{"id": "1", "client": "1"}, {"id": "2", "client": "1"}],
        [{"id": "3", "client": "1"}],
    ]
    connecteur, appels = fabrique(pages, page_size=2)
    assert len(connecteur.fetch_customers(since=SINCE)) == 3
    assert len(appels) == 2
    assert [a["params"]["page"] for a in appels] == [0, 1]
    assert all(a["params"]["sqlfilters"] == FILTRE for a in appels)


def test_customers_garde_le_filtre_client_avec_since():
    connecteur, _ = fabrique(
        [[{"id": "1", "client": "1"}, {"id": "2", "client": "0"}, {"id": "3", "client": "3"}]]
    )
    assert [c["id"] for c in connecteur.fetch_customers(since=SINCE)] == ["1", "3"]


def test_page_vide_404_avec_since_renvoie_liste_vide():
    connecteur, appels = fabrique(pages=[])
    assert connecteur.fetch_customers(since=SINCE) == []
    assert connecteur.fetch_invoices(since=SINCE) == []
    assert len(appels) == 2


def test_invoices_sans_since_pas_de_filtre():
    connecteur, appels = fabrique([[{"id": "5"}]])
    assert connecteur.fetch_invoices() == [{"id": "5"}]
    assert appels[0]["path"] == "invoices"
    assert "sqlfilters" not in appels[0]["params"]


def test_invoices_avec_since():
    connecteur, appels = fabrique([[{"id": "5"}]])
    connecteur.fetch_invoices(since=SINCE)
    assert appels[0]["path"] == "invoices"
    assert appels[0]["params"]["sqlfilters"] == FILTRE


def test_items_sans_since_pas_de_filtre():
    connecteur, appels = fabrique([[{"id": "8"}]])
    assert connecteur.fetch_items() == [{"id": "8"}]
    assert appels[0]["path"] == "products"
    assert "sqlfilters" not in appels[0]["params"]


def test_items_avec_since():
    connecteur, appels = fabrique([[{"id": "8"}]])
    connecteur.fetch_items(since=SINCE)
    assert appels[0]["path"] == "products"
    assert appels[0]["params"]["sqlfilters"] == FILTRE


def test_lignes_extraites_des_factures_sans_appel_reseau():
    connecteur, appels = fabrique()
    lignes = connecteur.fetch_invoice_lines([{"id": "5", "lines": [{"id": "9"}]}])
    assert lignes == [{"id": "9", "_invoice_id": "5"}]
    assert appels == []


def test_record_modified_at_lit_la_date_unix_en_utc():
    connecteur = DolibarrConnector("http://x", "cle")
    attendu = datetime.fromtimestamp(1780417344, tz=timezone.utc)
    assert connecteur.record_modified_at({"date_modification": "1780417344"}) == attendu


def test_record_modified_at_vide():
    connecteur = DolibarrConnector("http://x", "cle")
    assert connecteur.record_modified_at({"date_modification": None}) is None
    assert connecteur.record_modified_at({}) is None