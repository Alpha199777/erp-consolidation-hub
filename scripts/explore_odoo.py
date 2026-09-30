"""Exploration de l'API XML-RPC d'Odoo (lecture seule)."""
import os
import xmlrpc.client
from dotenv import load_dotenv

load_dotenv()
URL = os.environ["ODOO_URL"]
DB = os.environ["ODOO_DB"]
USER = os.environ["ODOO_USER"]
PWD = os.environ["ODOO_PASSWORD"]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
print("Version Odoo :", common.version()["server_version"])

uid = common.authenticate(DB, USER, PWD, {})
print("Authentification, uid =", uid)

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kwargs)


print("Partenaires au total :", call("res.partner", "search_count", []))
print("Dont societes        :", call("res.partner", "search_count", [["is_company", "=", True]]))

fields = call("res.partner", "fields_get", attributes=["string", "type"])
print("\nChamps utiles (None = absent dans cette base) :")
for name in ["name", "email", "phone", "city", "zip", "country_id",
             "is_company", "parent_id", "customer_rank", "write_date"]:
    print(f"  {name:14} -> {fields.get(name)}")

print("\nExemple de 2 societes :")
rows = call("res.partner", "search_read", [["is_company", "=", True]],
            fields=["name", "email", "phone", "city", "zip", "country_id", "write_date"],
            limit=2)
for row in rows:
    print(row)