"""Tests de la synchronisation incrementale de load.py (sans base de donnees)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from hub import load

T1 = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
WM = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
MARGE = timedelta(minutes=5)


class FakeConn:
    """Fausse connexion : sait si une transaction est ouverte."""

    def __init__(self) -> None:
        self.in_transaction = False
        self.transactions_opened = 0

    @contextmanager
    def transaction(self):
        self.transactions_opened += 1
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False


class FakeConnector:
    source = "fake"
    overlap = MARGE

    def __init__(self, customers=None, items=None, invoices=None, lines=None,
                 fail_fetch: bool = False) -> None:
        self._customers = customers if customers is not None else [
            {"name": "C1", "m": T1}, {"name": "C2", "m": T2}]
        self._items = items if items is not None else [{"name": "A", "m": T1}]
        self._invoices = invoices if invoices is not None else [
            {"name": "F1", "m": T1}, {"name": "F2", "m": T2}]
        self._lines = lines if lines is not None else [{"name": "L1"}, {"name": "L2"}]
        self._fail_fetch = fail_fetch
        self.calls: list[tuple] = []

    def fetch_customers(self, since=None):
        self.calls.append(("fetch_customers", since))
        if self._fail_fetch:
            raise RuntimeError("panne de lecture")
        return self._customers

    def fetch_items(self, since=None):
        self.calls.append(("fetch_items", since))
        return self._items

    def fetch_invoices(self, since=None):
        self.calls.append(("fetch_invoices", since))
        return self._invoices

    def fetch_invoice_lines(self, invoices=None):
        self.calls.append(("fetch_invoice_lines", invoices))
        return self._lines

    def record_modified_at(self, record):
        return record.get("m")

    def normalize(self, record):
        return ("customer", record)

    def normalize_item(self, record):
        return ("item", record)

    def normalize_invoice(self, record):
        return ("invoice", record)

    def normalize_invoice_line(self, record):
        return ("line", record)


@pytest.fixture
def etat(monkeypatch):
    """Remplace le journal, les upserts et le point de reprise par des enregistreurs."""
    state = {"starts": [], "watermarks": {}, "reads": [], "saves": [], "save_fails": False}

    def fake_start(conn, source, entity):
        state["starts"].append((source, entity))
        return len(state["starts"])

    def fake_get_watermark(conn, source, entity):
        state["reads"].append((source, entity))
        return state["watermarks"].get((source, entity))

    def fake_save_state(conn, source, entity, newest, run_id, full_read):
        assert conn.in_transaction, "le point de reprise doit etre ecrit DANS la transaction"
        if state["save_fails"]:
            raise RuntimeError("echec point de reprise")
        state["saves"].append(
            {"entity": entity, "newest": newest, "run_id": run_id, "full_read": full_read}
        )

    monkeypatch.setattr(load, "start_run", fake_start)
    monkeypatch.setattr(load, "finish_run", lambda *a, **k: None)
    monkeypatch.setattr(load, "get_watermark", fake_get_watermark)
    monkeypatch.setattr(load, "save_state", fake_save_state)
    for nom in ("customers", "items", "invoices", "invoice_lines"):
        monkeypatch.setattr(load, f"upsert_{nom}", lambda conn, objects: len(objects))
    return state


def test_mode_none_ne_touche_pas_au_point_de_reprise(etat):
    connecteur = FakeConnector()
    result = load.sync_source(FakeConn(), connecteur)
    assert result.status == "success" and result.since is None
    assert etat["reads"] == [] and etat["saves"] == []
    assert connecteur.calls == [("fetch_customers", None)]


def test_incremental_sans_point_de_reprise_lit_tout_et_initialise(etat):
    connecteur = FakeConnector()
    result = load.sync_source(FakeConn(), connecteur, "customers", mode="incremental")
    assert result.status == "success" and result.since is None
    assert connecteur.calls == [("fetch_customers", None)]
    assert etat["saves"] == [
        {"entity": "customers", "newest": T2, "run_id": 1, "full_read": True}
    ]


def test_incremental_avec_point_de_reprise_relit_depuis_la_marge(etat):
    etat["watermarks"][("fake", "customers")] = WM
    connecteur = FakeConnector()
    result = load.sync_source(FakeConn(), connecteur, "customers", mode="incremental")
    assert result.since == WM - MARGE
    assert connecteur.calls == [("fetch_customers", WM - MARGE)]
    assert etat["saves"][0]["full_read"] is False
    assert etat["saves"][0]["newest"] == T2


def test_full_ignore_le_point_de_reprise(etat):
    etat["watermarks"][("fake", "customers")] = WM
    connecteur = FakeConnector()
    result = load.sync_source(FakeConn(), connecteur, "customers", mode="full")
    assert result.since is None
    assert etat["reads"] == []
    assert connecteur.calls == [("fetch_customers", None)]
    assert etat["saves"][0]["full_read"] is True


def test_items_incremental(etat):
    etat["watermarks"][("fake", "items")] = WM
    connecteur = FakeConnector()
    load.sync_source(FakeConn(), connecteur, "items", mode="incremental")
    assert connecteur.calls == [("fetch_items", WM - MARGE)]
    assert etat["saves"][0]["entity"] == "items"


def test_invoices_incremental_lignes_des_factures_relues(etat):
    etat["watermarks"][("fake", "invoices")] = WM
    connecteur = FakeConnector()
    inv, lin = load.sync_invoices(FakeConn(), connecteur, mode="incremental")
    assert inv.since == WM - MARGE and lin.since == WM - MARGE
    assert connecteur.calls == [
        ("fetch_invoices", WM - MARGE),
        ("fetch_invoice_lines", [{"name": "F1", "m": T1}, {"name": "F2", "m": T2}]),
    ]
    # une seule entree d'etat pour les factures ET leurs lignes, rattachee au run des factures
    assert etat["saves"] == [
        {"entity": "invoices", "newest": T2, "run_id": 1, "full_read": False}
    ]


def test_point_de_reprise_ecrit_dans_la_meme_transaction(etat):
    conn = FakeConn()
    load.sync_source(conn, FakeConnector(), "customers", mode="incremental")
    assert conn.transactions_opened == 1
    assert len(etat["saves"]) == 1  # le faux save_state verifie in_transaction


def test_echec_de_lecture_nenregistre_pas_le_point(etat):
    result = load.sync_source(
        FakeConn(), FakeConnector(fail_fetch=True), "customers", mode="incremental")
    assert result.status == "failed"
    assert "panne de lecture" in result.error
    assert etat["saves"] == []


def test_echec_du_point_de_reprise_marque_le_run_en_echec(etat):
    etat["save_fails"] = True
    result = load.sync_source(FakeConn(), FakeConnector(), "customers", mode="incremental")
    assert result.status == "failed" and result.rows_loaded == 0
    assert "echec point de reprise" in result.error


def test_dates_absentes_ignorees(etat):
    mixte = FakeConnector(customers=[{"name": "A", "m": None}, {"name": "B", "m": T1}])
    sans_date = FakeConnector(customers=[{"name": "A", "m": None}])
    load.sync_source(FakeConn(), mixte, "customers", mode="incremental")
    load.sync_source(FakeConn(), sans_date, "customers", mode="incremental")
    assert etat["saves"][0]["newest"] == T1
    assert etat["saves"][1]["newest"] is None


def test_aucun_enregistrement_point_inchange(etat):
    etat["watermarks"][("fake", "customers")] = WM
    result = load.sync_source(
        FakeConn(), FakeConnector(customers=[]), "customers", mode="incremental")
    assert result.status == "success" and result.rows_fetched == 0
    # newest vaut None : le SQL GREATEST conserve l'ancien point de reprise
    assert etat["saves"][0]["newest"] is None


def test_mode_inconnu(etat):
    with pytest.raises(ValueError):
        load.sync_source(FakeConn(), FakeConnector(), "customers", mode="bizarre")
    with pytest.raises(ValueError):
        load.sync_invoices(FakeConn(), FakeConnector(), mode="bizarre")
    assert etat["starts"] == []


class RecordingConn:
    """Fausse connexion qui garde les requetes recues (pour les vraies fonctions SQL)."""

    def __init__(self, row=None) -> None:
        self.calls: list[tuple] = []
        self._row = row

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self._row


def test_get_watermark_lit_la_ligne():
    conn = RecordingConn(row=(WM,))
    assert load.get_watermark(conn, "odoo", "customers") == WM
    assert conn.calls[0][1] == ("odoo", "customers")


def test_get_watermark_sans_ligne():
    assert load.get_watermark(RecordingConn(row=None), "odoo", "customers") is None


def test_save_state_ecrit_sans_jamais_reculer():
    conn = RecordingConn()
    load.save_state(conn, "odoo", "customers", T2, 7, full_read=True)
    sql, params = conn.calls[0]
    assert params == ("odoo", "customers", T2, True, 7)
    assert "GREATEST" in sql
    assert "COALESCE" in sql