"""Tests des regles de controle (sans base de donnees)."""
from datetime import date
from decimal import Decimal

from hub.matching import CustomerRow
from hub.quality_rules import (
    QualityData, check_cross_erp_mismatch, check_invoice_due_before_date,
    check_invoice_total_mismatch, check_invoice_unknown_customer, check_lookalikes,
    check_missing_email, check_unknown_country, detect_all,
)


def member(source, source_id, **kw):
    base = {"source": source, "source_id": source_id, "name": "Acme", "email": None,
            "postal_code": None, "city": None, "country_code": None}
    base.update(kw)
    return base


# --- customer_missing_email ---------------------------------------------

def test_missing_email_flags_only_clients_without_valid_email():
    customers = [{"customer_id": 1, "name": "A", "email": None},
                 {"customer_id": 2, "name": "B", "email": "b@b.ch"},
                 {"customer_id": 3, "name": "C", "email": "pas-un-email"}]
    keys = [a.entity_key for a in check_missing_email(customers)]
    assert keys == ["1", "3"]


# --- cross_erp_mismatch -------------------------------------------------

def test_cross_erp_mismatch_detects_different_postal_codes():
    members = {7: [member("odoo", "1", postal_code="1004"),
                   member("dolibarr", "2", postal_code="1003")]}
    (anomaly,) = check_cross_erp_mismatch(members)
    assert anomaly.rule_code == "cross_erp_mismatch"
    assert anomaly.entity_key == "7:postal_code"
    assert anomaly.details["values"] == {"odoo:1": "1004", "dolibarr:2": "1003"}


def test_cross_erp_mismatch_ignores_case_accents_and_missing_values():
    members = {7: [member("odoo", "1", city="Genève", email="A@a.ch"),
                   member("dolibarr", "2", city="GENEVE", email="a@A.ch"),
                   member("erpnext", "3", city=None, email=None)]}
    assert check_cross_erp_mismatch(members) == []


def test_cross_erp_mismatch_one_anomaly_per_field():
    members = {7: [member("odoo", "1", city="Lausanne", country_code="CH"),
                   member("dolibarr", "2", city="Genève", country_code="FR")]}
    keys = sorted(a.entity_key for a in check_cross_erp_mismatch(members))
    assert keys == ["7:city", "7:country_code"]


def test_single_row_client_has_no_mismatch():
    assert check_cross_erp_mismatch({1: [member("odoo", "1", city="X")]}) == []


# --- lookalike_customers ------------------------------------------------

def test_lookalikes_reports_unmerged_near_duplicates_with_stable_key():
    rows = [CustomerRow("erpnext", "B", "Grant Plastics Ltd.", None, "8001", None, 2),
            CustomerRow("erpnext", "A", "Grant Plastic", None, "8001", None, 1)]
    (anomaly,) = check_lookalikes(rows)
    assert anomaly.entity_key == "erpnext:A|erpnext:B"
    assert anomaly.details["why_not_merged"] == "meme ERP"


# --- unknown_country ----------------------------------------------------

def test_unknown_country_flags_unrecognised_non_empty_values_only():
    raw = [{"source": "odoo", "source_id": "1", "name": "A", "country": "Atlantide"},
           {"source": "odoo", "source_id": "2", "name": "B", "country": "Switzerland"},
           {"source": "odoo", "source_id": "3", "name": "C", "country": None},
           {"source": "odoo", "source_id": "4", "name": "D", "country": "  "}]
    assert [a.entity_key for a in check_unknown_country(raw)] == ["odoo:1"]


# --- factures -----------------------------------------------------------

def invoice(**kw):
    base = {"source": "odoo", "source_id": "10", "number": "F1", "customer_source_id": "5",
            "invoice_date": date(2026, 9, 1), "due_date": date(2026, 10, 1),
            "total_excl_tax": Decimal("100.00")}
    base.update(kw)
    return base


def test_invoice_unknown_customer():
    keys = {("odoo", "5")}
    assert check_invoice_unknown_customer([invoice()], keys) == []
    (anomaly,) = check_invoice_unknown_customer([invoice(customer_source_id="99")], keys)
    assert anomaly.severity == "high"
    assert check_invoice_unknown_customer([invoice(customer_source_id=None)], keys) == []


def test_invoice_total_mismatch_uses_a_tolerance_and_needs_lines():
    key = ("odoo", "10")
    assert check_invoice_total_mismatch([invoice()], {key: Decimal("100.005")}) == []
    assert len(check_invoice_total_mismatch([invoice()], {key: Decimal("90")})) == 1
    assert check_invoice_total_mismatch([invoice()], {}) == []
    assert check_invoice_total_mismatch([invoice(total_excl_tax=None)], {key: Decimal("1")}) == []


def test_invoice_due_before_date():
    assert check_invoice_due_before_date([invoice()]) == []
    assert check_invoice_due_before_date([invoice(due_date=None)]) == []
    assert len(check_invoice_due_before_date([invoice(due_date=date(2026, 8, 1))])) == 1


# --- ensemble -----------------------------------------------------------

def test_detect_all_is_sorted_and_empty_data_gives_nothing():
    assert detect_all(QualityData()) == []
    data = QualityData(
        customers=[{"customer_id": 2, "name": "B", "email": None},
                   {"customer_id": 1, "name": "A", "email": None}],
        invoices=[invoice(due_date=date(2026, 8, 1))],
        customer_keys={("odoo", "5")},
    )
    found = detect_all(data)
    assert [(a.rule_code, a.entity_key) for a in found] == [
        ("customer_missing_email", "1"), ("customer_missing_email", "2"),
        ("invoice_due_before_date", "odoo:10"),
    ]