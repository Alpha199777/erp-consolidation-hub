"""Exploration Sprint 2 etape 5 : filtres par date de modification (LECTURE SEULE).

Objectif : voir si chaque ERP sait ne renvoyer que les enregistrements modifies
apres une date, et sous quelle forme, AVANT d'ecrire la synchronisation
incrementale.

Lancement (depuis la racine du projet) :
    python scripts/explore_incremental.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RACINE / ".env")

from hub.connectors.dolibarr import DolibarrConnector  # noqa: E402
from hub.connectors.erpnext import ERPNextConnector  # noqa: E402
from hub.connectors.odoo import MOVE_TYPES, OdooConnector  # noqa: E402

FORMAT = "%Y-%m-%d %H:%M:%S"


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


# ------------------------------------------------------------------- Odoo
def odoo(c: OdooConnector) -> None:
    cibles = (
        ("clients", "res.partner", [["is_company", "=", True]]),
        ("factures", "account.move", [["move_type", "in", MOVE_TYPES]]),
        ("articles", "product.product", []),
    )
    for libelle, modele, domaine in cibles:
        lignes = essayer(
            f"lecture {modele}",
            lambda m=modele, d=domaine: c._call(m, "search_read", d, fields=["write_date"]),
        ) or []
        dates = sorted(str(x["write_date"]) for x in lignes if x.get("write_date"))
        print(f"  {libelle} : {len(lignes)} enregistrement(s)")
        if not dates:
            continue
        recent = dates[-1]
        sup = essayer("count >", lambda m=modele, d=domaine, r=recent: c._call(
            m, "search_count", d + [["write_date", ">", r]]))
        sup_egal = essayer("count >=", lambda m=modele, d=domaine, r=recent: c._call(
            m, "search_count", d + [["write_date", ">=", r]]))
        print(f"    plus ancienne : {dates[0]} | plus recente : {recent}")
        print(f"    write_date >  plus recente : {sup}  (attendu : 0)")
        print(f"    write_date >= plus recente : {sup_egal}  (attendu : 1 ou plus)")


# ---------------------------------------------------------------- ERPNext
def compte_erpnext(c: ERPNextConnector, doctype: str, filtres: list) -> int:
    r = c._get(
        f"/api/resource/{quote(doctype)}",
        fields=json.dumps(["name"]),
        filters=json.dumps(filtres),
        limit_page_length=1000,
    )
    r.raise_for_status()
    return len(r.json().get("data", []))


def erpnext(c: ERPNextConnector) -> None:
    for libelle, doctype in (
        ("clients", "Customer"),
        ("factures", "Sales Invoice"),
        ("articles", "Item"),
    ):
        def lire(doctype=doctype):
            r = c._get(
                f"/api/resource/{quote(doctype)}",
                fields=json.dumps(["name", "modified"]),
                limit_page_length=1000,
            )
            r.raise_for_status()
            return r.json().get("data", [])

        lignes = essayer(f"lecture {doctype}", lire) or []
        dates = sorted(str(x["modified"]) for x in lignes if x.get("modified"))
        print(f"  {libelle} : {len(lignes)} enregistrement(s)")
        if not dates:
            continue
        recent = dates[-1]
        sup = essayer("filtre >", lambda d=doctype, r=recent: compte_erpnext(
            c, d, [["modified", ">", r]]))
        sup_egal = essayer("filtre >=", lambda d=doctype, r=recent: compte_erpnext(
            c, d, [["modified", ">=", r]]))
        print(f"    plus ancienne : {dates[0]} | plus recente : {recent}")
        print(f"    modified >  plus recente : {sup}  (attendu : 0)")
        print(f"    modified >= plus recente : {sup_egal}  (attendu : 1 ou plus)")


# --------------------------------------------------------------- Dolibarr
def compte_dolibarr(c: DolibarrConnector, chemin: str, seuil: str) -> int:
    r = c._get(chemin, limit=1000, page=0, sqlfilters=f"(t.tms:>:'{seuil}')")
    if r.status_code == 404:  # page vide chez Dolibarr
        return 0
    r.raise_for_status()
    return len(r.json())


def dolibarr(c: DolibarrConnector) -> None:
    for libelle, chemin in (
        ("clients", "thirdparties"),
        ("factures", "invoices"),
        ("articles", "products"),
    ):
        tous = essayer(f"lecture {chemin}", lambda chemin=chemin: c._get_all(chemin)) or []
        print(f"  {libelle} : {len(tous)} enregistrement(s)")
        if not tous:
            continue
        premier = tous[0]
        print(
            f"    1er enregistrement : tms={premier.get('tms')!r} "
            f"date_modification={premier.get('date_modification')!r} "
            f"date_creation={premier.get('date_creation')!r}"
        )
        unix = [
            int(x["date_modification"])
            for x in tous
            if str(x.get("date_modification") or "").isdigit()
        ]
        seuils = [("avant tout", "2000-01-01 00:00:00"), ("apres tout", "2100-01-01 00:00:00")]
        if unix:
            recent = datetime.fromtimestamp(max(unix), tz=timezone.utc)
            print(f"    date_modification la plus recente (UTC) : {recent.strftime(FORMAT)}")
            seuils.append(("recent - 1 jour", (recent - timedelta(days=1)).strftime(FORMAT)))
            seuils.append(("recent + 1 jour", (recent + timedelta(days=1)).strftime(FORMAT)))
        else:
            print("    aucune date_modification lisible : le filtre cote hub sera necessaire")
        for nom_seuil, seuil in seuils:
            n = essayer(
                f"filtre {chemin}",
                lambda chemin=chemin, seuil=seuil: compte_dolibarr(c, chemin, seuil),
            )
            print(f"    tms > {seuil} ({nom_seuil}) : {n}")


# ------------------------------------------------------------------- main
def main() -> None:
    for nom, classe, fonction in (
        ("Odoo", OdooConnector, odoo),
        ("Dolibarr", DolibarrConnector, dolibarr),
        ("ERPNext", ERPNextConnector, erpnext),
    ):
        titre(nom)
        connecteur = classe.from_env()
        if connecteur is None:
            print("  ignore (variables .env absentes)")
            continue
        essayer(nom, lambda f=fonction, c=connecteur: f(c))
    titre("FIN : lecture seule, rien n'a ete ecrit")


if __name__ == "__main__":
    main()