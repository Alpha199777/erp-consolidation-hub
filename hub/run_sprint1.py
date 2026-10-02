"""Point d'entrée du Sprint 1.

Usage :
    python -m hub.run_sprint1 --check-only   # teste les connexions, n'écrit rien
    python -m hub.run_sprint1                # charge les clients dans raw.customers
"""
import argparse
import sys

from dotenv import load_dotenv

from hub import load
from hub.connectors.dolibarr import DolibarrConnector
from hub.connectors.erpnext import ERPNextConnector
from hub.connectors.odoo import OdooConnector

CONNECTOR_CLASSES = [OdooConnector, DolibarrConnector, ERPNextConnector]


def build_connectors():
    """Retourne (connecteurs actifs, noms des sources ignorées).

    Un connecteur dont les variables .env sont absentes renvoie None
    via from_env() : il est ignoré, sans erreur.
    """
    active, skipped = [], []
    for cls in CONNECTOR_CLASSES:
        connector = cls.from_env()
        if connector is None:
            skipped.append(cls.source)
        else:
            active.append(connector)
    return active, skipped


def check_only(connectors):
    """Fait un ping() par ERP. N'écrit rien. Retourne 0 si tout répond, 1 sinon."""
    all_ok = True
    for connector in connectors:
        try:
            ok = bool(connector.ping())
        except Exception as exc:  # un ERP en panne ne doit pas bloquer les autres
            print(f"  {connector.source:<10} ECHEC  ({exc})")
            all_ok = False
            continue
        print(f"  {connector.source:<10} {'OK' if ok else 'ECHEC'}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


def run_sync(connectors):
    """Synchronise les clients de chaque ERP. Retourne 0 si tout a réussi, 1 sinon."""
    conn = load.connect()
    exit_code = 0
    try:
        for connector in connectors:
            result = load.sync_source(conn, connector, "customers")
            print(
                f"  {result.source:<10} {result.status:<8} "
                f"récupérés={result.rows_fetched} chargés={result.rows_loaded} "
                f"(run_id={result.run_id})"
            )
            if result.status != "success":
                print(f"             erreur : {result.error}")
                exit_code = 1
    finally:
        conn.close()
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hub de consolidation ERP - Sprint 1")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="teste les connexions aux ERP sans rien écrire en base",
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

    print("Synchronisation des clients :")
    return run_sync(connectors)


if __name__ == "__main__":
    sys.exit(main())