"""Exploration ERPNext : factures de vente et articles (lecture seule)."""
import json
import os
from collections import Counter
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("ERPNEXT_URL")
KEY = os.getenv("ERPNEXT_API_KEY")
SECRET = os.getenv("ERPNEXT_API_SECRET")

if not (URL and KEY and SECRET):
    raise SystemExit("ERPNEXT_URL, ERPNEXT_API_KEY ou ERPNEXT_API_SECRET manquant dans .env")

HEADERS = {"Authorization": f"token {KEY}:{SECRET}", "Accept": "application/json"}


def get(path, **params):
    r = requests.get(f"{URL}{path}", headers=HEADERS, params=params, timeout=15)
    print(f"GET {path} -> HTTP {r.status_code}")
    return r


def get_all(doctype, page_size=100):
    """Liste complète d'un doctype, avec tous les champs de l'en-tête."""
    path = f"/api/resource/{quote(doctype)}"
    rows, start = [], 0
    while True:
        r = get(path, fields=json.dumps(["*"]), limit_start=start,
                limit_page_length=page_size, order_by="name asc")
        if r.status_code != 200:
            raise SystemExit(f"Echec : {r.text[:300]}")
        batch = r.json()["data"]
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def show_fields(title, record, wanted):
    print(f"\n{title} : tous les champs disponibles")
    for k in sorted(record):
        print(f"  {k}")
    print(f"\n{title} : champs qui nous interessent (None = absent ou vide)")
    for k in wanted:
        print(f"  {k:22} -> {record.get(k)!r}")


# ---------- Factures de vente ----------
print("=== FACTURES DE VENTE (Sales Invoice) ===")
invoices = get_all("Sales Invoice")
print(f"\nNombre de factures recues : {len(invoices)}")
if invoices:
    print("Repartition par statut      :", dict(Counter(i.get("status") for i in invoices)))
    print("Repartition par docstatus   :", dict(Counter(i.get("docstatus") for i in invoices)),
          "(0 brouillon, 1 validee, 2 annulee)")
    print("Factures de retour (avoirs) :", dict(Counter(i.get("is_return") for i in invoices)))
    print("Repartition par devise      :", dict(Counter(i.get("currency") for i in invoices)))
    show_fields("Facture", invoices[0], [
        "name", "customer", "customer_name", "posting_date", "due_date",
        "status", "docstatus", "is_return", "return_against", "currency",
        "net_total", "total", "grand_total", "base_grand_total",
        "outstanding_amount", "company", "creation", "modified",
    ])

    # Les lignes ne sont visibles qu'en ouvrant chaque facture
    print("\n--- Ouverture individuelle des factures pour voir les lignes ---")
    total_lignes = 0
    premiere = None
    for inv in invoices:
        r = get(f"/api/resource/{quote('Sales Invoice')}/{quote(inv['name'])}")
        if r.status_code != 200:
            print("  echec :", r.text[:200])
            continue
        doc = r.json()["data"]
        items = doc.get("items") or []
        total_lignes += len(items)
        print(f"  {inv['name']} : {len(items)} ligne(s)")
        if premiere is None and items:
            premiere = items[0]
    print(f"Total de lignes sur les factures : {total_lignes}")
    if premiere:
        show_fields("Ligne", premiere, [
            "name", "idx", "parent", "item_code", "item_name", "description",
            "qty", "uom", "rate", "amount", "net_amount", "modified",
        ])

# ---------- Articles ----------
print("\n\n=== ARTICLES (Item) ===")
items = get_all("Item")
print(f"\nNombre d'articles recus : {len(items)}")
if items:
    print("Desactives (disabled) :", dict(Counter(i.get("disabled") for i in items)))
    print("Vendables (is_sales_item) :", dict(Counter(i.get("is_sales_item") for i in items)))
    print("Groupes d'articles :", dict(Counter(i.get("item_group") for i in items)))
    show_fields("Article", items[0], [
        "name", "item_code", "item_name", "item_group", "description",
        "stock_uom", "standard_rate", "valuation_rate", "is_stock_item",
        "is_sales_item", "disabled", "creation", "modified",
    ])