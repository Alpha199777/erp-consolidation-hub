"""Tests de hub/mcp_server.py, sans base de donnees : la connexion est simulee."""
import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from hub import mcp_server, read_api

EXPECTED_TOOLS = {"list_open_anomalies", "get_anomaly", "find_customer", "invoice_totals_by_currency"}


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(read_api, "connect_reader", lambda: FakeConn())


def test_les_quatre_outils_sont_declares():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    noms = {t.name for t in tools}
    assert noms == EXPECTED_TOOLS
    # chaque outil a une description lisible par Claude
    assert all(t.description and len(t.description) > 20 for t in tools)


def test_aucun_outil_n_ecrit():
    # garde-fou de conception : aucun nom d'outil ne suggere une ecriture
    interdits = ("create", "update", "delete", "insert", "set_", "write", "fix", "accept")
    assert not any(any(m in nom for m in interdits) for nom in EXPECTED_TOOLS)


def test_une_erreur_de_saisie_devient_un_tool_error_avec_son_message(fake_db, monkeypatch):
    def refuse(conn, **kwargs):
        raise ValueError("severity doit etre l'une de ('low', 'medium', 'high')")

    monkeypatch.setattr(read_api, "list_open_anomalies", refuse)
    with pytest.raises(ToolError, match="severity doit etre"):
        mcp_server.list_open_anomalies(severity="critique")


def test_get_anomaly_inconnue(fake_db, monkeypatch):
    monkeypatch.setattr(read_api, "get_anomaly", lambda conn, anomaly_id: None)
    assert mcp_server.get_anomaly(999) == {"found": False, "anomaly_id": 999}


def test_get_anomaly_connue(fake_db, monkeypatch):
    monkeypatch.setattr(read_api, "get_anomaly", lambda conn, anomaly_id: {"anomaly_id": anomaly_id})
    assert mcp_server.get_anomaly(3) == {"found": True, "anomaly": {"anomaly_id": 3}}


def test_find_customer_compte_les_resultats(fake_db, monkeypatch):
    monkeypatch.setattr(read_api, "find_customer", lambda conn, text, limit: [{"name": "A"}, {"name": "B"}])
    assert mcp_server.find_customer("ab") == {"returned": 2, "customers": [{"name": "A"}, {"name": "B"}]}


def test_invoice_totals_est_enveloppe(fake_db, monkeypatch):
    monkeypatch.setattr(read_api, "invoice_totals_by_currency", lambda conn: [{"currency": "CHF"}])
    assert mcp_server.invoice_totals_by_currency() == {"totals": [{"currency": "CHF"}]}