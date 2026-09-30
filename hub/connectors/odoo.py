"""Connecteur Odoo (XML-RPC).

Contrat commun aux connecteurs : ping(), fetch_customers(), normalize().
"""
import os
import xmlrpc.client

from hub.models import Customer, clean

SOURCE = "odoo"
FIELDS = ["name", "email", "phone", "city", "zip", "country_id", "write_date"]
ENV_KEYS = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD")


class OdooConnector:
    source = SOURCE

    def __init__(self, url: str, db: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.db = db
        self.user = user
        self.password = password
        self._uid = None
        self._models = None

    @classmethod
    def from_env(cls):
        """Cree le connecteur depuis le .env, ou None si une variable manque."""
        values = [os.getenv(key) for key in ENV_KEYS]
        if not all(values):
            return None
        return cls(*values)

    def _authenticate(self) -> int:
        if self._uid is None:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            uid = common.authenticate(self.db, self.user, self.password, {})
            if not uid:
                raise ConnectionError("Odoo : authentification refusee")
            self._uid = uid
            self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        return self._uid

    def _call(self, model: str, method: str, *args, **kwargs):
        self._authenticate()
        return self._models.execute_kw(
            self.db, self._uid, self.password, model, method, list(args), kwargs
        )

    def ping(self) -> bool:
        """True si Odoo repond et que les identifiants sont acceptes."""
        try:
            self._authenticate()
            return True
        except (OSError, xmlrpc.client.Error):
            return False

    def fetch_customers(self) -> list[dict]:
        """Societes d'Odoo, hors societe proprietaire de la base."""
        companies = self._call("res.company", "search_read", [], fields=["partner_id"])
        own_ids = [c["partner_id"][0] for c in companies if c["partner_id"]]
        domain = [["is_company", "=", True], ["id", "not in", own_ids]]
        return self._call("res.partner", "search_read", domain, fields=FIELDS)

    def normalize(self, record: dict) -> Customer:
        country = record.get("country_id")  # [233, 'United States'] ou False
        return Customer(
            source=SOURCE,
            source_id=str(record["id"]),
            name=clean(record.get("name")),
            email=clean(record.get("email")),
            phone=clean(record.get("phone")),
            city=clean(record.get("city")),
            postal_code=clean(record.get("zip")),
            country=clean(country[1]) if country else None,
            payload=record,
        )