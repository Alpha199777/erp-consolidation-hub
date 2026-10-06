from datetime import date, datetime, timezone
from decimal import Decimal

import requests

from hub.connectors.dolibarr import DolibarrConnector

# Enregistrements reels lus dans ton Dolibarr
LINE = {
    "id": "2108", "fk_product": None, "desc": "P1", "qty": "2",
    "subprice": "10.00000000", "total_ht": "19.00000000",
    "date_modification": None,
}

INVOICE = {
    "id": "476", "ref": "FA2606-0001", "socid": "59", "type": "0",
    "statut": "1", "paye": "0", "date": 1780358400,
    "date_lim_reglement": 1780358400, "total_ht": "29.00000000",
    "total_ttc": "34.80000000", "multicurrency_code": "EUR",
    "date_modification": 1780417344, "lines": [LINE],
}

PRODUCT = {
    "id": "1", "ref": "PINKDRESS", "label": "Pink dress", "price": "9.00000000",
    "status": "1", "date_modification": 1742384079,
}


def make_connector(page_size=100):
    return DolibarrConnector("http://localhost:8081", "key", page_size=page_size)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def fake_get_factory(pages):
    """pages : {numero_de_page: (code_http, liste)} ; une page absente = 404."""
    calls = []

    def fake_get(path, **params):
        calls.append((path, params["page"]))
        status, batch = pages.get(params["page"], (404, []))
        return FakeResponse(status, batch)

    return fake_get, calls


# ---------- normalize_invoice ----------
def test_normalize_invoice_real_record():
    inv = make_connector().normalize_invoice(INVOICE)
    assert inv.source == "dolibarr"
    assert inv.source_id == "476"
    assert inv.number == "FA2606-0001"
    assert inv.customer_source_id == "59"
    assert inv.doc_type == "invoice"
    assert inv.invoice_date == date(2026, 6, 2)
    assert inv.due_date == date(2026, 6, 2)
    assert inv.status == "validated/unpaid"
    assert inv.currency == "EUR"
    assert inv.total_excl_tax == Decimal("29")
    assert inv.total_incl_tax == Decimal("34.8")
    assert inv.source_modified_at == datetime(2026, 6, 2, 16, 22, 24, tzinfo=timezone.utc)
    assert inv.payload is INVOICE


def test_normalize_invoice_paid_status():
    inv = make_connector().normalize_invoice({**INVOICE, "statut": "2", "paye": "1"})
    assert inv.status == "closed/paid"


def test_normalize_invoice_credit_note():
    # Cas limite invente : ton Dolibarr n'a aucun avoir
    inv = make_connector().normalize_invoice({**INVOICE, "type": "2"})
    assert inv.doc_type == "credit_note"


def test_normalize_invoice_empty_customer():
    # Cas limite invente
    inv = make_connector().normalize_invoice({**INVOICE, "socid": None})
    assert inv.customer_source_id is None


# ---------- normalize_invoice_line ----------
def test_normalize_invoice_line_free_text_line():
    record = {**LINE, "_invoice_id": "476"}
    line = make_connector().normalize_invoice_line(record)
    assert line.source_id == "2108"
    assert line.invoice_source_id == "476"
    assert line.product_source_id is None
    assert line.description == "P1"
    assert line.quantity == Decimal("2")
    assert line.unit_price == Decimal("10")
    assert line.total_excl_tax == Decimal("19")


def test_normalize_invoice_line_with_and_without_product():
    conn = make_connector()
    with_product = conn.normalize_invoice_line({**LINE, "_invoice_id": "476", "fk_product": "12"})
    zero_product = conn.normalize_invoice_line({**LINE, "_invoice_id": "476", "fk_product": "0"})
    assert with_product.product_source_id == "12"
    assert zero_product.product_source_id is None


# ---------- normalize_item ----------
def test_normalize_item_real_record():
    item = make_connector().normalize_item(PRODUCT)
    assert item.source_id == "1"
    assert item.code == "PINKDRESS"
    assert item.name == "Pink dress"
    assert item.category is None
    assert item.sale_price == Decimal("9")
    assert item.is_sellable is True
    assert item.source_modified_at.date() == date(2025, 3, 19)
    assert item.source_modified_at.tzinfo is not None


def test_normalize_item_not_for_sale():
    item = make_connector().normalize_item({**PRODUCT, "status": "0"})
    assert item.is_sellable is False


# ---------- fetch ----------
def test_fetch_invoices_reads_every_page(monkeypatch):
    conn = make_connector(page_size=2)
    fake_get, calls = fake_get_factory({
        0: (200, [{"id": "1"}, {"id": "2"}]),
        1: (200, [{"id": "3"}]),  # page incomplete : fin des donnees
    })
    monkeypatch.setattr(conn, "_get", fake_get)
    assert [r["id"] for r in conn.fetch_invoices()] == ["1", "2", "3"]
    assert calls == [("invoices", 0), ("invoices", 1)]


def test_fetch_invoices_stops_on_404_page(monkeypatch):
    conn = make_connector(page_size=2)
    fake_get, calls = fake_get_factory({0: (200, [{"id": "1"}, {"id": "2"}])})
    monkeypatch.setattr(conn, "_get", fake_get)
    assert len(conn.fetch_invoices()) == 2
    assert calls == [("invoices", 0), ("invoices", 1)]  # la page 1 repond 404


def test_fetch_invoice_lines_from_given_invoices_makes_no_http_call(monkeypatch):
    conn = make_connector()

    def forbidden(*args, **kwargs):
        raise AssertionError("aucun appel reseau attendu")

    monkeypatch.setattr(conn, "_get", forbidden)
    lines = conn.fetch_invoice_lines([INVOICE])
    assert len(lines) == 1
    assert lines[0]["id"] == "2108"
    assert lines[0]["_invoice_id"] == "476"
    assert "_invoice_id" not in LINE  # l'original n'est pas modifie


def test_fetch_invoice_lines_without_argument_reads_invoices(monkeypatch):
    conn = make_connector()
    monkeypatch.setattr(conn, "fetch_invoices", lambda: [INVOICE])
    assert conn.fetch_invoice_lines()[0]["_invoice_id"] == "476"


def test_fetch_items_uses_products_endpoint(monkeypatch):
    conn = make_connector(page_size=2)
    fake_get, calls = fake_get_factory({0: (200, [PRODUCT])})
    monkeypatch.setattr(conn, "_get", fake_get)
    assert conn.fetch_items() == [PRODUCT]
    assert calls[0][0] == "products"