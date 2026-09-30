"""Modele commun des clients et nettoyage des valeurs vides."""
from dataclasses import dataclass
from typing import Any


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