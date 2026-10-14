"""Tests de hub/read_api.py.

Les tests purs tournent partout. Les tests de base utilisent le compte hub_reader : ils sont
ignores si HUB_READER_PASSWORD est absent. Ils verifient des proprietes (filtres respectes,
limites respectees, coherence entre fonctions), pas des valeurs qui changent avec les donnees.
"""
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from dotenv import load_dotenv

from hub import read_api

load_dotenv()

needs_db = pytest.mark.skipif(
    not os.environ.get("HUB_READER_PASSWORD"), reason="HUB_READER_PASSWORD absent"
)


# ---------- logique pure ----------

def test_clamp_limit_borne_les_valeurs():
    assert read_api.clamp_limit(5) == 5
    assert read_api.clamp_limit(0) == 1
    assert read_api.clamp_limit(-3) == 1
    assert read_api.clamp_limit(10_000) == read_api.MAX_LIMIT


def test_clamp_limit_valeur_invalide_donne_la_valeur_par_defaut():
    assert read_api.clamp_limit(None) == read_api.DEFAULT_LIMIT
    assert read_api.clamp_limit("12") == read_api.DEFAULT_LIMIT
    assert read_api.clamp_limit(True) == read_api.DEFAULT_LIMIT
    assert read_api.clamp_limit(2.5) == read_api.DEFAULT_LIMIT


def test_escape_like_neutralise_les_jokers():
    assert read_api.escape_like("100%") == "100\\%"
    assert read_api.escape_like("a_b") == "a\\_b"
    assert read_api.escape_like("a\\b") == "a\\\\b"
    assert read_api.escape_like("simple") == "simple"


def test_to_jsonable_convertit_les_types_postgres():
    out = read_api.to_jsonable({
        "montant": Decimal("122.2400"),
        "jour": date(2026, 10, 12),
        "instant": datetime(2026, 10, 12, 18, 11, 51, tzinfo=timezone.utc),
        "liste": [Decimal("1.5")],
        "texte": "x",
        "rien": None,
    })
    assert out == {
        "montant": "122.2400",
        "jour": "2026-10-12",
        "instant": "2026-10-12T18:11:51+00:00",
        "liste": ["1.5"],
        "texte": "x",
        "rien": None,
    }


def test_connect_reader_sans_mot_de_passe(monkeypatch):
    monkeypatch.delenv("HUB_READER_PASSWORD", raising=False)
    monkeypatch.setattr(read_api, "load_dotenv", lambda: None)
    with pytest.raises(RuntimeError):
        read_api.connect_reader()


# ---------- base (compte hub_reader) ----------

@pytest.fixture(scope="module")
def conn():
    c = read_api.connect_reader()
    yield c
    c.close()


@needs_db
def test_list_open_anomalies_ne_renvoie_que_des_ouvertes(conn):
    res = read_api.list_open_anomalies(conn, limit=100)
    assert res["returned"] == len(res["anomalies"])
    assert res["returned"] <= res["total"]
    assert all(a["status"] == "open" for a in res["anomalies"])


@needs_db
def test_list_open_anomalies_respecte_la_limite_et_garde_le_total(conn):
    tout = read_api.list_open_anomalies(conn, limit=100)
    un = read_api.list_open_anomalies(conn, limit=1)
    assert un["returned"] <= 1
    assert un["total"] == tout["total"]


@needs_db
def test_list_open_anomalies_filtre_par_regle_et_gravite(conn):
    tout = read_api.list_open_anomalies(conn, limit=100)
    if not tout["anomalies"]:
        pytest.skip("aucune anomalie ouverte")
    regle = tout["anomalies"][0]["rule_code"]
    filtre = read_api.list_open_anomalies(conn, rule_code=regle, limit=100)
    assert filtre["total"] <= tout["total"]
    assert all(a["rule_code"] == regle for a in filtre["anomalies"])
    grave = read_api.list_open_anomalies(conn, severity="high", limit=100)
    assert all(a["severity"] == "high" for a in grave["anomalies"])


@needs_db
def test_list_open_anomalies_trie_les_plus_graves_en_premier(conn):
    rang = {"high": 3, "medium": 2, "low": 1}
    res = read_api.list_open_anomalies(conn, limit=100)
    rangs = [rang[a["severity"]] for a in res["anomalies"]]
    assert rangs == sorted(rangs, reverse=True)


@needs_db
def test_list_open_anomalies_refuse_une_gravite_inconnue(conn):
    with pytest.raises(ValueError):
        read_api.list_open_anomalies(conn, severity="critique")


@needs_db
def test_get_anomaly(conn):
    res = read_api.list_open_anomalies(conn, limit=1)
    if not res["anomalies"]:
        pytest.skip("aucune anomalie ouverte")
    a = res["anomalies"][0]
    detail = read_api.get_anomaly(conn, a["anomaly_id"])
    assert detail["anomaly_id"] == a["anomaly_id"]
    assert detail["rule_code"] == a["rule_code"]
    assert read_api.get_anomaly(conn, -1) is None
    with pytest.raises(ValueError):
        read_api.get_anomaly(conn, "1; DROP TABLE x")


@needs_db
def test_find_customer(conn):
    with pytest.raises(ValueError):
        read_api.find_customer(conn, "a")
    with pytest.raises(ValueError):
        read_api.find_customer(conn, "   ")
    # un jocker n'est pas interprete : "%%" ne doit pas tout renvoyer
    assert read_api.find_customer(conn, "%%%") == []


@needs_db
def test_find_customer_retrouve_un_client_connu(conn):
    # on prend un client existant puis on le recherche par un morceau de son nom
    premier = read_api._fetch(conn, "SELECT name FROM reporting.dim_customer WHERE length(name) >= 4 LIMIT 1")
    if not premier:
        pytest.skip("aucun client")
    nom = premier[0]["name"]
    res = read_api.find_customer(conn, nom[:4].upper())
    assert any(r["name"] == nom for r in res)


@needs_db
def test_invoice_totals_by_currency(conn):
    res = read_api.invoice_totals_by_currency(conn)
    devises = [r["currency"] for r in res]
    assert devises == sorted(devises)
    assert len(devises) == len(set(devises))


@needs_db
def test_le_compte_ne_peut_pas_ecrire(conn):
    import psycopg
    with pytest.raises(psycopg.Error):
        with conn.cursor() as cur:
            cur.execute("UPDATE reporting.anomalies SET status = 'fixed'")
    conn.rollback()