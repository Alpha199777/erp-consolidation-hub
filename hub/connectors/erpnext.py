"""Connecteur ERPNext : lit clients, factures, lignes et articles via l'API REST de Frappe.

Même contrat que les autres connecteurs : ping(), fetch_*(), normalize*().
Ville, code postal et pays ne sont pas sur le Customer : ils sont dans le
doctype Address (enrichissement prévu au sprint 2).
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote

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

ENV_KEYS = ("ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET")

DEFAULT_PAGE_SIZE = 100
TIMEOUT = 15


class ERPNextConnector:
    source = "erpnext"

    def __init__(self, url: str, api_key: str, api_secret: str,
                 page_size: int = DEFAULT_PAGE_SIZE):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
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
            f"{self.url}{path}",
            headers={
                "Authorization": f"token {self.api_key}:{self.api_secret}",
                "Accept": "application/json",
            },
            params=params,
            timeout=TIMEOUT,
        )

    def ping(self) -> bool:
        """Teste la connexion ET les identifiants (l'appel exige une authentification)."""
        try:
            r = self._get("/api/method/frappe.auth.get_logged_user")
            return r.status_code == 200
        except requests.RequestException:
            return False

    def fetch_customers(self) -> list[dict]:
        """Retourne tous les enregistrements bruts Customer (actifs ou non)."""
        records: list[dict] = []
        start = 0
        while True:
            r = self._get(
                "/api/resource/Customer",
                fields=json.dumps(["*"]),
                limit_start=start,
                limit_page_length=self.page_size,
                order_by="name asc",
            )
            r.raise_for_status()
            batch = r.json()["data"]
            records.extend(batch)
            if len(batch) < self.page_size:
                break
            start += self.page_size
        return records

    def normalize(self, record: dict) -> Customer:
        return Customer(
            source=self.source,
            source_id=str(record["name"]),
            name=clean(record.get("customer_name")),
            email=clean(record.get("email_id")),
            phone=clean(record.get("mobile_no")),
            city=None,
            postal_code=None,
            country=None,
            payload=record,
        )

    # ---------- Sprint 2 : factures, lignes, articles ----------

    def _list(self, doctype: str) -> list[dict]:
        """Pagine /api/resource/<doctype> (nom du doctype URL-encodé)."""
        records: list[dict] = []
        start = 0
        while True:
            response = self._get(
                f"/api/resource/{quote(doctype)}",
                fields=json.dumps(["*"]),
                limit_start=start,
                limit_page_length=self.page_size,
                order_by="name asc",
            )
            response.raise_for_status()
            batch = response.json().get("data", [])
            records.extend(batch)
            if len(batch) < self.page_size:
                return records
            start += self.page_size

    def fetch_invoices(self) -> list[dict]:
        return self._list("Sales Invoice")

    def normalize_invoice(self, record: dict) -> Invoice:
        return Invoice(
            source=self.source,
            source_id=str(record["name"]),
            number=clean(record.get("name")),
            customer_source_id=clean(record.get("customer")),
            doc_type="credit_note" if record.get("is_return") else "invoice",
            invoice_date=to_date(record.get("posting_date")),
            due_date=to_date(record.get("due_date")),
            status=clean(record.get("status")),
            currency=clean(record.get("currency")),
            total_excl_tax=to_decimal(record.get("net_total")),
            total_incl_tax=to_decimal(record.get("grand_total")),
            source_modified_at=to_datetime(record.get("modified")),
            payload=record,
        )

    def fetch_invoice_lines(self, invoices: list[dict] | None = None) -> list[dict]:
        # Les lignes sont une table enfant : on lit chaque facture seule
        # et on injecte l'id de la facture parente dans chaque ligne.
        if invoices is None:
            invoices = self.fetch_invoices()
        lines: list[dict] = []
        for invoice in invoices:
            name = str(invoice["name"])
            response = self._get(f"/api/resource/{quote('Sales Invoice')}/{quote(name)}")
            response.raise_for_status()
            document = response.json().get("data", {})
            for line in document.get("items", []):
                line = dict(line)
                line["_invoice_id"] = name
                line["_invoice_modified"] = document.get("modified")
                lines.append(line)
        return lines

    def normalize_invoice_line(self, record: dict) -> InvoiceLine:
        return InvoiceLine(
            source=self.source,
            source_id=str(record["name"]),
            invoice_source_id=str(record["_invoice_id"]),
            product_source_id=clean(record.get("item_code")),
            description=clean(record.get("description")) or clean(record.get("item_name")),
            quantity=to_decimal(record.get("qty")),
            unit_price=to_decimal(record.get("rate")),
            total_excl_tax=to_decimal(record.get("amount")),
            source_modified_at=to_datetime(
                record.get("modified") or record.get("_invoice_modified")
            ),
            payload=record,
        )

    def fetch_items(self) -> list[dict]:
        return self._list("Item")

    def normalize_item(self, record: dict) -> Item:
        return Item(
            source=self.source,
            source_id=str(record["name"]),
            code=clean(record.get("item_code")) or str(record["name"]),
            name=clean(record.get("item_name")),
            category=clean(record.get("item_group")),
            sale_price=to_decimal(record.get("standard_rate")),
            is_sellable=bool(record.get("is_sales_item")) and not bool(record.get("disabled")),
            source_modified_at=to_datetime(record.get("modified")),
            payload=record,
        )