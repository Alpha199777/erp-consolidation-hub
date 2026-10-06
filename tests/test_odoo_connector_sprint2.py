from datetime import date, datetime, timezone
from decimal import Decimal

from hub.connectors.odoo import OdooConnector

CONN = OdooConnector("http://localhost:8069", "db", "user", "pwd")

# Enregistrement reel lu dans ton Odoo (factures)
INVOICE = {
    "id": 2, "name": "FAC/2026/00002", "partner_id": [10, "Acme Corporation"],
    "move_type": "out_invoice", "invoice_date": "2026-10-04",
    "invoice_date_due": "2026-10-06", "state": "posted",
    "payment_state": "not_paid", "amount_untaxed": 41750.0,
    "amount_total": 41750.0, "currency_id": [4, "CHF"],
    "write_date": "2026-10-06 17:26:20",
}

LINE = {
    "id": 7, "move_id": [2, "FAC/2026/00002"],
    "product_id": [34, "[FURN_8220] Four Person Desk"],
    "name": "[FURN_8220] Bureau pour quatre personnes",
    "quantity": 5.0, "price_unit": 2350.0, "price_subtotal": 11750.0,
    "write_date": "2026-10-06 17:26:12",
}

ITEM = {
    "id": 15, "name": "Cabinet with Doors", "default_code": "E-COM11",
    "list_price": 140.0, "categ_id": [8, "All / Saleable / Office Furniture"],
    "sale_ok": True, "active": True, "write_date": "2026-10-06 17:26:20",
}


def test_normalize_invoice_real_record():
    inv = CONN.normalize_invoice(INVOICE)
    assert inv.source == "odoo"
    assert inv.source_id == "2"
    assert inv.number == "FAC/2026/00002"
    assert inv.customer_source_id == "10"
    assert inv.doc_type == "invoice"
    assert inv.invoice_date == date(2026, 10, 4)
    assert inv.due_date == date(2026, 10, 6)
    assert inv.status == "posted/not_paid"
    assert inv.currency == "CHF"
    assert inv.total_excl_tax == Decimal("41750")
    assert inv.total_incl_tax == Decimal("41750")
    assert inv.source_modified_at == datetime(2026, 10, 6, 17, 26, 20, tzinfo=timezone.utc)
    assert inv.payload is INVOICE


def test_normalize_invoice_credit_note():
    record = {**INVOICE, "id": 9, "move_type": "out_refund"}
    assert CONN.normalize_invoice(record).doc_type == "credit_note"


def test_normalize_invoice_empty_values():
    # Cas limite invente : Odoo renvoie False pour les champs vides
    record = {**INVOICE, "partner_id": False, "invoice_date": False,
              "invoice_date_due": False, "currency_id": False}
    inv = CONN.normalize_invoice(record)
    assert inv.customer_source_id is None
    assert inv.invoice_date is None
    assert inv.due_date is None
    assert inv.currency is None


def test_normalize_invoice_line_real_record():
    line = CONN.normalize_invoice_line(LINE)
    assert line.source_id == "7"
    assert line.invoice_source_id == "2"
    assert line.product_source_id == "34"
    assert line.quantity == Decimal("5")
    assert line.unit_price == Decimal("2350")
    assert line.total_excl_tax == Decimal("11750")
    assert line.source_modified_at == datetime(2026, 10, 6, 17, 26, 12, tzinfo=timezone.utc)


def test_normalize_invoice_line_without_product():
    line = CONN.normalize_invoice_line({**LINE, "product_id": False})
    assert line.product_source_id is None


def test_normalize_item_real_record():
    item = CONN.normalize_item(ITEM)
    assert item.source_id == "15"
    assert item.code == "E-COM11"
    assert item.name == "Cabinet with Doors"
    assert item.category == "All / Saleable / Office Furniture"
    assert item.sale_price == Decimal("140")
    assert item.is_sellable is True


def test_normalize_item_empty_code_and_inactive():
    item = CONN.normalize_item({**ITEM, "default_code": False, "active": False})
    assert item.code is None
    assert item.is_sellable is False


def test_fetch_invoices_queries_both_move_types(monkeypatch):
    calls = []

    def fake_call(model, method, *args, **kwargs):
        calls.append((model, method, args, kwargs))
        return [INVOICE]

    monkeypatch.setattr(CONN, "_call", fake_call)
    assert CONN.fetch_invoices() == [INVOICE]
    model, method, args, _ = calls[0]
    assert (model, method) == ("account.move", "search_read")
    assert args[0] == [["move_type", "in", ["out_invoice", "out_refund"]]]


def test_fetch_invoice_lines_only_product_lines(monkeypatch):
    calls = []
    monkeypatch.setattr(CONN, "_call", lambda *a, **k: calls.append(a) or [LINE])
    assert CONN.fetch_invoice_lines() == [LINE]
    model, method, domain = calls[0]
    assert model == "account.move.line"
    assert ["display_type", "=", "product"] in domain


def test_fetch_items_reads_product_variants(monkeypatch):
    calls = []
    monkeypatch.setattr(CONN, "_call", lambda *a, **k: calls.append(a) or [ITEM])
    assert CONN.fetch_items() == [ITEM]
    assert calls[0][0] == "product.product"