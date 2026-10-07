"""Tests de la logique de chargement du Sprint 2 (sans base de données)."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from hub import load


class FakeConn:
    """Fausse connexion : compte les transactions ouvertes."""

    def __init__(self) -> None:
        self.transactions_opened = 0

    @contextmanager
    def transaction(self):
        self.transactions_opened += 1
        yield


class FakeConnector:
    source = "fake"

    def __init__(self, invoices=None, lines=None, items=None, customers=None,
                 fail_on: str | None = None) -> None:
        self._invoices = invoices if invoices is not None else [{"name": "F1"}, {"name": "F2"}]
        self._lines = lines if lines is not None else [{"name": "L1"}, {"name": "L2"}, {"name": "L3"}]
        self._items = items if items is not None else [{"name": "A"}]
        self._customers = customers if customers is not None else [{"name": "C"}]
        self._fail_on = fail_on
        self.lines_called_with = None

    def _maybe_fail(self, what: str) -> None:
        if self._fail_on == what:
            raise RuntimeError(f"panne {what}")

    def fetch_invoices(self):
        self._maybe_fail("fetch_invoices")
        return self._invoices

    def fetch_invoice_lines(self, invoices=None):
        self.lines_called_with = invoices
        self._maybe_fail("fetch_invoice_lines")
        return self._lines

    def fetch_items(self):
        self._maybe_fail("fetch_items")
        return self._items

    def fetch_customers(self):
        return self._customers

    def normalize(self, record):
        return ("customer", record)

    def normalize_invoice(self, record):
        return ("invoice", record)

    def normalize_invoice_line(self, record):
        return ("line", record)

    def normalize_item(self, record):
        return ("item", record)


@pytest.fixture
def journal(monkeypatch):
    """Remplace le journal et les upserts par des enregistreurs."""
    state = {"starts": [], "finishes": [], "upserts": []}

    def fake_start(conn, source, entity):
        state["starts"].append((source, entity))
        return len(state["starts"])

    def fake_finish(conn, run_id, status, fetched, loaded, error=None):
        state["finishes"].append((run_id, status, fetched, loaded, error))

    def make_upsert(name, fail=False):
        def _upsert(conn, objects):
            if fail:
                raise RuntimeError(f"echec {name}")
            state["upserts"].append((name, len(objects)))
            return len(objects)
        return _upsert

    state["make_upsert"] = make_upsert
    monkeypatch.setattr(load, "start_run", fake_start)
    monkeypatch.setattr(load, "finish_run", fake_finish)
    monkeypatch.setattr(load, "upsert_customers", make_upsert("customers"))
    monkeypatch.setattr(load, "upsert_items", make_upsert("items"))
    monkeypatch.setattr(load, "upsert_invoices", make_upsert("invoices"))
    monkeypatch.setattr(load, "upsert_invoice_lines", make_upsert("invoice_lines"))
    return state


def test_customers_reste_compatible_sprint1(journal):
    result = load.sync_source(FakeConn(), FakeConnector())
    assert result.status == "success"
    assert (result.rows_fetched, result.rows_loaded) == (1, 1)
    assert journal["starts"] == [("fake", "customers")]


def test_items(journal):
    result = load.sync_source(FakeConn(), FakeConnector(), "items")
    assert result.status == "success"
    assert journal["upserts"] == [("items", 1)]
    assert journal["starts"] == [("fake", "items")]


def test_invoices_charge_factures_et_lignes_dans_une_transaction(journal):
    conn = FakeConn()
    connector = FakeConnector()
    inv, lin = load.sync_invoices(conn, connector)

    assert conn.transactions_opened == 1
    assert journal["starts"] == [("fake", "invoices"), ("fake", "invoice_lines")]
    assert journal["upserts"] == [("invoices", 2), ("invoice_lines", 3)]
    assert (inv.status, inv.rows_fetched, inv.rows_loaded) == ("success", 2, 2)
    assert (lin.status, lin.rows_fetched, lin.rows_loaded) == ("success", 3, 3)
    # fetch_invoice_lines doit recevoir la LISTE des factures
    assert connector.lines_called_with == [{"name": "F1"}, {"name": "F2"}]


def test_sync_source_invoices_renvoie_le_resultat_des_factures(journal):
    result = load.sync_source(FakeConn(), FakeConnector(), "invoices")
    assert result.rows_fetched == 2


def test_echec_de_lecture_est_trace_sans_exception(journal):
    inv, lin = load.sync_invoices(FakeConn(), FakeConnector(fail_on="fetch_invoices"))
    assert inv.status == "failed" and lin.status == "failed"
    assert "panne fetch_invoices" in inv.error
    assert journal["upserts"] == []
    assert [f[1] for f in journal["finishes"]] == ["failed", "failed"]


def test_echec_de_chargement_des_lignes_marque_les_deux_runs_en_echec(journal, monkeypatch):
    monkeypatch.setattr(load, "upsert_invoice_lines", journal["make_upsert"]("invoice_lines", fail=True))
    inv, lin = load.sync_invoices(FakeConn(), FakeConnector())
    assert inv.status == "failed" and lin.status == "failed"
    assert inv.rows_loaded == 0 and lin.rows_loaded == 0
    # les volumes lus restent tracés malgré l'échec
    assert (inv.rows_fetched, lin.rows_fetched) == (2, 3)


def test_entite_inconnue(journal):
    with pytest.raises(ValueError):
        load.sync_source(FakeConn(), FakeConnector(), "pizzas")
    assert journal["starts"] == []


def test_start_run_existe():
    assert load.start_run.__name__ == "start_run"