"""Exploration en lecture seule de l'API REST Dolibarr (ne modifie rien)."""
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


# 1. La clé est-elle acceptée ?
r = get("status")
print("Réponse status :", r.text[:200])

# 2. Tous les tiers (limit large pour tout récupérer)
r = get("thirdparties", limit=100)
if r.status_code != 200:
    raise SystemExit(f"Échec : {r.text[:300]}")
tiers = r.json()
print(f"\nNombre de tiers reçus : {len(tiers)}")

# 3. Les champs disponibles sur le premier tiers
print("\nChamps du premier tiers :")
for k in sorted(tiers[0]):
    print(f"  {k}")

# 4. Répartition de la nature (client / fournisseur)
print("\nValeurs du champ 'client' :", dict(Counter(t.get("client") for t in tiers)))
print("Valeurs du champ 'fournisseur' :", dict(Counter(t.get("fournisseur") for t in tiers)))

# 5. Aperçu de 3 tiers (champs utiles seulement)
print("\nAperçu :")
for t in tiers[:3]:
    print({k: t.get(k) for k in ("id", "name", "email", "phone", "town", "zip", "country", "client")})