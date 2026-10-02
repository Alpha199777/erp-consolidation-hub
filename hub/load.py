"""Chargement dans PostgreSQL : upsert idempotent + journal des synchronisations."""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from hub.models import Customer

UPSERT_CUSTOMER = """
INSERT INTO raw.customers
    (source, source_id, name, email, phone, city, postal_code, country,
     payload, first_seen_at, last_synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
ON CONFLICT (source, source_id) DO UPDATE SET
    name = EXCLUDED.name,
    email = EXCLUDED.email,
    phone = EXCLUDED.phone,
    city = EXCLUDED.city,
    postal_code = EXCLUDED.postal_code,
    country = EXCLUDED.country,
    payload = EXCLUDED.payload,
    last_synced_at = now()
"""


@dataclass
class SyncResult:
    source: str
    run_id: int
    status: str  # 'success' ou 'failed'
    rows_fetched: int
    rows_loaded: int
    error: str | None = None


def connect() -> psycopg.Connection:
    """Ouvre la connexion à la base du hub (adresse lue dans HUB_DATABASE_URL)."""
    url = os.getenv("HUB_DATABASE_URL")
    if not url:
        raise RuntimeError("HUB_DATABASE_URL manquant dans .env")
    return psycopg.connect(url, autocommit=True)


def upsert_customers(conn: psycopg.Connection, customers: list[Customer]) -> int:
    """Insère ou met à jour les clients, en une seule transaction."""
    rows = [
        (c.source, c.source_id, c.name, c.email, c.phone, c.city,
         c.postal_code, c.country, Jsonb(c.payload))
        for c in customers
    ]
    if not rows:
        return 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(UPSERT_CUSTOMER, rows)
    return len(rows)


def start_run(conn: psycopg.Connection, source: str, entity: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.sync_runs "
            "(source, entity, started_at, status, rows_fetched, rows_loaded) "
            "VALUES (%s, %s, now(), 'running', 0, 0) RETURNING run_id",
            (source, entity),
        )
        return cur.fetchone()[0]


def finish_run(conn: psycopg.Connection, run_id: int, status: str,
               rows_fetched: int, rows_loaded: int,
               error_message: str | None = None) -> None:
    conn.execute(
        "UPDATE raw.sync_runs SET finished_at = now(), status = %s, "
        "rows_fetched = %s, rows_loaded = %s, error_message = %s "
        "WHERE run_id = %s",
        (status, rows_fetched, rows_loaded, error_message, run_id),
    )


def sync_source(conn: psycopg.Connection, connector, entity: str = "customers") -> SyncResult:
    """Synchronise un ERP. Ne lève pas d'exception : l'échec est tracé dans le journal."""
    run_id = start_run(conn, connector.source, entity)
    fetched = 0
    try:
        records = connector.fetch_customers()
        fetched = len(records)
        customers = [connector.normalize(r) for r in records]
        loaded = upsert_customers(conn, customers)
    except Exception as exc:  # noqa: BLE001 - on trace toute erreur d'un ERP
        message = f"{type(exc).__name__}: {exc}"[:500]
        finish_run(conn, run_id, "failed", fetched, 0, message)
        return SyncResult(connector.source, run_id, "failed", fetched, 0, message)
    finish_run(conn, run_id, "success", fetched, loaded)
    return SyncResult(connector.source, run_id, "success", fetched, loaded)