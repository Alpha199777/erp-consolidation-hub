"""Chargement dans PostgreSQL : upsert idempotent + journal des synchronisations.

Trois modes de lecture (parametre `mode`) :
  - "none"        : lecture complete, sans point de reprise (comportement historique) ;
  - "incremental" : lecture depuis le point de reprise de raw.sync_state, moins la marge
                    de recouvrement du connecteur ; sans point de reprise, lecture complete ;
  - "full"        : lecture complete, quel que soit l'etat.
Avec "incremental" et "full", le point de reprise est ecrit dans la MEME transaction que
les donnees : s'il y a un echec, ni l'un ni l'autre n'avance.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from hub.models import Customer, Invoice, InvoiceLine, Item

MODES = ("none", "incremental", "full")

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

# Le point de reprise ne recule jamais (GREATEST ignore les NULL) et la date du
# dernier rechargement complet n'est ecrasee que par un nouveau rechargement complet.
UPSERT_STATE = """
INSERT INTO raw.sync_state
    (source, entity, watermark, last_full_sync_at, last_run_id, updated_at)
VALUES (%s, %s, %s::timestamptz, CASE WHEN %s::boolean THEN now() END, %s::bigint, now())
ON CONFLICT (source, entity) DO UPDATE SET
    watermark = GREATEST(raw.sync_state.watermark, EXCLUDED.watermark),
    last_full_sync_at = COALESCE(EXCLUDED.last_full_sync_at, raw.sync_state.last_full_sync_at),
    last_run_id = EXCLUDED.last_run_id,
    updated_at = now()
"""


@dataclass
class SyncResult:
    source: str
    run_id: int
    status: str  # 'success' ou 'failed'
    rows_fetched: int
    rows_loaded: int
    error: str | None = None
    since: datetime | None = None  # None = lecture complete


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


def get_watermark(conn: psycopg.Connection, source: str, entity: str) -> datetime | None:
    """Point de reprise d'un ERP pour une entité (None s'il n'y en a pas encore)."""
    row = conn.execute(
        "SELECT watermark FROM raw.sync_state WHERE source = %s AND entity = %s",
        (source, entity),
    ).fetchone()
    return row[0] if row else None


def save_state(conn: psycopg.Connection, source: str, entity: str,
               newest: datetime | None, run_id: int, full_read: bool) -> None:
    """Écrit le point de reprise (sans jamais le faire reculer).

    `newest` : plus grande date de modification vue dans cette lecture (None si rien).
    `full_read` : vrai si la lecture était complète (met à jour last_full_sync_at).
    À appeler DANS la transaction qui charge les données.
    """
    conn.execute(UPSERT_STATE, (source, entity, newest, full_read, run_id))


def _error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _check_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Mode inconnu : {mode!r} (attendu : {MODES})")


def _fetch(method, since: datetime | None):
    """Appelle fetch_*() ; l'argument `since` n'est transmis que s'il existe."""
    return method() if since is None else method(since=since)


def _since_for(conn: psycopg.Connection, connector, entity: str, mode: str) -> datetime | None:
    """Date de départ de la lecture : point de reprise moins la marge, ou None (tout lire)."""
    if mode != "incremental":
        return None
    watermark = get_watermark(conn, connector.source, entity)
    if watermark is None:
        return None
    return watermark - connector.overlap


def _newest(connector, records: list[dict]) -> datetime | None:
    """Plus grande date de modification des enregistrements bruts (None si aucune)."""
    dates = [d for d in (connector.record_modified_at(r) for r in records) if d is not None]
    return max(dates) if dates else None


def sync_invoices(conn: psycopg.Connection, connector,
                  mode: str = "none") -> tuple[SyncResult, SyncResult]:
    """Synchronise factures ET lignes d'un ERP dans une seule transaction.

    Deux lignes de journal (invoices, invoice_lines), un seul bloc atomique :
    une ligne de facture n'existe jamais sans sa facture. Le point de reprise
    (entité 'invoices') est écrit dans ce même bloc.
    """
    _check_mode(mode)
    run_inv = start_run(conn, connector.source, "invoices")
    run_lin = start_run(conn, connector.source, "invoice_lines")
    n_inv = 0
    n_lin = 0
    since = None
    try:
        since = _since_for(conn, connector, "invoices", mode)
        raw_invoices = _fetch(connector.fetch_invoices, since)
        n_inv = len(raw_invoices)
        raw_lines = connector.fetch_invoice_lines(raw_invoices)
        n_lin = len(raw_lines)
        invoices = [connector.normalize_invoice(r) for r in raw_invoices]
        lines = [connector.normalize_invoice_line(r) for r in raw_lines]
        with conn.transaction():
            loaded_inv = upsert_invoices(conn, invoices)
            loaded_lin = upsert_invoice_lines(conn, lines)
            if mode != "none":
                save_state(conn, connector.source, "invoices",
                           _newest(connector, raw_invoices), run_inv,
                           full_read=since is None)
    except Exception as exc:  # noqa: BLE001 - on trace toute erreur d'un ERP
        message = _error_message(exc)
        finish_run(conn, run_inv, "failed", n_inv, 0, message)
        finish_run(conn, run_lin, "failed", n_lin, 0, message)
        return (
            SyncResult(connector.source, run_inv, "failed", n_inv, 0, message, since=since),
            SyncResult(connector.source, run_lin, "failed", n_lin, 0, message, since=since),
        )
    finish_run(conn, run_inv, "success", n_inv, loaded_inv)
    finish_run(conn, run_lin, "success", n_lin, loaded_lin)
    return (
        SyncResult(connector.source, run_inv, "success", n_inv, loaded_inv, since=since),
        SyncResult(connector.source, run_lin, "success", n_lin, loaded_lin, since=since),
    )


def sync_source(conn: psycopg.Connection, connector, entity: str = "customers",
                mode: str = "none") -> SyncResult:
    """Synchronise une entité d'un ERP. Ne lève pas d'exception : l'échec est tracé.

    Entités : customers, items, invoices (invoices charge aussi les lignes ;
    pour obtenir les deux résultats, appeler sync_invoices directement).
    """
    if entity == "invoices":
        return sync_invoices(conn, connector, mode)[0]
    if entity not in ("customers", "items"):
        raise ValueError(f"Entité inconnue : {entity!r}")
    _check_mode(mode)

    run_id = start_run(conn, connector.source, entity)
    fetched = 0
    since = None
    try:
        since = _since_for(conn, connector, entity, mode)
        if entity == "customers":
            records = _fetch(connector.fetch_customers, since)
            fetched = len(records)
            objects = [connector.normalize(r) for r in records]
            upsert = upsert_customers
        else:
            records = _fetch(connector.fetch_items, since)
            fetched = len(records)
            objects = [connector.normalize_item(r) for r in records]
            upsert = upsert_items
        if mode == "none":
            loaded = upsert(conn, objects)
        else:
            with conn.transaction():
                loaded = upsert(conn, objects)
                save_state(conn, connector.source, entity,
                           _newest(connector, records), run_id,
                           full_read=since is None)
    except Exception as exc:  # noqa: BLE001 - on trace toute erreur d'un ERP
        message = _error_message(exc)
        finish_run(conn, run_id, "failed", fetched, 0, message)
        return SyncResult(connector.source, run_id, "failed", fetched, 0, message, since=since)
    finish_run(conn, run_id, "success", fetched, loaded)
    return SyncResult(connector.source, run_id, "success", fetched, loaded, since=since)