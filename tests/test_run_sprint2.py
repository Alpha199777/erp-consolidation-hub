"""Tests du point d'entrée du Sprint 2 (sans base de données ni ERP)."""
from __future__ import annotations

import pytest

from hub import load, run_sprint2


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, source: str) -> None:
        self.source = source


def _result(source: str, echec: bool) -> load.SyncResult:
    if echec:
        return load.SyncResult(source, 1, "failed", 2, 0, "panne")
    return load.SyncResult(source, 1, "success", 2, 2)


@pytest.fixture
def etat(monkeypatch):
    """Remplace connect() et les synchronisations par des enregistreurs."""
    state = {"appels": [], "modes": [], "echecs": set(), "conn": FakeConn()}

    monkeypatch.setattr(load, "connect", lambda: state["conn"])

    def fake_sync_source(conn, connector, entity="customers", mode="none"):
        state["appels"].append((connector.source, entity))
        state["modes"].append(mode)
        return _result(connector.source, (connector.source, entity) in state["echecs"])

    def fake_sync_invoices(conn, connector, mode="none"):
        state["appels"].append((connector.source, "invoices"))
        state["modes"].append(mode)
        echec = (connector.source, "invoices") in state["echecs"]
        return (_result(connector.source, echec), _result(connector.source, echec))

    monkeypatch.setattr(load, "sync_source", fake_sync_source)
    monkeypatch.setattr(load, "sync_invoices", fake_sync_invoices)
    return state


def test_ordre_des_entites_et_des_erp(etat):
    code = run_sprint2.run_sync([FakeConnector("odoo"), FakeConnector("dolibarr")])
    assert code == 0
    assert etat["appels"] == [
        ("odoo", "customers"), ("odoo", "items"), ("odoo", "invoices"),
        ("dolibarr", "customers"), ("dolibarr", "items"), ("dolibarr", "invoices"),
    ]
    assert etat["conn"].closed is True


def test_un_echec_nempeche_pas_les_autres_entites(etat):
    etat["echecs"].add(("odoo", "items"))
    code = run_sprint2.run_sync([FakeConnector("odoo"), FakeConnector("erpnext")])
    assert code == 1
    assert len(etat["appels"]) == 6  # tout a quand meme ete tente


def test_connexion_fermee_meme_en_cas_derreur_inattendue(etat, monkeypatch):
    def boom(conn, connector, entity="customers", mode="none"):
        raise RuntimeError("erreur inattendue")

    monkeypatch.setattr(load, "sync_source", boom)
    with pytest.raises(RuntimeError):
        run_sprint2.run_sync([FakeConnector("odoo")])
    assert etat["conn"].closed is True


def test_main_sans_connecteur_renvoie_1(monkeypatch):
    monkeypatch.setattr(run_sprint2, "load_dotenv", lambda: None)
    monkeypatch.setattr(run_sprint2, "build_connectors", lambda: ([], ["odoo"]))
    assert run_sprint2.main([]) == 1


def test_check_only_necrit_rien(monkeypatch):
    monkeypatch.setattr(run_sprint2, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        run_sprint2, "build_connectors", lambda: ([FakeConnector("odoo")], [])
    )
    monkeypatch.setattr(run_sprint2, "check_only", lambda connectors: 0)

    def interdit():
        raise AssertionError("connect() ne doit pas etre appele avec --check-only")

    monkeypatch.setattr(load, "connect", interdit)
    assert run_sprint2.main(["--check-only"]) == 0


def test_mode_transmis_a_toutes_les_synchronisations(etat):
    run_sprint2.run_sync([FakeConnector("odoo")], mode="full")
    assert etat["modes"] == ["full", "full", "full"]


@pytest.mark.parametrize(
    "argv, mode_attendu",
    [([], "incremental"), (["--full"], "full")],
)
def test_main_choisit_le_mode(monkeypatch, argv, mode_attendu):
    vus = []
    monkeypatch.setattr(run_sprint2, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        run_sprint2, "build_connectors", lambda: ([FakeConnector("odoo")], [])
    )
    monkeypatch.setattr(run_sprint2, "run_sync", lambda connectors, mode: vus.append(mode) or 0)
    assert run_sprint2.main(argv) == 0
    assert vus == [mode_attendu]


def test_entites_du_sprint2():
    assert run_sprint2.ENTITIES == ("customers", "items", "invoices")