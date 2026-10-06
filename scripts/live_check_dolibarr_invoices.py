"""Verification reelle (lecture seule) du connecteur Dolibarr : factures, lignes, articles."""
from collections import Counter

from dotenv import load_dotenv

from hub.connectors.dolibarr import DolibarrConnector

load_dotenv()
conn = DolibarrConnector.from_env()
if conn is None:
    raise SystemExit("Variables DOLIBARR_* manquantes dans .env")

print("ping :", conn.ping())

raw_invoices = conn.fetch_invoices()
invoices = [conn.normalize_invoice(r) for r in raw_invoices]
lines = [conn.normalize_invoice_line(r) for r in conn.fetch_invoice_lines(raw_invoices)]
items = [conn.normalize_item(r) for r in conn.fetch_items()]
customers = [conn.normalize(r) for r in conn.fetch_customers()]

print(f"\nFactures : {len(invoices)}", dict(Counter(i.doc_type for i in invoices)))
print("Statuts  :", dict(Counter(i.status for i in invoices)))
print(f"Lignes   : {len(lines)} (dont sans produit : "
      f"{sum(1 for l in lines if l.product_source_id is None)})")
print(f"Articles : {len(items)}")
print(f"Clients  : {len(customers)}")

invoice_ids = {i.source_id for i in invoices}
item_ids = {i.source_id for i in items}
customer_ids = {c.source_id for c in customers}

orphan_lines = [l.source_id for l in lines if l.invoice_source_id not in invoice_ids]
unknown_products = sorted(
    {l.product_source_id for l in lines
     if l.product_source_id and l.product_source_id not in item_ids}
)
unknown_customers = sorted(
    {i.customer_source_id for i in invoices
     if i.customer_source_id and i.customer_source_id not in customer_ids}
)

print("\n--- Verification des liens ---")
print("Lignes sans facture connue           :", orphan_lines or "aucune")
print("Produits de lignes absents des items :", unknown_products or "aucun")
print("Clients de factures absents de raw   :", unknown_customers or "aucun")

print("\nExemple de facture normalisee :")
print(invoices[0])
print("\nExemple de ligne normalisee :")
print(lines[0])
print("\nExemple d'article normalise :")
print(items[0])