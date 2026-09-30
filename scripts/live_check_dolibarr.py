"""Contrôle en réel du connecteur Dolibarr (lecture seule, n'affiche pas la clé)."""
import os

from dotenv import load_dotenv

from hub.connectors.dolibarr import DolibarrConnector

load_dotenv()

c = DolibarrConnector.from_env()
if c is None:
    raise SystemExit("Variables DOLIBARR_* absentes de .env")

# 1. ping avec la bonne clé, puis avec une mauvaise
print("ping (bonne clé)    :", c.ping())
mauvais = DolibarrConnector(os.getenv("DOLIBARR_URL"), "mauvaise-cle")
print("ping (mauvaise clé) :", mauvais.ping(), " <- doit être False")

# 2. même résultat quelle que soit la taille de page
resultats = {}
for taille in (100, 10, 5):
    c.page_size = taille
    ids = [r["id"] for r in c.fetch_customers()]
    resultats[taille] = ids
    print(f"page_size={taille:<3} -> {len(ids)} clients, {len(set(ids))} ids distincts")

memes = sorted(resultats[100]) == sorted(resultats[10]) == sorted(resultats[5])
print("Mêmes ids avec les 3 tailles :", memes)

# 3. comportement d'une page vide (très loin après la fin)
r = c._get("thirdparties", limit=5, page=99, sortfield="t.rowid", sortorder="ASC")
print("Page vide -> HTTP", r.status_code)

# 4. aperçu de la normalisation
c.page_size = 100
clients = c.fetch_customers()
print("\nAperçu normalisé :")
for rec in clients[:3]:
    print(c.normalize(rec))