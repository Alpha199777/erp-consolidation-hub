"""Exploration ERPNext : adresses des clients (LECTURE SEULE).

Objectif : voir comment ville, code postal et pays sont stockes dans le
doctype Address, et comment une adresse est liee a un Customer, AVANT
d'ecrire l'enrichissement dans le connecteur.

Lancement (depuis la racine du projet) :
    python scripts/explore_erpnext_addresses.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RACINE / ".env")

from hub.connectors.erpnext import ERPNextConnector  # noqa: E402


def titre(texte: str) -> None:
    print()
    print("=" * 70)
    print(texte)
    print("=" * 70)


def essayer(libelle: str, fonction):
    try:
        return fonction()
    except Exception as exc:  # noqa: BLE001
        print(f"  ERREUR sur {libelle} : {type(exc).__name__}: {exc}")
        return None


def lire_adresse(connecteur, nom: str) -> dict:
    """Lit UNE adresse complete (la liste ne contient pas la table enfant 'links')."""
    reponse = connecteur._get(f"/api/resource/{quote('Address')}/{quote(nom)}")
    reponse.raise_for_status()
    return reponse.json().get("data", {})


def liens_clients(adresse: dict) -> list[str]:
    """Noms des Customer lies a cette adresse (table enfant 'links')."""
    return [
        str(lien.get("link_name"))
        for lien in adresse.get("links", []) or []
        if lien.get("link_doctype") == "Customer"
    ]


def main() -> None:
    titre("0. Connexion")
    connecteur = essayer("from_env()", ERPNextConnector.from_env)
    if connecteur is None:
        print("  Connecteur ERPNext indisponible (variables .env manquantes ?).")
        return
    print(f"  ping() -> {essayer('ping', connecteur.ping)}")

    # ------------------------------------------------------------ adresses
    titre("1. Adresses (liste)")
    liste = essayer("liste des Address", lambda: connecteur._list("Address"))
    liste = liste or []
    print(f"  Nombre d'adresses : {len(liste)}")
    if liste:
        print(f"  Champs de la liste (1re adresse) : {sorted(liste[0].keys())}")
        print(f"  'links' present dans la liste ? {'links' in liste[0]}")

    titre("2. Adresses (detail, une lecture par adresse)")
    adresses: list[dict] = []
    for brut in liste:
        nom = str(brut.get("name"))
        detail = essayer(f"adresse {nom}", lambda nom=nom: lire_adresse(connecteur, nom))
        if detail is not None:
            adresses.append(detail)
    print(f"  Adresses lues en detail : {len(adresses)} / {len(liste)}")

    for a in adresses:
        print(
            f"   - {a.get('name')} | type={a.get('address_type')} | "
            f"ligne1={a.get('address_line1')!r} | ville={a.get('city')!r} | "
            f"cp={a.get('pincode')!r} | pays={a.get('country')!r}"
        )
        print(
            f"       principale={a.get('is_primary_address')} | "
            f"livraison={a.get('is_shipping_address')} | desactivee={a.get('disabled')} | "
            f"liens={[(l.get('link_doctype'), l.get('link_name')) for l in a.get('links', []) or []]}"
        )

    # ------------------------------------------------------------- clients
    titre("3. Clients et leurs adresses")
    clients = essayer("fetch_customers", connecteur.fetch_customers) or []
    print(f"  Nombre de clients : {len(clients)}")
    if clients:
        cles = sorted(clients[0].keys())
        pertinentes = [c for c in cles if "address" in c or "contact" in c]
        print(f"  Champs du Customer lies aux adresses : {pertinentes}")

    par_client: dict[str, list[dict]] = defaultdict(list)
    for a in adresses:
        for nom_client in liens_clients(a):
            par_client[nom_client].append(a)

    for c in clients:
        nom = str(c.get("name"))
        adrs = par_client.get(nom, [])
        principale = c.get("customer_primary_address")
        print(
            f"   - {nom} | customer_primary_address={principale!r} | "
            f"adresses liees={len(adrs)}"
        )
        for a in adrs:
            marque = " <- principale du client" if a.get("name") == principale else ""
            print(
                f"       {a.get('name')} : ville={a.get('city')!r} "
                f"cp={a.get('pincode')!r} pays={a.get('country')!r}{marque}"
            )

    # ------------------------------------------------------------- synthese
    titre("4. Synthese")
    noms_clients = {str(c.get("name")) for c in clients}
    sans_adresse = sorted(noms_clients - set(par_client))
    plusieurs = sorted(n for n, adrs in par_client.items() if len(adrs) > 1)
    liees_autre = [
        a.get("name")
        for a in adresses
        if not liens_clients(a) and (a.get("links") or [])
    ]
    sans_lien = [a.get("name") for a in adresses if not (a.get("links") or [])]
    principale_hors_liens = [
        str(c.get("name"))
        for c in clients
        if c.get("customer_primary_address")
        and c.get("customer_primary_address")
        not in {a.get("name") for a in par_client.get(str(c.get("name")), [])}
    ]

    print(f"  Clients sans aucune adresse                 : {len(sans_adresse)} {sans_adresse[:10]}")
    print(f"  Clients avec plusieurs adresses             : {len(plusieurs)} {plusieurs[:10]}")
    print(f"  Adresses liees a autre chose qu'un Customer : {len(liees_autre)} {liees_autre[:10]}")
    print(f"  Adresses sans aucun lien                    : {len(sans_lien)} {sans_lien[:10]}")
    print(f"  Clients dont l'adresse principale n'est pas dans leurs liens : {len(principale_hors_liens)} {principale_hors_liens[:10]}")
    print(f"  Valeurs distinctes de 'country'             : {dict(Counter(str(a.get('country')) for a in adresses))}")
    print(f"  Adresses sans ville                         : {sum(1 for a in adresses if not a.get('city'))}")
    print(f"  Adresses sans code postal                   : {sum(1 for a in adresses if not a.get('pincode'))}")

    titre("FIN : lecture seule, rien n'a ete ecrit")


if __name__ == "__main__":
    main()