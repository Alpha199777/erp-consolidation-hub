"""Contrôle en réel du connecteur ERPNext (lecture seule, n'affiche aucune clé)."""
import json
import os
from dataclasses import asdict

from dotenv import load_dotenv

from hub.connectors.erpnext import ERPNextConnector

load_dotenv()

c = ERPNextConnector.from_env()
if c is None:
    raise SystemExit("Variables ERPNEXT_* absentes de .env")

# 1. ping avec les bons identifiants, puis avec un faux secret
print("ping (bons identifiants) :", c.ping())
faux = ERPNextConnector(os.getenv("ERPNEXT_URL"), os.getenv("ERPNEXT_API_KEY"), "faux-secret")
print("ping (faux secret)       :", faux.ping(), " <- doit être False")

# 2. même résultat quelle que soit la taille de page
resultats = {}
for taille in (100, 3, 2, 1):
    c.page_size = taille
    ids = [r["name"] for r in c.fetch_customers()]
    resultats[taille] = ids
    print(f"page_size={taille:<3} -> {len(ids)} clients, {len(set(ids))} ids distincts")

memes = all(sorted(v) == sorted(resultats[100]) for v in resultats.values())
print("Mêmes ids avec toutes les tailles :", memes)

# 3. comportement d'une page vide (au-delà de la fin)
r = c._get("/api/resource/Customer", fields=json.dumps(["name"]),
           limit_start=99, limit_page_length=3, order_by="name asc")
print("Page vide -> HTTP", r.status_code, "|", r.text[:80])

# 4. aperçu de la normalisation (sans le payload, trop long)
c.page_size = 100
print("\nAperçu normalisé :")
for rec in c.fetch_customers():
    d = asdict(c.normalize(rec))
    d.pop("payload")
    print(d)