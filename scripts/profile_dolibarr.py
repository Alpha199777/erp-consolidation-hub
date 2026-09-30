"""Profil des données Dolibarr : champs remplis, statuts, natures (lecture seule)."""
import os
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("DOLIBARR_URL")
KEY = os.getenv("DOLIBARR_API_KEY")
if not URL or not KEY:
    raise SystemExit("DOLIBARR_URL ou DOLIBARR_API_KEY manquant dans .env")

r = requests.get(
    f"{URL}/api/index.php/thirdparties",
    headers={"DOLAPIKEY": KEY, "Accept": "application/json"},
    params={"limit": 100},
    timeout=15,
)
r.raise_for_status()
tiers = r.json()
print(f"{len(tiers)} tiers reçus\n")

VIDES = (None, "", 0, "0", False)

print("Champs remplis (sur le total) :")
for champ in ("email", "phone", "phone_mobile", "address", "town", "zip",
              "country_code", "country_id"):
    n = sum(1 for t in tiers if t.get(champ) not in VIDES)
    print(f"  {champ:<14} {n}/{len(tiers)}")

print("\nValeurs de country_code :", dict(Counter(t.get("country_code") for t in tiers)))
print("Valeurs de status :", dict(Counter(t.get("status") for t in tiers)))
print("Croisement (client, status) :",
      dict(Counter((t.get("client"), t.get("status")) for t in tiers)))

print("\nTiers dont status n'est pas '1' :")
for t in tiers:
    if t.get("status") != "1":
        print(f"  id={t.get('id')} name={t.get('name')} client={t.get('client')} status={t.get('status')}")