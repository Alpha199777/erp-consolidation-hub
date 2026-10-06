"""Exploration Dolibarr : factures clients et produits (lecture seule)."""
import os
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("DOLIBARR_URL")
KEY = os.getenv("DOLIBARR_API_KEY")

if not URL or not KEY:
    raise SystemExit("DOLIBARR_URL ou DOLIBARR_API_KEY manquant dans .env")

HEADERS = {"DOLAPIKEY": KEY, "Accept": "application/json"}
BASE = f"{URL}/api/index.php"


def get(path, **params):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, params=params, timeout=15)
    print(f"GET {path} {params} -> HTTP {r.status_code}")
    return r


def get_all(path, page_size=100):
    """Parcourt toutes les pages. Une page vide renvoie 404 chez Dolibarr."""
    rows, page = [], 0
    while True:
        r = get(path, limit=page_size, page=page, sortfield="t.rowid", sortorder="ASC")
        if r.status_code == 404:
            break
        if r.status_code != 200:
            raise SystemExit(f"Echec : {r.text[:300]}")
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return rows


def show_fields(title, record, wanted):
    print(f"\n{title} : tous les champs disponibles")
    for k in sorted(record):
        print(f"  {k}")
    print(f"\n{title} : champs qui nous interessent (None = absent ou vide)")
    for k in wanted:
        print(f"  {k:22} -> {record.get(k)!r}")


# ---------- Factures clients ----------
print("=== FACTURES (invoices) ===")
invoices = get_all("invoices")
print(f"\nNombre de factures recues : {len(invoices)}")
if invoices:
    print("Repartition par type  (0 = facture, 2 = avoir) :",
          dict(Counter(i.get("type") for i in invoices)))
    print("Repartition par statut :",
          dict(Counter(i.get("statut", i.get("status")) for i in invoices)))
    print("Repartition par devise :",
          dict(Counter(i.get("multicurrency_code") for i in invoices)))
    print("Lignes presentes dans la liste ?", "lines" in invoices[0])
    show_fields("Facture", invoices[0], [
        "id", "ref", "socid", "type", "statut", "status", "paye", "date",
        "date_lim_reglement", "total_ht", "total_tva", "total_ttc",
        "multicurrency_code", "date_creation", "date_modification", "tms",
    ])
    lines = invoices[0].get("lines") or []
    print(f"\nNombre de lignes sur la premiere facture : {len(lines)}")
    if lines:
        show_fields("Ligne", lines[0], [
            "id", "fk_product", "product_ref", "product_label", "desc",
            "qty", "subprice", "total_ht", "total_ttc", "product_type",
        ])

# ---------- Produits ----------
print("\n\n=== PRODUITS (products) ===")
products = get_all("products")
print(f"\nNombre de produits recus : {len(products)}")
if products:
    print("Repartition par type (0 = produit, 1 = service) :",
          dict(Counter(p.get("type") for p in products)))
    print("A vendre (status) :", dict(Counter(p.get("status") for p in products)))
    show_fields("Produit", products[0], [
        "id", "ref", "label", "description", "price", "price_ttc",
        "cost_price", "pmp", "type", "status", "status_buy", "tosell",
        "date_creation", "date_modification", "tms",
    ])