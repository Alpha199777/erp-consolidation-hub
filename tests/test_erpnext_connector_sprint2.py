"""Tests Sprint 2 du connecteur ERPNext : factures, lignes, articles."""
from datetime import date
from decimal import Decimal

import pytest

from hub.connectors.erpnext import ERPNextConnector


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"data": self._data}


@pytest.fixture
def connector():
    return ERPNextConnector("http://erpnext.local", "key", "secret", page_size=2)


INVOICE = {
    "name": "ACC-SINV-2026-00001",
    "customer": "Grant Plastics Ltd.",
    "is_return": 0,
    "posting_date": "2026-09-01",
    "due_date": "2026-10-01",
    "status": "Unpaid",
    "currency": "CHF",
    "net_total": 1000.0,
    "grand_total": 1081.0,
    "modified": "2026-09-02 10:30:00.123456",
}

CREDIT_NOTE = {**INVOICE, "name": "ACC-SINV-2026-00002", "is_return": 1,
               "net_total": -100.0, "grand_total": -108.1, "status": "Return"}

LINE = {
    "name": "abc123def4",
    "item_code": "SKU001",
    "item_name": "T-shirt",
    "description": "T-shirt blanc",
    "qty": 2.0,
    "rate": 500.0,
    "amount": 1000.0,
    "modified": "2026-09-02 10:30:00",
}


def test_normalize_invoice(connector):
    inv = connector.normalize_invoice(INVOICE)
    assert inv.source == "erpnext"
    assert inv.source_id == "ACC-SINV-2026-00001"
    assert inv.customer_source_id == "Grant Plastics Ltd."
    assert inv.doc_type == "invoice"
    assert inv.invoice_date == date(2026, 9, 1)
    assert inv.due_date == date(2026, 10, 1)
    assert inv.status == "Unpaid"
    assert inv.currency == "CHF"
    assert inv.total_excl_tax == Decimal("1000.0")
    assert inv.total_incl_tax == Decimal("1081.0")
    assert inv.source_modified_at is not None
    assert inv.payload == INVOICE


def test_credit_note_is_detected(connector):
    inv = connector.normalize_invoice(CREDIT_NOTE)
    assert inv.doc_type == "credit_note"
    assert inv.total_excl_tax == Decimal("-100.0")


def test_empty_due_date_becomes_none(connector):
    inv = connector.normalize_invoice({**INVOICE, "due_date": None})
    assert inv.due_date is None


def test_normalize_invoice_line(connector):
    line = connector.normalize_invoice_line({**LINE, "_invoice_id": "ACC-SINV-2026-00001"})
    assert line.source_id == "abc123def4"
    assert line.invoice_source_id == "ACC-SINV-2026-00001"
    assert line.product_source_id == "SKU001"
    assert line.description == "T-shirt blanc"
    assert line.quantity == Decimal("2.0")
    assert line.unit_price == Decimal("500.0")
    assert line.total_excl_tax == Decimal("1000.0")


def test_line_without_description_falls_back_to_item_name(connector):
    rec = {**LINE, "description": "", "_invoice_id": "X"}
    assert connector.normalize_invoice_line(rec).description == "T-shirt"


def test_line_without_item_code(connector):
    rec = {**LINE, "item_code": None, "_invoice_id": "X"}
    assert connector.normalize_invoice_line(rec).product_source_id is None


def test_normalize_item(connector):
    item = connector.normalize_item({
        "name": "SKU001", "item_code": "SKU001", "item_name": "T-shirt",
        "item_group": "Products", "standard_rate": 500.0,
        "is_sales_item": 1, "disabled": 0, "modified": "2026-09-02 10:30:00",
    })
    assert item.source_id == "SKU001"
    assert item.code == "SKU001"
    assert item.category == "Products"
    assert item.sale_price == Decimal("500.0")
    assert item.is_sellable is True


@pytest.mark.parametrize("sales,disabled,expected", [
    (1, 0, True), (0, 0, False), (1, 1, False), (0, 1, False),
])
def test_item_sellable_logic(connector, sales, disabled, expected):
    item = connector.normalize_item({
        "name": "S", "item_code": "S", "item_name": "S",
        "is_sales_item": sales, "disabled": disabled,
    })
    assert item.is_sellable is expected


def test_list_paginates_until_short_page(connector, monkeypatch):
    pages = [[{"name": "A"}, {"name": "B"}], [{"name": "C"}]]
    calls = []

    def fake_get(path, **params):
        calls.append((path, params["limit_start"]))
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(connector, "_get", fake_get)
    result = connector.fetch_invoices()
    assert [r["name"] for r in result] == ["A", "B", "C"]
    assert calls == [("/api/resource/Sales%20Invoice", 0),
                     ("/api/resource/Sales%20Invoice", 2)]


def test_list_empty(connector, monkeypatch):
    monkeypatch.setattr(connector, "_get", lambda path, **p: FakeResponse([]))
    assert connector.fetch_items() == []


def test_fetch_invoice_lines_reads_each_document(connector, monkeypatch):
    paths = []

    def fake_get(path, **params):
        paths.append(path)
        return FakeResponse({"name": "ACC-SINV-2026-00001",
                             "modified": "2026-09-02 10:30:00",
                             "items": [dict(LINE), {**LINE, "name": "zzz999"}]})

    monkeypatch.setattr(connector, "_get", fake_get)
    lines = connector.fetch_invoice_lines([INVOICE])
    assert paths == ["/api/resource/Sales%20Invoice/ACC-SINV-2026-00001"]
    assert len(lines) == 2
    assert all(l["_invoice_id"] == "ACC-SINV-2026-00001" for l in lines)


def test_fetch_invoice_lines_without_lines(connector, monkeypatch):
    monkeypatch.setattr(connector, "_get",
                        lambda path, **p: FakeResponse({"name": "X", "items": []}))
    assert connector.fetch_invoice_lines([INVOICE]) == []