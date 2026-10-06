"""Modele commun des clients, factures, lignes et articles.

Contient aussi le nettoyage des valeurs vides et les conversions de formats
(montants, dates) qui permettent de comparer les trois ERP.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

DOC_TYPES = ("invoice", "credit_note")


def clean(value: Any) -> Any:
    """Uniformise les valeurs vides : False (Odoo), None, "" et espaces -> None.

    On teste `is False` (et non `not value`) pour que 0 reste 0.
    """
    if value is False or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def to_decimal(value: Any) -> Decimal | None:
    """Montant ou quantite -> Decimal exact. Les vides deviennent None."""
    value = clean(value)
    if value is None:
        return None
    return Decimal(str(value))  # str() evite le bruit des flottants


def _is_unix(value: Any) -> bool:
    """Vrai pour un horodatage Unix (nombre ou texte fait de chiffres)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and value.strip().isdigit()


def _from_unix(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def to_date(value: Any) -> date | None:
    """Date au format Unix (Dolibarr) ou ISO (Odoo, ERPNext) -> date."""
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, datetime):  # datetime avant date : c'en est une sous-classe
        return value.date()
    if isinstance(value, date):
        return value
    if _is_unix(value):
        return _from_unix(value).date()
    return datetime.fromisoformat(str(value)).date()


def to_datetime(value: Any) -> datetime | None:
    """Instant au format Unix ou ISO -> datetime avec fuseau UTC.

    Hypothese : un texte sans fuseau est exprime en UTC.
    """
    value = clean(value)
    if value is None:
        return None
    if _is_unix(value):
        return _from_unix(value)
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Customer:
    """Un client, dans le format commun aux trois ERP."""

    source: str                 # 'odoo', 'dolibarr', 'erpnext'
    source_id: str              # identifiant du client dans l'ERP
    name: str | None
    email: str | None
    phone: str | None
    city: str | None
    postal_code: str | None
    country: str | None
    payload: dict               # enregistrement brut de l'ERP


@dataclass
class Invoice:
    """Une facture ou un avoir client, dans le format commun."""

    source: str
    source_id: str
    number: str | None
    customer_source_id: str | None   # source_id du client dans le meme ERP
    doc_type: str                    # 'invoice' ou 'credit_note'
    invoice_date: date | None
    due_date: date | None
    status: str | None               # statut tel que l'ERP l'ecrit
    currency: str | None
    total_excl_tax: Decimal | None
    total_incl_tax: Decimal | None
    source_modified_at: datetime | None
    payload: dict

    def __post_init__(self):
        if self.doc_type not in DOC_TYPES:
            raise ValueError(
                f"doc_type inconnu : {self.doc_type!r} (attendu : {DOC_TYPES})"
            )


@dataclass
class InvoiceLine:
    """Une ligne de facture. Le produit peut etre absent (ligne libre)."""

    source: str
    source_id: str
    invoice_source_id: str
    product_source_id: str | None
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    total_excl_tax: Decimal | None
    source_modified_at: datetime | None
    payload: dict


@dataclass
class Item:
    """Un article (produit ou service), dans le format commun."""

    source: str
    source_id: str
    code: str | None
    name: str | None
    category: str | None
    sale_price: Decimal | None
    is_sellable: bool | None
    source_modified_at: datetime | None
    payload: dict