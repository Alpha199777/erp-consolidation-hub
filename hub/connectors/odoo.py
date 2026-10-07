"""Connecteur Odoo (XML-RPC).

Contrat commun aux connecteurs :
  - ping()
  - fetch_customers() / normalize()
  - fetch_invoices() / normalize_invoice()
  - fetch_invoice_lines(invoices=None) / normalize_invoice_line()
  - fetch_items() / normalize_item()
"""
import os
import xmlrpc.client

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

SOURCE = "odoo"
FIELDS = ["name", "email", "phone", "city", "zip", "country_id", "write_date"]
ENV_KEYS = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD")

# Factures clients et avoirs clients : meme modele account.move
MOVE_TYPES = ["out_invoice", "out_refund"]
DOC_TYPES = {"out_invoice": "invoice", "out_refund": "credit_note"}
INVOICE_FIELDS = [
    "name", "partner_id", "move_type", "invoice_date", "invoice_date_due",
    "state", "payment_state", "amount_untaxed", "amount_total",
    "currency_id", "write_date",
]
LINE_FIELDS = [
    "move_id", "product_id", "name", "quantity", "price_unit",
    "price_subtotal", "write_date",
]
# Lu sur product.product (variantes) : c'est ce que les lignes de facture referencent.
ITEM_FIELDS = [
    "name", "default_code", "list_price", "categ_id", "sale_ok", "active",
    "write_date",
]


def _many2one_id(value) -> str | None:
    """[10, 'Acme'] -> '10' ; False -> None."""
    return str(value[0]) if value else None


def _many2one_label(value) -> str | None:
    """[4, 'CHF'] -> 'CHF' ; False -> None."""
    return clean(value[1]) if value else None


def _invoice_status(record: dict) -> str | None:
    """Statut Odoo : 'posted/not_paid' (etat + etat de paiement)."""
    state = clean(record.get("state"))
    payment = clean(record.get("payment_state"))
    return f"{state}/{payment}" if state and payment else state


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

    # ---------- Clients ----------
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

    # ---------- Factures et avoirs ----------
    def fetch_invoices(self) -> list[dict]:
        """Factures et avoirs clients, tous statuts confondus."""
        domain = [["move_type", "in", MOVE_TYPES]]
        return self._call("account.move", "search_read", domain, fields=INVOICE_FIELDS)

    def normalize_invoice(self, record: dict) -> Invoice:
        return Invoice(
            source=SOURCE,
            source_id=str(record["id"]),
            number=clean(record.get("name")),
            customer_source_id=_many2one_id(record.get("partner_id")),
            doc_type=DOC_TYPES[record["move_type"]],
            invoice_date=to_date(record.get("invoice_date")),
            due_date=to_date(record.get("invoice_date_due")),
            status=_invoice_status(record),
            currency=_many2one_label(record.get("currency_id")),
            total_excl_tax=to_decimal(record.get("amount_untaxed")),
            total_incl_tax=to_decimal(record.get("amount_total")),
            source_modified_at=to_datetime(record.get("write_date")),
            payload=record,
        )

    # ---------- Lignes de facture ----------
    def fetch_invoice_lines(self, invoices: list[dict] | None = None) -> list[dict]:
        """Lignes produit des factures et avoirs clients.

        `invoices` est accepte pour respecter le contrat commun des connecteurs,
        mais Odoo lit toutes les lignes en un seul appel : le parametre est ignore.
        """
        domain = [
            ["move_id.move_type", "in", MOVE_TYPES],
            ["display_type", "=", "product"],
        ]
        return self._call("account.move.line", "search_read", domain, fields=LINE_FIELDS)

    def normalize_invoice_line(self, record: dict) -> InvoiceLine:
        return InvoiceLine(
            source=SOURCE,
            source_id=str(record["id"]),
            invoice_source_id=_many2one_id(record["move_id"]),
            product_source_id=_many2one_id(record.get("product_id")),
            description=clean(record.get("name")),
            quantity=to_decimal(record.get("quantity")),
            unit_price=to_decimal(record.get("price_unit")),
            total_excl_tax=to_decimal(record.get("price_subtotal")),
            source_modified_at=to_datetime(record.get("write_date")),
            payload=record,
        )

    # ---------- Articles ----------
    def fetch_items(self) -> list[dict]:
        """Articles actifs (variantes de produit)."""
        return self._call("product.product", "search_read", [], fields=ITEM_FIELDS)

    def normalize_item(self, record: dict) -> Item:
        return Item(
            source=SOURCE,
            source_id=str(record["id"]),
            code=clean(record.get("default_code")),
            name=clean(record.get("name")),
            category=_many2one_label(record.get("categ_id")),
            sale_price=to_decimal(record.get("list_price")),
            is_sellable=bool(record.get("sale_ok")) and bool(record.get("active")),
            source_modified_at=to_datetime(record.get("write_date")),
            payload=record,
        )