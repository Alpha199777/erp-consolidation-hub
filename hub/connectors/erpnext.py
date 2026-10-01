"""Connecteur ERPNext : lit les clients via l'API REST de Frappe.

Même contrat que les autres connecteurs : ping(), fetch_customers(), normalize().
Ville, code postal et pays ne sont pas sur le Customer : ils sont dans le
doctype Address (enrichissement prévu au sprint 2).
"""
from __future__ import annotations

import json
import os

import requests

from hub.models import Customer, clean

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