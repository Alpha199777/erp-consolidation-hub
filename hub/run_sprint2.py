"""Point d'entrée du Sprint 2.

Usage :
    python -m hub.run_sprint2 --check-only   # teste les connexions, n'écrit rien
    python -m hub.run_sprint2                # synchronisation incrémentale
    python -m hub.run_sprint2 --full         # rechargement complet

Pour chaque ERP actif, dans l'ordre : customers, items, invoices (+ invoice_lines).
Chaque entité est tracée dans raw.sync_runs. Un échec n'arrête pas les autres.
En mode incrémental, un ERP sans point de reprise est lu en entier (ce qui
initialise raw.sync_state).
"""
import argparse
import sys

from dotenv import load_dotenv

from hub import load
from hub.run_sprint1 import build_connectors, check_only

ENTITIES = ("customers", "items", "invoices")


def _report(result, label):
    """Affiche une ligne de résultat. Retourne 0 si succès, 1 sinon."""
    portee = "complet" if result.since is None else f"depuis {result.since:%Y-%m-%d %H:%M:%S}"
    print(
        f"  {result.source:<10} {label:<14} {result.status:<8} "
        f"récupérés={result.rows_fetched} chargés={result.rows_loaded} "
        f"[{portee}] (run_id={result.run_id})"
    )
    if result.status != "success":
        print(f"             erreur : {result.error}")
        return 1
    return 0


def run_sync(connectors, mode="incremental"):
    """Synchronise toutes les entités de chaque ERP. Retourne 0 si tout a réussi, 1 sinon."""
    conn = load.connect()
    exit_code = 0
    try:
        for connector in connectors:
            for entity in ENTITIES:
                if entity == "invoices":
                    # factures + lignes : deux résultats, une seule transaction
                    results = load.sync_invoices(conn, connector, mode=mode)
                    labels = ("invoices", "invoice_lines")
                else:
                    results = (load.sync_source(conn, connector, entity, mode=mode),)
                    labels = (entity,)
                for result, label in zip(results, labels):
                    exit_code |= _report(result, label)
    finally:
        conn.close()
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hub de consolidation ERP - Sprint 2")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="teste les connexions aux ERP sans rien écrire en base",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="rechargement complet : ignore les points de reprise",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    connectors, skipped = build_connectors()

    if skipped:
        print(f"Ignorés (variables .env absentes) : {', '.join(skipped)}")
    if not connectors:
        print("Aucun ERP configuré dans .env : rien à faire.")
        return 1

    if args.check_only:
        print("Test des connexions (aucune écriture) :")
        return check_only(connectors)

    mode = "full" if args.full else "incremental"
    if mode == "full":
        print("Rechargement complet (clients, articles, factures et lignes) :")
    else:
        print("Synchronisation incrémentale (clients, articles, factures et lignes) :")
    return run_sync(connectors, mode=mode)


if __name__ == "__main__":
    sys.exit(main())