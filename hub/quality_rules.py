"""Regles de controle de la couche quality (logique pure, sans base de donnees).

Chaque regle recoit des donnees deja lues et renvoie une liste d'Anomaly. Une anomalie est
identifiee par (rule_code, entity_key) : c'est ce qui permet de la retrouver a chaque passage.

Regles :
  customer_missing_email    client core sans aucun e-mail
  cross_erp_mismatch        meme client, valeurs differentes selon l'ERP (e-mail, code postal,
                            ville, pays)
  lookalike_customers       fiches qui se ressemblent sans avoir ete fusionnees
  unknown_country           pays renseigne mais absent de la table ISO
  invoice_unknown_customer  facture dont le client n'existe pas dans raw
  invoice_total_mismatch    total de la facture different de la somme de ses lignes
  invoice_due_before_date   echeance anterieure a la date de facture
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Mapping

from hub.matching import (
    CustomerRow, country_to_iso, normalize_email, normalize_name, normalize_postal,
)
from hub.review_core import find_suspects

TOTAL_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class Anomaly:
    rule_code: str
    entity_type: str
    entity_key: str
    severity: str          # 'low', 'medium' ou 'high'
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class QualityData:
    """Tout ce dont les regles ont besoin, deja lu depuis la base."""

    customers: list = field(default_factory=list)       # core.customers : customer_id, name, email
    members: dict = field(default_factory=dict)         # customer_id -> fiches raw du client
    rows: list = field(default_factory=list)            # CustomerRow avec customer_id
    raw_customers: list = field(default_factory=list)   # fiches raw : source, source_id, name, country
    invoices: list = field(default_factory=list)        # raw.invoices
    customer_keys: set = field(default_factory=set)     # {(source, source_id)} des clients raw
    line_totals: dict = field(default_factory=dict)     # (source, source_id) -> somme des lignes


def _key(source, source_id) -> str:
    return f"{source}:{source_id}"


# --- clients --------------------------------------------------------------

def check_missing_email(customers: Iterable[Mapping]) -> list[Anomaly]:
    return [
        Anomaly("customer_missing_email", "core_customer", str(c["customer_id"]), "low",
                f"Client sans e-mail : {c.get('name') or '(sans nom)'}", {"name": c.get("name")})
        for c in customers if not normalize_email(c.get("email"))
    ]


_COMPARED_FIELDS = (
    ("email", normalize_email),
    ("postal_code", normalize_postal),
    ("city", normalize_name),
    ("country_code", lambda v: v or None),
)


def check_cross_erp_mismatch(members: Mapping[int, list]) -> list[Anomaly]:
    anomalies = []
    for customer_id, group in members.items():
        for field_name, normalize in _COMPARED_FIELDS:
            values = {}
            for m in group:
                normalized = normalize(m.get(field_name))
                if normalized:
                    values[_key(m["source"], m["source_id"])] = m.get(field_name)
            if len({normalize(v) for v in values.values()}) > 1:
                names = sorted({m.get("name") for m in group if m.get("name")})
                anomalies.append(Anomaly(
                    "cross_erp_mismatch", "core_customer", f"{customer_id}:{field_name}", "medium",
                    f"Valeurs différentes selon l'ERP pour {field_name} : {names[0] if names else customer_id}",
                    {"field": field_name, "values": values},
                ))
    return anomalies


def check_lookalikes(rows: Iterable[CustomerRow]) -> list[Anomaly]:
    anomalies = []
    for s in find_suspects(rows):
        a, b = sorted((_key(s.a.source, s.a.source_id), _key(s.b.source, s.b.source_id)))
        anomalies.append(Anomaly(
            "lookalike_customers", "raw_customer_pair", f"{a}|{b}", "medium",
            f"Fiches qui se ressemblent, non fusionnées : {s.a.name} et {s.b.name}",
            {"evidence": s.evidence, "why_not_merged": s.why_not_merged},
        ))
    return anomalies


def check_unknown_country(raw_customers: Iterable[Mapping]) -> list[Anomaly]:
    anomalies = []
    for c in raw_customers:
        country = (c.get("country") or "").strip()
        if country and country_to_iso(country) is None:
            anomalies.append(Anomaly(
                "unknown_country", "raw_customer", _key(c["source"], c["source_id"]), "low",
                f"Pays non reconnu : {country} ({c.get('name')})", {"country": country},
            ))
    return anomalies


# --- factures -------------------------------------------------------------

def check_invoice_unknown_customer(invoices: Iterable[Mapping], customer_keys: set) -> list[Anomaly]:
    return [
        Anomaly("invoice_unknown_customer", "raw_invoice", _key(i["source"], i["source_id"]), "high",
                f"Facture {i.get('number') or i['source_id']} : client inconnu ({i['customer_source_id']})",
                {"customer_source_id": i["customer_source_id"]})
        for i in invoices
        if i.get("customer_source_id") is not None
        and (i["source"], i["customer_source_id"]) not in customer_keys
    ]


def check_invoice_total_mismatch(invoices: Iterable[Mapping], line_totals: Mapping) -> list[Anomaly]:
    anomalies = []
    for i in invoices:
        key = (i["source"], i["source_id"])
        total = i.get("total_excl_tax")
        if key not in line_totals or total is None:
            continue
        if abs(Decimal(total) - Decimal(line_totals[key])) > TOTAL_TOLERANCE:
            anomalies.append(Anomaly(
                "invoice_total_mismatch", "raw_invoice", _key(*key), "high",
                f"Facture {i.get('number') or i['source_id']} : total différent de la somme des lignes",
                {"total": str(total), "lines_total": str(line_totals[key])},
            ))
    return anomalies


def check_invoice_due_before_date(invoices: Iterable[Mapping]) -> list[Anomaly]:
    return [
        Anomaly("invoice_due_before_date", "raw_invoice", _key(i["source"], i["source_id"]), "medium",
                f"Facture {i.get('number') or i['source_id']} : échéance avant la date de facture",
                {"invoice_date": str(i["invoice_date"]), "due_date": str(i["due_date"])})
        for i in invoices
        if i.get("invoice_date") and i.get("due_date") and i["due_date"] < i["invoice_date"]
    ]


def detect_all(data: QualityData) -> list[Anomaly]:
    """Applique toutes les regles. Le resultat est trie pour etre deterministe."""
    anomalies = [
        *check_missing_email(data.customers),
        *check_cross_erp_mismatch(data.members),
        *check_lookalikes(data.rows),
        *check_unknown_country(data.raw_customers),
        *check_invoice_unknown_customer(data.invoices, data.customer_keys),
        *check_invoice_total_mismatch(data.invoices, data.line_totals),
        *check_invoice_due_before_date(data.invoices),
    ]
    return sorted(anomalies, key=lambda a: (a.rule_code, a.entity_key))