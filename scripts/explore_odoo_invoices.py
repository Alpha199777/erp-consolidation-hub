"""Exploration Odoo : factures clients et articles (lecture seule)."""
import os
import xmlrpc.client
from dotenv import load_dotenv

load_dotenv()
URL = os.environ["ODOO_URL"]
DB = os.environ["ODOO_DB"]
USER = os.environ["ODOO_USER"]
PWD = os.environ["ODOO_PASSWORD"]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, PWD, {})
print("Authentification, uid =", uid)

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kwargs)


def existing(model, names):
    """Retourne seulement les champs qui existent vraiment sur ce modele."""
    fields = call(model, "fields_get", attributes=["string", "type"])
    print(f"\nChamps de {model} (None = absent dans cette base) :")
    for name in names:
        print(f"  {name:20} -> {fields.get(name)}")
    return [n for n in names if n in fields]


# ---------- Factures clients : modele account.move ----------
print("\n=== FACTURES CLIENTS (account.move) ===")
print("Factures clients (out_invoice) :",
      call("account.move", "search_count", [["move_type", "=", "out_invoice"]]))
print("Avoirs clients (out_refund)    :",
      call("account.move", "search_count", [["move_type", "=", "out_refund"]]))
for state in ["draft", "posted", "cancel"]:
    n = call("account.move", "search_count",
             [["move_type", "=", "out_invoice"], ["state", "=", state]])
    print(f"  statut {state:7} : {n}")

inv_fields = existing("account.move", [
    "name", "partner_id", "invoice_date", "invoice_date_due", "state",
    "payment_state", "amount_untaxed", "amount_total", "currency_id",
    "invoice_line_ids", "create_date", "write_date",
])
print("\nExemple de 2 factures clients :")
for row in call("account.move", "search_read", [["move_type", "=", "out_invoice"]],
                fields=inv_fields, limit=2):
    print(row)

# ---------- Lignes de facture : modele account.move.line ----------
print("\n=== LIGNES DE FACTURE (account.move.line) ===")
line_domain = [["move_id.move_type", "=", "out_invoice"], ["display_type", "=", "product"]]
print("Lignes produit des factures clients :",
      call("account.move.line", "search_count", line_domain))
line_fields = existing("account.move.line", [
    "move_id", "product_id", "name", "quantity", "price_unit",
    "price_subtotal", "price_total", "write_date",
])
print("\nExemple de 2 lignes :")
for row in call("account.move.line", "search_read", line_domain,
                fields=line_fields, limit=2):
    print(row)

# ---------- Articles : modele product.template ----------
print("\n=== ARTICLES (product.template) ===")
print("Articles actifs      :", call("product.template", "search_count", []))
print("Articles vendables   :", call("product.template", "search_count",
                                     [["sale_ok", "=", True]]))
prod_fields = existing("product.template", [
    "name", "default_code", "list_price", "standard_price", "type",
    "categ_id", "sale_ok", "active", "write_date",
])
print("\nExemple de 3 articles :")
for row in call("product.template", "search_read", [], fields=prod_fields, limit=3):
    print(row)