"""Chargement dans PostgreSQL : upsert idempotent + journal des synchronisations."""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from hub.models import Customer, Invoice, InvoiceLine, Item

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

UPSERT_INVOICE = """
INSERT INTO raw.invoices
    (source, source_id, number, customer_source_id, doc_type, invoice_date,
     due_date, status, currency, total_excl_tax, total_incl_tax,
     source_modified_at, payload, first_seen_at, last_synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
ON CONFLICT (source, source_id) DO UPDATE SET
    number = EXCLUDED.number,
    customer_source_id = EXCLUDED.customer_source_id,
    doc_type = EXCLUDED.doc_type,
    invoice_date = EXCLUDED.invoice_date,
    due_date = EXCLUDED.due_date,
    status = EXCLUDED.status,
    currency = EXCLUDED.currency,
    total_excl_tax = EXCLUDED.total_excl_tax,
    total_incl_tax = EXCLUDED.total_incl_tax,
    source_modified_at = EXCLUDED.source_modified_at,
    payload = EXCLUDED.payload,
    last_synced_at = now()
"""

UPSERT_INVOICE_LINE = """
INSERT INTO raw.invoice_lines
    (source, source_id, invoice_source_id, product_source_id, description,
     quantity, unit_price, total_excl_tax, source_modified_at, payload,
     first_seen_at, last_synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
ON CONFLICT (source, source_id) DO UPDATE SET
    invoice_source_id = EXCLUDED.invoice_source_id,
    product_source_id = EXCLUDED.product_source_id,
    description = EXCLUDED.description,
    quantity = EXCLUDED.quantity,
    unit_price = EXCLUDED.unit_price,
    total_excl_tax = EXCLUDED.total_excl_tax,
    source_modified_at = EXCLUDED.source_modified_at,
    payload = EXCLUDED.payload,
    last_synced_at = now()
"""

UPSERT_ITEM = """
INSERT INTO raw.items
    (source, source_id, code, name, category, sale_price, is_sellable,
     source_modified_at, payload, first_seen_at, last_synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
ON CONFLICT (source, source_id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    sale_price = EXCLUDED.sale_price,
    is_sellable = EXCLUDED.is_sellable,
    source_modified_at = EXCLUDED.source_modified_at,
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


def _executemany(conn: psycopg.Connection, sql: str, rows: list[tuple]) -> int:
    """Exécute un upsert en une transaction. Ne fait rien si la liste est vide."""
    if not rows:
        return 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    return len(rows)


def upsert_customers(conn: psycopg.Connection, customers: list[Customer]) -> int:
    """Insère ou met à jour les clients, en une seule transaction."""
    rows = [
        (c.source, c.source_id, c.name, c.email, c.phone, c.city,
         c.postal_code, c.country, Jsonb(c.payload))
        for c in customers
    ]
    return _executemany(conn, UPSERT_CUSTOMER, rows)


def upsert_invoices(conn: psycopg.Connection, invoices: list[Invoice]) -> int:
    """Insère ou met à jour les factures (et avoirs), en une transaction."""
    rows = [
        (i.source, i.source_id, i.number, i.customer_source_id, i.doc_type,
         i.invoice_date, i.due_date, i.status, i.currency, i.total_excl_tax,
         i.total_incl_tax, i.source_modified_at, Jsonb(i.payload))
        for i in invoices
    ]
    return _executemany(conn, UPSERT_INVOICE, rows)


def upsert_invoice_lines(conn: psycopg.Connection, lines: list[InvoiceLine]) -> int:
    """Insère ou met à jour les lignes de facture, en une transaction."""
    rows = [
        (l.source, l.source_id, l.invoice_source_id, l.product_source_id,
         l.description, l.quantity, l.unit_price, l.total_excl_tax,
         l.source_modified_at, Jsonb(l.payload))
        for l in lines
    ]
    return _executemany(conn, UPSERT_INVOICE_LINE, rows)


def upsert_items(conn: psycopg.Connection, items: list[Item]) -> int:
    """Insère ou met à jour les articles, en une transaction."""
    rows = [
        (i.source, i.source_id, i.code, i.name, i.category, i.sale_price,
         i.is_sellable, i.source_modified_at, Jsonb(i.payload))
        for i in items
    ]
    return _executemany(conn, UPSERT_ITEM, rows)


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


def _error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def sync_invoices(conn: psycopg.Connection, connector) -> tuple[SyncResult, SyncResult]:
    """Synchronise factures ET lignes d'un ERP dans une seule transaction.

    Deux lignes de journal (invoices, invoice_lines), un seul bloc atomique :
    une ligne de facture n'existe jamais sans sa facture.
    """
    run_inv = start_run(conn, connector.source, "invoices")
    run_lin = start_run(conn, connector.source, "invoice_lines")
    n_inv = 0
    n_lin = 0
    try:
        raw_invoices = connector.fetch_invoices()
        n_inv = len(raw_invoices)
        raw_lines = connector.fetch_invoice_lines(raw_invoices)
        n_lin = len(raw_lines)
        invoices = [connector.normalize_invoice(r) for r in raw_invoices]
        lines = [connector.normalize_invoice_line(r) for r in raw_lines]
        with conn.transaction():
            loaded_inv = upsert_invoices(conn, invoices)
            loaded_lin = upsert_invoice_lines(conn, lines)
    except Exception as exc:  # noqa: BLE001 - on trace toute erreur d'un ERP
        message = _error_message(exc)
        finish_run(conn, run_inv, "failed", n_inv, 0, message)
        finish_run(conn, run_lin, "failed", n_lin, 0, message)
        return (
            SyncResult(connector.source, run_inv, "failed", n_inv, 0, message),
            SyncResult(connector.source, run_lin, "failed", n_lin, 0, message),
        )
    finish_run(conn, run_inv, "success", n_inv, loaded_inv)
    finish_run(conn, run_lin, "success", n_lin, loaded_lin)
    return (
        SyncResult(connector.source, run_inv, "success", n_inv, loaded_inv),
        SyncResult(connector.source, run_lin, "success", n_lin, loaded_lin),
    )


def sync_source(conn: psycopg.Connection, connector, entity: str = "customers") -> SyncResult:
    """Synchronise une entité d'un ERP. Ne lève pas d'exception : l'échec est tracé.

    Entités : customers, items, invoices (invoices charge aussi les lignes ;
    pour obtenir les deux résultats, appeler sync_invoices directement).
    """
    if entity == "invoices":
        return sync_invoices(conn, connector)[0]
    if entity not in ("customers", "items"):
        raise ValueError(f"Entité inconnue : {entity!r}")

    run_id = start_run(conn, connector.source, entity)
    fetched = 0
    try:
        if entity == "customers":
            records = connector.fetch_customers()
            fetched = len(records)
            objects = [connector.normalize(r) for r in records]
            loaded = upsert_customers(conn, objects)
        else:
            records = connector.fetch_items()
            fetched = len(records)
            objects = [connector.normalize_item(r) for r in records]
            loaded = upsert_items(conn, objects)
    except Exception as exc:  # noqa: BLE001 - on trace toute erreur d'un ERP
        message = _error_message(exc)
        finish_run(conn, run_id, "failed", fetched, 0, message)
        return SyncResult(connector.source, run_id, "failed", fetched, 0, message)
    finish_run(conn, run_id, "success", fetched, loaded)
    return SyncResult(connector.source, run_id, "success", fetched, loaded)