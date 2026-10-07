"""Live check ERPNext, Sprint 2 etape 3.4 (LECTURE SEULE), version 2.

Correction : fetch_invoice_lines() recoit la LISTE des factures (un seul
appel), pas un nom de facture.

Lancement (depuis la racine du projet) :
    python scripts/live_check_erpnext_invoices.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RACINE / ".env")

from hub.connectors.erpnext import ERPNextConnector  # noqa: E402


def lire(obj, *noms, defaut=None):
    """Lit le premier champ non vide parmi `noms`, dans un dict ou un objet."""
    for nom in noms:
        valeur = obj.get(nom) if isinstance(obj, dict) else getattr(obj, nom, None)
        if valeur is not None:
            return valeur
    return defaut


def en_nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


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


def signe(valeurs: list[float]) -> str:
    if not valeurs:
        return "aucune valeur"
    negatifs = sum(1 for v in valeurs if v < 0)
    positifs = sum(1 for v in valeurs if v > 0)
    zeros = len(valeurs) - negatifs - positifs
    return f"{negatifs} negatif(s), {positifs} positif(s), {zeros} nul(s)"


def est_avoir(brut: dict) -> bool:
    return lire(brut, "is_return", defaut=0) in (1, True, "1")


def main() -> None:
    titre("0. Connexion et ping")
    connecteur = essayer("from_env()", ERPNextConnector.from_env)
    if connecteur is None:
        print("  Connecteur ERPNext indisponible (variables .env manquantes ?).")
        return
    print(f"  ping() -> {essayer('ping', connecteur.ping)}")

    # ---------------------------------------------------------- factures
    titre("1. Factures")
    factures = essayer("fetch_invoices", connecteur.fetch_invoices) or []
    print(f"  Nombre de factures : {len(factures)}")
    noms_factures = {str(lire(f, "name")) for f in factures if lire(f, "name")}

    par_type_statut = Counter(
        ("avoir" if est_avoir(f) else "facture", str(lire(f, "status", defaut="?")))
        for f in factures
    )
    print("  Par type et statut :")
    for (type_doc, statut), n in sorted(par_type_statut.items()):
        print(f"   - {type_doc:8} | {statut:18} | {n}")
    print(f"  Devises : {dict(Counter(str(lire(f, 'currency', defaut='?')) for f in factures))}")

    # ---------------------------------------------- signe des montants
    titre("2. Signe des montants (point cle : avoirs)")
    normalisees = []
    for f in factures:
        n = essayer(f"normalize_invoice {lire(f, 'name')}", lambda f=f: connecteur.normalize_invoice(f))
        if n is not None:
            normalisees.append((f, n))
    print(f"  Factures normalisees sans erreur : {len(normalisees)} / {len(factures)}")

    avoirs = [(f, n) for f, n in normalisees if est_avoir(f) or n.doc_type != "invoice"]
    normales = [(f, n) for f, n in normalisees if (f, n) not in avoirs]
    print(f"  Avoirs : {len(avoirs)} | Factures normales : {len(normales)}")
    for f, n in avoirs:
        print(
            f"   AVOIR {n.source_id} | brut grand_total={lire(f, 'grand_total')} "
            f"| normalise total_incl_tax={n.total_incl_tax} {n.currency}"
        )
    print(
        "  Signe total_incl_tax, factures : "
        + signe([en_nombre(n.total_incl_tax) for _, n in normales if n.total_incl_tax is not None])
    )
    print(
        "  Signe total_incl_tax, avoirs   : "
        + signe([en_nombre(n.total_incl_tax) for _, n in avoirs if n.total_incl_tax is not None])
    )
    if not avoirs:
        print("  -> Aucun avoir dans ERPNext : le signe des avoirs reste NON VERIFIE.")

    # ------------------------------------------------------------ lignes
    titre("3. Lignes de factures (un seul appel, on passe la liste)")
    lignes = essayer("fetch_invoice_lines", lambda: connecteur.fetch_invoice_lines(factures)) or []
    print(f"  Nombre de lignes : {len(lignes)}")
    if lignes:
        print(f"  Champs de la premiere ligne brute : {sorted(lignes[0].keys())[:30]}")

    lignes_normalisees = 0
    exemple = None
    for ligne in lignes:
        n = essayer("normalize_invoice_line", lambda l=ligne: connecteur.normalize_invoice_line(l))
        if n is not None:
            lignes_normalisees += 1
            if exemple is None:
                exemple = n
    print(f"  Lignes normalisees sans erreur : {lignes_normalisees} / {len(lignes)}")
    if exemple is not None:
        print(f"  Exemple normalise : {exemple!r}"[:500])

    par_facture = Counter(str(lire(l, "parent", defaut="?")) for l in lignes)
    print(f"  Lignes par facture : {dict(sorted(par_facture.items()))}")

    # ----------------------------------------------------------- articles
    titre("4. Articles")
    articles = essayer("fetch_items", connecteur.fetch_items) or []
    print(f"  Nombre d'articles : {len(articles)}")
    codes_articles = {str(lire(a, "name")) for a in articles if lire(a, "name")}

    # ------------------------------------------------------------ clients
    titre("5. Clients")
    clients = essayer("fetch_customers", connecteur.fetch_customers) or []
    print(f"  Nombre de clients : {len(clients)}")
    noms_clients = {str(lire(c, "name")) for c in clients if lire(c, "name")}

    # -------------------------------------------------------------- liens
    titre("6. Verification des liens")
    parent_illisible = 0
    sans_facture = 0
    sans_produit = 0
    produits_absents: set[str] = set()
    for ligne in lignes:
        parent = lire(ligne, "parent")
        if parent is None:
            parent_illisible += 1
        elif str(parent) not in noms_factures:
            sans_facture += 1
        produit = lire(ligne, "item_code")
        if produit is None or str(produit).strip() == "":
            sans_produit += 1
        elif str(produit) not in codes_articles:
            produits_absents.add(str(produit))

    clients_factures = {str(lire(f, "customer")) for f in factures if lire(f, "customer")}
    clients_absents = sorted(clients_factures - noms_clients)
    factures_sans_ligne = sorted(noms_factures - set(par_facture))

    print(f"  Lignes dont le champ parent est illisible : {parent_illisible}")
    print(f"  Lignes sans facture connue                : {sans_facture}")
    print(f"  Lignes sans produit (texte libre)         : {sans_produit}")
    print(f"  Produits de lignes absents des articles   : {len(produits_absents)} {sorted(produits_absents)[:10]}")
    print(f"  Factures sans aucune ligne                : {len(factures_sans_ligne)} {factures_sans_ligne[:10]}")
    print(f"  Clients distincts dans les factures       : {len(clients_factures)}")
    print(f"  Clients de factures absents de raw        : {len(clients_absents)} {clients_absents[:10]}")

    titre("FIN : lecture seule, rien n'a ete ecrit")


if __name__ == "__main__":
    main()