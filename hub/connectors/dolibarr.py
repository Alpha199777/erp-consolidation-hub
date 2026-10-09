"""Connecteur Dolibarr : lit clients, factures, lignes et articles via l'API REST.

Contrat commun aux connecteurs :
  - ping()
  - fetch_customers(since=None) / normalize()
  - fetch_invoices(since=None) / normalize_invoice()
  - fetch_invoice_lines(invoices=None) / normalize_invoice_line()
  - fetch_items(since=None) / normalize_item()
  - record_modified_at(record) : date de modification d'un enregistrement brut
  - overlap : marge relue avant le point de reprise (synchronisation incrementale)

`since` : sans lui, lecture complete ; avec lui, seulement les enregistrements dont
t.tms est strictement apres cette date (seule syntaxe validee). La marge d'un jour
(overlap) rend la difference avec >= sans effet.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

from hub.models import (
    Customer,
    Invoice,
    InvoiceLine,
    Item,
    clean,
    to_date,
    to_datetime,
    to_decimal,
)

ENV_KEYS = ("DOLIBARR_URL", "DOLIBARR_API_KEY")

# Champ Dolibarr `client` : 0 = ni client ni prospect, 1 = client,
# 2 = prospect, 3 = client et prospect (vérifié : 25 clients dans l'interface).
CLIENT_CODES = {"1", "3"}

# Champ Dolibarr `type` d'une facture : 2 = avoir. Tout autre type = facture.
CREDIT_NOTE_TYPES = {"2"}

# Champ Dolibarr `statut` d'une facture (seuls 1 et 2 sont vus dans nos données).
INVOICE_STATUS = {"0": "draft", "1": "validated", "2": "closed", "3": "abandoned"}

DEFAULT_PAGE_SIZE = 100
TIMEOUT = 15


def _id_or_none(value) -> str | None:
    """Identifiant en texte ; vide ou '0' (= pas de lien) -> None."""
    value = clean(value)
    return None if value in (None, 0, "0") else str(value)


def _invoice_status(record: dict) -> str | None:
    """Statut Dolibarr : 'validated/unpaid' (etat + paiement)."""
    code = clean(record.get("statut"))
    if code is None:
        return None
    label = INVOICE_STATUS.get(str(code), f"status_{code}")
    paid = "paid" if str(clean(record.get("paye"))) == "1" else "unpaid"
    return f"{label}/{paid}"


def _since_filter(since: datetime) -> str:
    """Filtre Dolibarr 'modifie apres since' sur t.tms (UTC, a la seconde).

    Un instant sans fuseau est lu comme UTC (meme hypothese que to_datetime).
    """
    if since.tzinfo is not None:
        since = since.astimezone(timezone.utc)
    return f"(t.tms:>:'{since.strftime('%Y-%m-%d %H:%M:%S')}')"


class DolibarrConnector:
    source = "dolibarr"
    # Marge relue avant le point de reprise : le fuseau de t.tms n'est pas verifie,
    # un jour couvre tout decalage horaire.
    overlap = timedelta(days=1)

    def __init__(self, url: str, api_key: str, page_size: int = DEFAULT_PAGE_SIZE):
        self.base = url.rstrip("/") + "/api/index.php"
        self.api_key = api_key
        self.page_size = page_size

    @classmethod
    def from_env(cls):
        """Retourne None si une variable manque : l'ERP est alors ignoré."""
        values = [os.getenv(k) for k in ENV_KEYS]
        if not all(values):
            return None
        return cls(*values)

    def _get(self, path: str, **params):
        return requests.get(
            f"{self.base}/{path}",
            headers={"DOLAPIKEY": self.api_key, "Accept": "application/json"},
            params=params,
            timeout=TIMEOUT,
        )

    def _page_params(self, page: int, since: datetime | None) -> dict:
        """Paramètres d'une page ; le filtre de date n'est ajouté que s'il y a un since."""
        params = {
            "limit": self.page_size,
            "page": page,
            "sortfield": "t.rowid",
            "sortorder": "ASC",
        }
        if since is not None:
            params["sqlfilters"] = _since_filter(since)
        return params

    def _get_all(self, path: str, since: datetime | None = None) -> list[dict]:
        """Parcourt toutes les pages d'une liste (page vide = 404 chez Dolibarr)."""
        records: list[dict] = []
        page = 0
        while True:
            r = self._get(path, **self._page_params(page, since))
            if r.status_code == 404:  # page vide : fin des données
                break
            r.raise_for_status()
            batch = r.json()
            records.extend(batch)
            if len(batch) < self.page_size:
                break
            page += 1
        return records

    def ping(self) -> bool:
        try:
            return self._get("status").status_code == 200
        except requests.RequestException:
            return False

    def record_modified_at(self, record: dict) -> datetime | None:
        """Date de derniere modification d'un enregistrement brut (date_modification, Unix)."""
        return to_datetime(record.get("date_modification"))

    # ---------- Clients ----------
    def fetch_customers(self, since: datetime | None = None) -> list[dict]:
        """Retourne les enregistrements bruts des clients (client = 1 ou 3)."""
        records: list[dict] = []
        page = 0
        while True:
            r = self._get("thirdparties", **self._page_params(page, since))
            if r.status_code == 404:  # page vide : fin des données
                break
            r.raise_for_status()
            batch = r.json()
            records.extend(t for t in batch if str(t.get("client")) in CLIENT_CODES)
            if len(batch) < self.page_size:
                break
            page += 1
        return records

    def normalize(self, record: dict) -> Customer:
        return Customer(
            source=self.source,
            source_id=str(record["id"]),
            name=clean(record.get("name")),
            email=clean(record.get("email")),
            phone=clean(record.get("phone")),
            city=clean(record.get("town")),
            postal_code=clean(record.get("zip")),
            country=clean(record.get("country_code")),
            payload=record,
        )

    # ---------- Factures ----------
    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        """Factures clients brutes, avec leurs lignes (champ `lines`)."""
        if since is None:
            return self._get_all("invoices")
        return self._get_all("invoices", since=since)

    def normalize_invoice(self, record: dict) -> Invoice:
        is_credit_note = str(clean(record.get("type"))) in CREDIT_NOTE_TYPES
        return Invoice(
            source=self.source,
            source_id=str(record["id"]),
            number=clean(record.get("ref")),
            customer_source_id=_id_or_none(record.get("socid")),
            doc_type="credit_note" if is_credit_note else "invoice",
            invoice_date=to_date(record.get("date")),
            due_date=to_date(record.get("date_lim_reglement")),
            status=_invoice_status(record),
            currency=clean(record.get("multicurrency_code")),
            total_excl_tax=to_decimal(record.get("total_ht")),
            total_incl_tax=to_decimal(record.get("total_ttc")),
            source_modified_at=to_datetime(record.get("date_modification")),
            payload=record,
        )

    # ---------- Lignes de facture ----------
    def fetch_invoice_lines(self, invoices: list[dict] | None = None) -> list[dict]:
        """Lignes brutes extraites des factures (deja lues si on les passe).

        Chaque ligne recoit la cle `_invoice_id` (ajoutee par le hub).
        """
        if invoices is None:
            invoices = self.fetch_invoices()
        lines: list[dict] = []
        for invoice in invoices:
            for line in invoice.get("lines") or []:
                lines.append({**line, "_invoice_id": str(invoice["id"])})
        return lines

    def normalize_invoice_line(self, record: dict) -> InvoiceLine:
        return InvoiceLine(
            source=self.source,
            source_id=str(record["id"]),
            invoice_source_id=record["_invoice_id"],
            product_source_id=_id_or_none(record.get("fk_product")),
            description=clean(record.get("desc")) or clean(record.get("product_label")),
            quantity=to_decimal(record.get("qty")),
            unit_price=to_decimal(record.get("subprice")),
            total_excl_tax=to_decimal(record.get("total_ht")),
            source_modified_at=to_datetime(record.get("date_modification")),
            payload=record,
        )

    # ---------- Articles ----------
    def fetch_items(self, since: datetime | None = None) -> list[dict]:
        """Produits et services bruts."""
        if since is None:
            return self._get_all("products")
        return self._get_all("products", since=since)

    def normalize_item(self, record: dict) -> Item:
        return Item(
            source=self.source,
            source_id=str(record["id"]),
            code=clean(record.get("ref")),
            name=clean(record.get("label")),
            category=None,  # les categories demandent un appel d'API separe
            sale_price=to_decimal(record.get("price")),
            is_sellable=str(clean(record.get("status"))) == "1",
            source_modified_at=to_datetime(record.get("date_modification")),
            payload=record,
        )