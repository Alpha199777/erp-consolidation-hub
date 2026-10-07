"""Tests de l'enrichissement des clients ERPNext par leur adresse (sans réseau)."""
from __future__ import annotations

from urllib.parse import unquote

import pytest
import requests

from hub.connectors.erpnext import ERPNextConnector, choose_address

PREFIXE_DETAIL = "/api/resource/Address/"


class FakeResponse:
    def __init__(self, data, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {"data": self._data}


def adresse(name, city, pincode, *, address_type="Billing",
            lien=("Customer", "X"), principale=0, desactivee=0, societe=0) -> dict:
    return {
        "name": name,
        "address_type": address_type,
        "city": city,
        "pincode": pincode,
        "country": "Switzerland",
        "is_primary_address": principale,
        "disabled": desactivee,
        "is_your_company_address": societe,
        "links": [{"link_doctype": lien[0], "link_name": lien[1]}],
    }


@pytest.fixture
def erp(monkeypatch):
    """ERPNext simulé : 3 clients, 6 adresses (3 vraies + 3 pièges)."""
    clients = [
        {"name": "Grant Plastics Ltd.", "customer_name": "Grant Plastics Ltd.",
         "customer_primary_address": None},
        {"name": "Palmer Productions Ltd.", "customer_name": "Palmer Productions Ltd.",
         "customer_primary_address": None},
        {"name": "West View Software Ltd.", "customer_name": "West View Software Ltd.",
         "customer_primary_address": None},
    ]
    details = {
        a["name"]: a
        for a in [
            adresse("Grant Plastics Ltd.-Facturation", "Zurich", "8001",
                    lien=("Customer", "Grant Plastics Ltd.")),
            adresse("Palmer Productions Ltd-Billing-1", "Genève", "1204", principale=1,
                    lien=("Customer", "Palmer Productions Ltd.")),
            adresse("Palmer Productions Ltd.-Facturation", "Lausanne", "1003",
                    address_type="Shipping", lien=("Customer", "Palmer Productions Ltd.")),
            adresse("Grant Plastics Ltd.-Ancienne", "Bâle", "4001", desactivee=1,
                    lien=("Customer", "Grant Plastics Ltd.")),
            adresse("Hub Demo-Siege", "Berne", "3000", societe=1,
                    lien=("Company", "Hub Demo. (Demo)")),
            adresse("Fournisseur-1", "Lugano", "6900",
                    lien=("Supplier", "Fournisseur SA")),
        ]
    }
    lectures: list[str] = []

    def fake_get(path, **params):
        if path == "/api/resource/Customer":
            return FakeResponse([dict(c) for c in clients])
        if path == "/api/resource/Address":
            # la liste ne contient pas la table enfant 'links'
            return FakeResponse(
                [{k: v for k, v in a.items() if k != "links"} for a in details.values()]
            )
        if path.startswith(PREFIXE_DETAIL):
            nom = unquote(path[len(PREFIXE_DETAIL):])
            lectures.append(nom)
            return FakeResponse(details[nom])
        raise AssertionError(f"appel inattendu : {path}")

    connecteur = ERPNextConnector("http://erp", "cle", "secret")
    monkeypatch.setattr(connecteur, "_get", fake_get)
    return {"connecteur": connecteur, "lectures": lectures}


def _clients_normalises(erp) -> dict:
    connecteur = erp["connecteur"]
    return {c.source_id: c for c in (connecteur.normalize(r) for r in connecteur.fetch_customers())}


# ---------- choose_address ----------

def test_choix_aucune_adresse():
    assert choose_address([]) is None


def test_choix_adresse_unique():
    a = adresse("A", "Zurich", "8001")
    assert choose_address([a]) is a


def test_choix_principale_avant_facturation():
    facturation = adresse("F", "Zurich", "8001")
    principale = adresse("P", "Genève", "1204", address_type="Shipping", principale=1)
    assert choose_address([facturation, principale]) is principale


def test_choix_facturation_si_pas_de_principale():
    livraison = adresse("A", "Lausanne", "1003", address_type="Shipping")
    facturation = adresse("B", "Genève", "1204")
    assert choose_address([livraison, facturation]) is facturation


def test_choix_departage_par_le_nom():
    b = adresse("B", "Lausanne", "1003", address_type="Shipping")
    a = adresse("A", "Genève", "1204", address_type="Shipping")
    assert choose_address([b, a]) is a
    assert choose_address([a, b]) is a


def test_choix_adresse_declaree_sur_le_client():
    principale = adresse("F", "Genève", "1204", principale=1)
    declaree = adresse("C", "Lausanne", "1003", address_type="Shipping")
    assert choose_address([principale, declaree], primary_name="C") is declaree


def test_choix_ignore_desactivees_et_adresse_de_societe():
    desactivee = adresse("D", "Bâle", "4001", principale=1, desactivee=1)
    societe = adresse("S", "Berne", "3000", principale=1, societe=1)
    assert choose_address([desactivee, societe]) is None


# ---------- fetch_customers et normalize ----------

def test_fetch_customers_enrichit_les_clients(erp):
    clients = _clients_normalises(erp)
    grant = clients["Grant Plastics Ltd."]
    palmer = clients["Palmer Productions Ltd."]
    assert (grant.city, grant.postal_code, grant.country) == ("Zurich", "8001", "Switzerland")
    # 2 adresses : la principale (Genève) l'emporte sur la livraison (Lausanne)
    assert (palmer.city, palmer.postal_code, palmer.country) == ("Genève", "1204", "Switzerland")


def test_client_sans_adresse_reste_sans_ville(erp):
    west = _clients_normalises(erp)["West View Software Ltd."]
    assert (west.city, west.postal_code, west.country) == (None, None, None)


def test_adresses_inutiles_non_lues_en_detail(erp):
    clients = _clients_normalises(erp)
    # désactivée et adresse de société : écartées avant la lecture détaillée
    assert sorted(erp["lectures"]) == sorted([
        "Grant Plastics Ltd.-Facturation",
        "Palmer Productions Ltd-Billing-1",
        "Palmer Productions Ltd.-Facturation",
        "Fournisseur-1",
    ])
    # l'adresse du fournisseur (lue) et la désactivée (non lue) ne profitent à personne
    assert {c.city for c in clients.values()} == {"Zurich", "Genève", None}


def test_erreur_adresse_remonte(erp, monkeypatch):
    connecteur = erp["connecteur"]
    original = connecteur._get

    def get_en_panne(path, **params):
        if path.startswith(PREFIXE_DETAIL):
            return FakeResponse({}, status_code=500)
        return original(path, **params)

    monkeypatch.setattr(connecteur, "_get", get_en_panne)
    with pytest.raises(requests.HTTPError):
        connecteur.fetch_customers()


def test_normalize_sans_adresse_reste_compatible():
    connecteur = ERPNextConnector("http://erp", "cle", "secret")
    client = connecteur.normalize({"name": "C1", "customer_name": "C1"})
    assert (client.city, client.postal_code, client.country) == (None, None, None)


def test_normalize_lit_ville_cp_pays():
    connecteur = ERPNextConnector("http://erp", "cle", "secret")
    record = {
        "name": "C1",
        "customer_name": "C1",
        "_address": {"city": "Zurich", "pincode": None, "country": "Switzerland"},
    }
    client = connecteur.normalize(record)
    assert (client.city, client.postal_code, client.country) == ("Zurich", None, "Switzerland")


def test_payload_garde_ladresse_brute(erp):
    connecteur = erp["connecteur"]
    palmer = next(r for r in connecteur.fetch_customers() if r["name"] == "Palmer Productions Ltd.")
    assert palmer["_address"]["name"] == "Palmer Productions Ltd-Billing-1"
    assert connecteur.normalize(palmer).payload is palmer
    assert palmer["_address"]["links"] == [{"link_doctype": "Customer", "link_name": "Palmer Productions Ltd."}]