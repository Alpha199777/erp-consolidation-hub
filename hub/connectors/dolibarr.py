"""Connecteur Dolibarr : lit les clients via l'API REST.

Même contrat que les autres connecteurs : ping(), fetch_customers(), normalize().
"""
from __future__ import annotations

import os

import requests

from hub.models import Customer, clean

ENV_KEYS = ("DOLIBARR_URL", "DOLIBARR_API_KEY")

# Champ Dolibarr `client` : 0 = ni client ni prospect, 1 = client,
# 2 = prospect, 3 = client et prospect (vérifié : 25 clients dans l'interface).
CLIENT_CODES = {"1", "3"}

DEFAULT_PAGE_SIZE = 100
TIMEOUT = 15


class DolibarrConnector:
    source = "dolibarr"

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

    def ping(self) -> bool:
        try:
            return self._get("status").status_code == 200
        except requests.RequestException:
            return False

    def fetch_customers(self) -> list[dict]:
        """Retourne les enregistrements bruts des clients (client = 1 ou 3)."""
        records: list[dict] = []
        page = 0
        while True:
            r = self._get(
                "thirdparties",
                limit=self.page_size,
                page=page,
                sortfield="t.rowid",
                sortorder="ASC",
            )
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