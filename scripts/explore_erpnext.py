"""Exploration en lecture seule de l'API REST ERPNext (ne modifie rien)."""
import json
import os
from collections import Counter

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


# 1. Le serveur répond-il ? (public)
r = get("/api/method/ping")
print("  ping :", r.text[:100])

# 2. La clé et le secret sont-ils acceptés ?
r = get("/api/method/frappe.auth.get_logged_user")
print("  utilisateur connecté :", r.text[:100])
if r.status_code != 200:
    raise SystemExit("Authentification refusée : vérifie la clé et le secret dans .env")

# 3. Les clients (tous les champs)
r = get("/api/resource/Customer", fields=json.dumps(["*"]), limit_page_length=100)
if r.status_code != 200:
    raise SystemExit(f"Échec : {r.text[:300]}")
clients = r.json()["data"]
print(f"\nNombre de clients reçus : {len(clients)}")

print("\nChamps du premier client :")
for k in sorted(clients[0]):
    print(f"  {k}")

# 4. Champs remplis
VIDES = (None, "", 0, "0", False)
print("\nChamps remplis (sur le total) :")
for champ in ("customer_name", "email_id", "mobile_no", "primary_address",
              "customer_type", "customer_group", "territory", "tax_id"):
    n = sum(1 for c in clients if c.get(champ) not in VIDES)
    print(f"  {champ:<16} {n}/{len(clients)}")

print("\nValeurs de disabled :", dict(Counter(c.get("disabled") for c in clients)))
print("Valeurs de customer_type :", dict(Counter(c.get("customer_type") for c in clients)))

# 5. Aperçu
print("\nAperçu :")
for c in clients[:3]:
    print({k: c.get(k) for k in ("name", "customer_name", "email_id", "mobile_no",
                                 "customer_type", "disabled", "modified")})