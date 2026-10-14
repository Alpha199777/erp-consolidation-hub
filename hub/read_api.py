"""Acces en lecture seule aux donnees du hub, pour le serveur MCP (Sprint 6).

Toutes les fonctions lisent uniquement le schema `reporting`, avec le compte `hub_reader`
(lecture seule cote PostgreSQL). Elles renvoient des structures simples (dict, list, str,
int) que le serveur MCP peut serialiser en JSON tel quel.

Les textes renvoyes (noms de clients, messages d'anomalie) viennent des ERP : ce sont des
donnees, pas des instructions.
"""
import os
from datetime import date, datetime
from decimal import Decimal

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MIN_SEARCH_LENGTH = 2
SEVERITIES = ("low", "medium", "high")


def clamp_limit(limit) -> int:
    """Ramene une limite demandee dans [1, MAX_LIMIT] ; DEFAULT_LIMIT si absente ou invalide."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def escape_like(text: str) -> str:
    """Neutralise % et _ pour que la recherche traite le texte comme du texte."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_jsonable(value):
    """Convertit les types PostgreSQL non JSON : Decimal -> str, dates -> ISO 8601."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def connect_reader() -> psycopg.Connection:
    """Connexion avec le compte hub_reader. Le mot de passe vient de .env (HUB_READER_PASSWORD)."""
    load_dotenv()
    password = os.environ.get("HUB_READER_PASSWORD")
    if not password:
        raise RuntimeError("HUB_READER_PASSWORD absent de .env")
    return psycopg.connect(
        host=os.environ.get("HUB_READER_HOST", "localhost"),
        port=int(os.environ.get("HUB_READER_PORT", "5433")),
        dbname=os.environ.get("HUB_READER_DB", "hub"),
        user="hub_reader",
        password=password,
        connect_timeout=5,
        row_factory=dict_row,
    )


def _fetch(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.rollback()  # lecture seule : on ne garde jamais de transaction ouverte
    return [to_jsonable(dict(r)) for r in rows]


def list_open_anomalies(conn, rule_code: str | None = None, severity: str | None = None,
                        limit=DEFAULT_LIMIT) -> dict:
    """Anomalies au statut `open`, les plus graves d'abord.

    Renvoie {"total": nombre d'anomalies ouvertes correspondant aux filtres,
             "returned": nombre renvoye, "anomalies": [...]}.
    """
    if severity is not None and severity not in SEVERITIES:
        raise ValueError(f"severity doit etre l'une de {SEVERITIES}")
    where = ["status = 'open'"]
    params: list = []
    if rule_code:
        where.append("rule_code = %s")
        params.append(rule_code)
    if severity:
        where.append("severity = %s")
        params.append(severity)
    clause = " AND ".join(where)
    total = _fetch(conn, f"SELECT count(*) AS n FROM reporting.anomalies WHERE {clause}", tuple(params))[0]["n"]
    rows = _fetch(
        conn,
        "SELECT anomaly_id, rule_code, entity_type, entity_key, severity, message, status, "
        "first_detected_at, last_detected_at "
        f"FROM reporting.anomalies WHERE {clause} "
        "ORDER BY severity_rank DESC, last_detected_at DESC, anomaly_id "
        "LIMIT %s",
        tuple(params) + (clamp_limit(limit),),
    )
    return {"total": total, "returned": len(rows), "anomalies": rows}


def get_anomaly(conn, anomaly_id: int) -> dict | None:
    """Une anomalie (tous statuts) ou None si elle n'existe pas."""
    if isinstance(anomaly_id, bool) or not isinstance(anomaly_id, int):
        raise ValueError("anomaly_id doit etre un entier")
    rows = _fetch(conn, "SELECT * FROM reporting.anomalies WHERE anomaly_id = %s", (anomaly_id,))
    return rows[0] if rows else None


def find_customer(conn, text: str, limit=DEFAULT_LIMIT) -> list[dict]:
    """Clients unifies dont le nom ou l'e-mail contient `text` (sans tenir compte de la casse)."""
    text = (text or "").strip()
    if len(text) < MIN_SEARCH_LENGTH:
        raise ValueError(f"la recherche doit faire au moins {MIN_SEARCH_LENGTH} caracteres")
    pattern = f"%{escape_like(text)}%"
    return _fetch(
        conn,
        "SELECT customer_id, name, email, postal_code, city, country_code, erp_count, erp_list "
        "FROM reporting.dim_customer "
        "WHERE name ILIKE %s OR email ILIKE %s "
        "ORDER BY name, customer_id LIMIT %s",
        (pattern, pattern, clamp_limit(limit)),
    )


def invoice_totals_by_currency(conn) -> list[dict]:
    """Chiffre d'affaires net HT par devise (avoirs en negatif), tous statuts confondus.

    Aucune conversion de devise : ne jamais additionner deux devises.
    """
    return _fetch(
        conn,
        "SELECT currency, "
        "count(*) FILTER (WHERE doc_type <> 'credit_note') AS invoices, "
        "count(*) FILTER (WHERE doc_type = 'credit_note') AS credit_notes, "
        "sum(signed_total_excl_tax) AS net_total_excl_tax "
        "FROM reporting.fact_invoice GROUP BY currency ORDER BY currency",
    )