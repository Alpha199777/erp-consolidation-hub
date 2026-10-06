from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from hub.models import Invoice, InvoiceLine, Item, to_date, to_datetime, to_decimal


# ---------- to_decimal ----------
def test_to_decimal_from_text():
    assert to_decimal("29.00000000") == Decimal("29")


def test_to_decimal_from_float_has_no_float_noise():
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(41750.0) == Decimal("41750")


def test_to_decimal_empty_values():
    for empty in (None, False, "", "   "):
        assert to_decimal(empty) is None


def test_to_decimal_zero_stays_zero():
    assert to_decimal(0) == Decimal("0")
    assert to_decimal("0.00000000") == Decimal("0")


# ---------- to_date ----------
def test_to_date_from_unix_int():
    assert to_date(1780358400) == date(2026, 6, 2)  # valeur reelle de Dolibarr


def test_to_date_from_unix_text():
    assert to_date("1780358400") == date(2026, 6, 2)


def test_to_date_from_iso_date():
    assert to_date("2026-10-04") == date(2026, 10, 4)


def test_to_date_from_iso_datetime_text():
    assert to_date("2026-09-30 15:15:40.435552") == date(2026, 9, 30)


def test_to_date_empty():
    for empty in (None, False, ""):
        assert to_date(empty) is None


# ---------- to_datetime ----------
def test_to_datetime_from_unix():
    assert to_datetime(1780417344) == datetime(2026, 6, 2, 16, 22, 24, tzinfo=timezone.utc)


def test_to_datetime_erpnext_microseconds():
    result = to_datetime("2026-09-30 15:15:40.435552")
    assert result == datetime(2026, 9, 30, 15, 15, 40, 435552, tzinfo=timezone.utc)


def test_to_datetime_odoo_format():
    result = to_datetime("2026-10-06 17:26:20")
    assert result == datetime(2026, 10, 6, 17, 26, 20, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_to_datetime_empty():
    for empty in (None, False, ""):
        assert to_datetime(empty) is None


# ---------- dataclasses ----------
def _invoice(doc_type):
    return Invoice(
        source="odoo", source_id="2", number="FAC/2026/00002",
        customer_source_id="10", doc_type=doc_type,
        invoice_date=date(2026, 10, 4), due_date=date(2026, 10, 6),
        status="posted", currency="CHF",
        total_excl_tax=Decimal("41750"), total_incl_tax=Decimal("41750"),
        source_modified_at=None, payload={},
    )


def test_invoice_rejects_unknown_doc_type():
    with pytest.raises(ValueError):
        _invoice("bill")


def test_invoice_accepts_credit_note():
    assert _invoice("credit_note").doc_type == "credit_note"


def test_invoice_line_without_product():
    line = InvoiceLine(
        source="dolibarr", source_id="2108", invoice_source_id="476",
        product_source_id=None, description="P1", quantity=Decimal("2"),
        unit_price=Decimal("10"), total_excl_tax=Decimal("19"),
        source_modified_at=None, payload={},
    )
    assert line.product_source_id is None


def test_item_builds():
    item = Item(
        source="erpnext", source_id="SKU001", code="SKU001", name="T-shirt",
        category="Demo Item Group", sale_price=Decimal("0"), is_sellable=True,
        source_modified_at=None, payload={},
    )
    assert item.is_sellable is True