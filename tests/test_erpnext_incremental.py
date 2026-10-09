"""Tests de la lecture incrementale d'ERPNext (sans reseau)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import requests

from hub.connectors.erpnext import ERPNextConnector

SINCE = datetime(2026, 10, 6, 17, 26, 20, tzinfo=timezone.utc)
SINCE_TEXTE = "2026-10-06 17:26:20.000000"
FILTRE = json.dumps([["modified", ">=", SINCE_TEXTE]])

AVANT = "2026-09-30 10:00:00.000000"
APRES = "2026-10-06 18:00:00.000000"
APRES_ADRESSE = "2026-10-07 09:00:00.000000"


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return {"data": self._data}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def client(nom, modified):
    return {"name": nom, "customer_name": nom, "modified": modified,
            "customer_primary_address": None}


def adresse(nom, nom_client, modified):
    return {
        "name": nom, "modified": modified, "disabled": 0, "is_your_company_address": 0,
        "address_type": "Billing", "is_primary_address": 0,
        "city": "Zurich", "pincode": "8001", "country": "Switzerland",
        "links": [{"link_doctype": "Customer", "link_name": nom_client}],
    }


def fabrique(clients, adresses=()):
    """Connecteur dont _get simule ERPNext, filtre serveur `modified >=` compris."""
    connecteur = ERPNextConnector("http://x", "cle", "secret")
    par_nom = {c["name"]: c for c in clients}
    details = {a["name"]: a for a in adresses}
    appels: list[dict] = []

    def faux_get(path, **params):
        appels.append({"path": path, "params": params})
        if path.startswith("/api/resource/Address/"):
            nom = unquote(path[len("/api/resource/Address/"):])
            return FakeResponse(200, details[nom])
        if path.startswith("/api/resource/Customer/"):
            nom = unquote(path[len("/api/resource/Customer/"):])
            if nom in par_nom:
                return FakeResponse(200, dict(par_nom[nom]))
            return FakeResponse(404)
        if path == "/api/resource/Address":
            return FakeResponse(
                200, [{k: v for k, v in a.items() if k != "links"} for a in details.values()]
            )
        if path == "/api/resource/Customer":
            donnees = clients
            if "filters" in params:
                ((_, _, seuil),) = json.loads(params["filters"])
                donnees = [c for c in clients if c["modified"] >= seuil]
            return FakeResponse(200, [dict(c) for c in donnees])
        return FakeResponse(200, [])

    connecteur._get = faux_get
    return connecteur, appels


def appels_vers(appels, chemin):
    return [a for a in appels if a["path"] == chemin]


def noms(records):
    return [r["name"] for r in records]


def test_marge_par_defaut():
    assert ERPNextConnector.overlap == timedelta(minutes=5)


def test_sans_since_aucun_filtre_et_aucun_detail_client():
    connecteur, appels = fabrique([client("C1", AVANT)], [adresse("A1", "C1", AVANT)])
    assert noms(connecteur.fetch_customers()) == ["C1"]
    assert all("filters" not in a["params"] for a in appels_vers(appels, "/api/resource/Customer"))
    assert not any(a["path"].startswith("/api/resource/Customer/") for a in appels)


def test_since_envoie_le_filtre_modified():
    connecteur, appels = fabrique([client("C1", APRES)])
    connecteur.fetch_customers(since=SINCE)
    assert appels_vers(appels, "/api/resource/Customer")[0]["params"]["filters"] == FILTRE


def test_since_avec_fuseau_converti_en_utc():
    connecteur, appels = fabrique([])
    deux_heures = timezone(timedelta(hours=2))
    connecteur.fetch_items(since=datetime(2026, 10, 6, 19, 26, 20, tzinfo=deux_heures))
    assert appels_vers(appels, "/api/resource/Item")[0]["params"]["filters"] == FILTRE


def test_invoices_since():
    connecteur, appels = fabrique([])
    connecteur.fetch_invoices(since=SINCE)
    assert appels_vers(appels, "/api/resource/Sales%20Invoice")[0]["params"]["filters"] == FILTRE


def test_items_since():
    connecteur, appels = fabrique([])
    connecteur.fetch_items(since=SINCE)
    assert appels_vers(appels, "/api/resource/Item")[0]["params"]["filters"] == FILTRE


def test_clients_modifies_et_clients_dont_ladresse_a_change():
    clients = [client("C1", APRES), client("C2", AVANT), client("C3", AVANT)]
    adresses = [
        adresse("A1", "C1", AVANT),
        adresse("A2", "C2", APRES_ADRESSE),   # seule l'adresse a change
        adresse("A3", "C3", AVANT),
    ]
    connecteur, appels = fabrique(clients, adresses)
    records = connecteur.fetch_customers(since=SINCE)
    assert noms(records) == ["C1", "C2"]
    chemins = [a["path"] for a in appels]
    assert "/api/resource/Customer/C2" in chemins     # relu par un appel detaille
    assert "/api/resource/Customer/C1" not in chemins  # deja dans la liste
    assert "/api/resource/Customer/C3" not in chemins  # rien n'a change


def test_client_modifie_et_adresse_recente_pas_en_double():
    connecteur, _ = fabrique([client("C1", APRES)], [adresse("A1", "C1", APRES_ADRESSE)])
    assert noms(connecteur.fetch_customers(since=SINCE)) == ["C1"]


def test_modified_max_quand_ladresse_est_plus_recente():
    connecteur, _ = fabrique([client("C2", AVANT)], [adresse("A2", "C2", APRES_ADRESSE)])
    (record,) = connecteur.fetch_customers(since=SINCE)
    assert record["_modified_max"] == APRES_ADRESSE
    assert record["_address"]["city"] == "Zurich"


def test_pas_de_modified_max_quand_le_client_est_plus_recent():
    connecteur, _ = fabrique([client("C1", APRES)], [adresse("A1", "C1", AVANT)])
    (record,) = connecteur.fetch_customers(since=SINCE)
    assert "_modified_max" not in record


def test_adresse_liee_a_un_client_introuvable_est_ignoree():
    connecteur, _ = fabrique([client("C1", AVANT)], [adresse("A9", "C9", APRES_ADRESSE)])
    assert connecteur.fetch_customers(since=SINCE) == []


def test_record_modified_at_lit_modified_en_utc():
    connecteur = ERPNextConnector("http://x", "k", "s")
    assert connecteur.record_modified_at({"modified": "2026-10-06 17:26:20"}) == SINCE


def test_record_modified_at_prefere_modified_max():
    connecteur = ERPNextConnector("http://x", "k", "s")
    record = {"modified": AVANT, "_modified_max": APRES_ADRESSE}
    assert connecteur.record_modified_at(record) == datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def test_record_modified_at_sans_modified_max_lit_modified():
    connecteur = ERPNextConnector("http://x", "k", "s")
    assert connecteur.record_modified_at({"modified": AVANT}) == datetime(
        2026, 9, 30, 10, 0, tzinfo=timezone.utc
    )


def test_record_modified_at_vide():
    assert ERPNextConnector("http://x", "k", "s").record_modified_at({"modified": None}) is None