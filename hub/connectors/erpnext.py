"""Connecteur ERPNext : lit clients, factures, lignes et articles via l'API REST de Frappe.

Contrat commun aux connecteurs :
  - ping()
  - fetch_customers(since=None) / normalize()
  - fetch_invoices(since=None) / normalize_invoice()
  - fetch_invoice_lines(invoices=None) / normalize_invoice_line()
  - fetch_items(since=None) / normalize_item()
  - record_modified_at(record) : date de modification d'un enregistrement brut
  - overlap : marge relue avant le point de reprise (synchronisation incrementale)

Ville, code postal et pays ne sont pas sur le Customer : ils sont dans le
doctype Address, relie au client par une table enfant (links). fetch_customers()
enrichit chaque client avec l'adresse retenue (voir choose_address).

`since` : sans lui, lecture complete ; avec lui, seulement les enregistrements dont
`modified` est egal ou posterieur. Un client dont seule l'adresse a change est
relu aussi (son `modified` n'a pas bouge).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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


def _utc(value: datetime) -> datetime:
    """Instant avec fuseau UTC (un instant sans fuseau est lu comme UTC)."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def _erpnext_datetime(since: datetime) -> str:
    """Instant -> texte du champ `modified` d'ERPNext (UTC, avec microsecondes)."""
    return _utc(since).strftime("%Y-%m-%d %H:%M:%S.%f")


def _newest_modified(values: list) -> str | None:
    """Plus recente des dates de modification (texte d'origine), ou None."""
    dated = [(to_datetime(v), v) for v in values if clean(v) is not None]
    return max(dated, key=lambda pair: pair[0])[1] if dated else None


def choose_address(addresses: list[dict], primary_name: str | None = None) -> dict | None:
    """Choisit l'adresse d'un client parmi toutes celles qui lui sont liées.

    On écarte les adresses désactivées et celles de la société elle-même, puis
    on garde la première selon cet ordre :
      1. l'adresse déclarée sur le client (customer_primary_address) ;
      2. l'adresse marquée principale (is_primary_address) ;
      3. l'adresse de type Billing ;
      4. à égalité, le nom le plus petit (résultat toujours le même).
    Le nom d'une adresse ne dit rien de son type : on lit address_type.
    """
    candidates = [
        a for a in addresses
        if not a.get("disabled") and not a.get("is_your_company_address")
    ]
    if not candidates:
        return None

    def rank(address: dict):
        return (
            0 if primary_name and address.get("name") == primary_name else 1,
            0 if address.get("is_primary_address") else 1,
            0 if address.get("address_type") == "Billing" else 1,
            str(address.get("name")),
        )

    return min(candidates, key=rank)


class ERPNextConnector:
    source = "erpnext"
    # Marge relue avant le point de reprise : couvre les ecritures tardives et le
    # fuseau du serveur (non verifie, lu comme UTC).
    overlap = timedelta(minutes=5)

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

    def record_modified_at(self, record: dict) -> datetime | None:
        """Date de derniere modification d'un enregistrement brut.

        Pour un client dont l'adresse a change plus tard, `_modified_max` (ajoute par
        fetch_customers) l'emporte sur `modified`.
        """
        return to_datetime(record.get("_modified_max") or record.get("modified"))

    # ---------- Clients ----------
    def fetch_customers(self, since: datetime | None = None) -> list[dict]:
        """Retourne les Customer bruts (actifs ou non), enrichis de leur adresse.

        L'adresse retenue est ajoutée sous la clé '_address' (enregistrement brut
        de l'Address). Un client sans adresse n'a pas cette clé.
        Avec `since` : les clients modifies depuis cette date, plus ceux dont une
        adresse a ete modifiee depuis cette date.
        Une erreur de lecture des adresses remonte : mieux vaut un run en échec
        tracé qu'une ville vide sans explication.
        """
        if since is None:
            records = self._list("Customer")
        else:
            records = self._list("Customer", since=since)
        addresses = self.fetch_addresses_by_customer()
        if since is not None:
            records = records + self._customers_with_recent_address(records, addresses, since)
        for record in records:
            linked = addresses.get(str(record["name"]), [])
            chosen = choose_address(linked, clean(record.get("customer_primary_address")))
            if chosen is not None:
                record["_address"] = chosen
            newest = _newest_modified(
                [record.get("modified")] + [a.get("modified") for a in linked]
            )
            if newest is not None and newest != record.get("modified"):
                record["_modified_max"] = newest
        return records

    def _customers_with_recent_address(
        self, records: list[dict], addresses: dict[str, list[dict]], since: datetime
    ) -> list[dict]:
        """Clients absents de `records` mais dont une adresse a change depuis `since`."""
        known = {str(r["name"]) for r in records}
        limit = _utc(since)
        extra: list[dict] = []
        for name, linked in addresses.items():
            if name in known:
                continue
            if not any(
                (to_datetime(a.get("modified")) or datetime.min.replace(tzinfo=timezone.utc))
                >= limit
                for a in linked
            ):
                continue
            response = self._get(f"/api/resource/{quote('Customer')}/{quote(name)}")
            if response.status_code == 404:  # adresse liee a un client disparu : on ignore
                continue
            response.raise_for_status()
            extra.append(response.json().get("data", {}))
        return extra

    def fetch_addresses_by_customer(self) -> dict[str, list[dict]]:
        """Adresses regroupées par nom de client.

        La liste /api/resource/Address ne contient pas la table enfant 'links' :
        on lit chaque adresse seule. Les adresses désactivées et celles de la
        société sont écartées avant cette lecture (un appel de moins chacune).
        """
        by_customer: dict[str, list[dict]] = {}
        for brut in self._list("Address"):
            if brut.get("disabled") or brut.get("is_your_company_address"):
                continue
            name = str(brut["name"])
            response = self._get(f"/api/resource/{quote('Address')}/{quote(name)}")
            response.raise_for_status()
            detail = response.json().get("data", {})
            for link in detail.get("links") or []:
                if link.get("link_doctype") == "Customer":
                    by_customer.setdefault(str(link.get("link_name")), []).append(detail)
        return by_customer

    def normalize(self, record: dict) -> Customer:
        address = record.get("_address") or {}
        return Customer(
            source=self.source,
            source_id=str(record["name"]),
            name=clean(record.get("customer_name")),
            email=clean(record.get("email_id")),
            phone=clean(record.get("mobile_no")),
            city=clean(address.get("city")),
            postal_code=clean(address.get("pincode")),
            country=clean(address.get("country")),
            payload=record,
        )

    # ---------- Sprint 2 : factures, lignes, articles ----------

    def _list(self, doctype: str, since: datetime | None = None) -> list[dict]:
        """Pagine /api/resource/<doctype> (nom du doctype URL-encodé).

        Avec `since` : filtre serveur `modified >= since` envoye a chaque page.
        """
        records: list[dict] = []
        start = 0
        while True:
            params = {
                "fields": json.dumps(["*"]),
                "limit_start": start,
                "limit_page_length": self.page_size,
                "order_by": "name asc",
            }
            if since is not None:
                params["filters"] = json.dumps([["modified", ">=", _erpnext_datetime(since)]])
            response = self._get(f"/api/resource/{quote(doctype)}", **params)
            response.raise_for_status()
            batch = response.json().get("data", [])
            records.extend(batch)
            if len(batch) < self.page_size:
                return records
            start += self.page_size

    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        if since is None:
            return self._list("Sales Invoice")
        return self._list("Sales Invoice", since=since)

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

    def fetch_items(self, since: datetime | None = None) -> list[dict]:
        if since is None:
            return self._list("Item")
        return self._list("Item", since=since)

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