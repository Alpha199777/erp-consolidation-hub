"""Verifie que le compte hub_reader est bien en lecture seule (Sprint 6.1).

Se connecte comme le fera le serveur MCP : par le port publie de la base, avec le
mot de passe du compte. Lecture seule : ne modifie rien (les ecritures tentees sont refusees).

Usage : python scripts/check_reader.py
Le mot de passe est lu dans la variable HUB_READER_PASSWORD, sinon demande a l'ecran.
"""
import getpass
import os
import sys

import psycopg
from dotenv import load_dotenv


def attempt(conn, sql: str) -> tuple[bool, str]:
    """Execute sql ; renvoie (reussi, detail). Annule toujours la transaction."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone() if cur.description else None
        return True, str(row[0]) if row else "ok"
    except psycopg.Error as exc:
        return False, type(exc).__name__
    finally:
        conn.rollback()


def main() -> int:
    load_dotenv()
    password = os.environ.get("HUB_READER_PASSWORD") or getpass.getpass("Mot de passe hub_reader : ")
    conn = psycopg.connect(
        host=os.environ.get("HUB_READER_HOST", "localhost"),
        port=int(os.environ.get("HUB_READER_PORT", "5433")),
        dbname=os.environ.get("HUB_READER_DB", "hub"),
        user="hub_reader",
        password=password,
        connect_timeout=5,
    )
    # (description, requete, resultat attendu : True = doit reussir)
    checks = [
        ("lire reporting.fact_invoice", "SELECT count(*) FROM reporting.fact_invoice", True),
        ("lire reporting.dim_customer", "SELECT count(*) FROM reporting.dim_customer", True),
        ("lire reporting.anomalies ouvertes", "SELECT count(*) FROM reporting.anomalies WHERE status = 'open'", True),
        ("lire raw.invoices", "SELECT count(*) FROM raw.invoices", False),
        ("lire core.customers", "SELECT count(*) FROM core.customers", False),
        ("lire quality.anomalies", "SELECT count(*) FROM quality.anomalies", False),
        ("ecrire dans core.customers", "INSERT INTO core.customers (name) VALUES ('x')", False),
        ("modifier reporting.anomalies", "UPDATE reporting.anomalies SET status = 'fixed'", False),
        ("creer une table dans reporting", "CREATE TABLE reporting.x (a int)", False),
    ]
    failures = 0
    for label, sql, should_work in checks:
        ok, detail = attempt(conn, sql)
        good = ok == should_work
        failures += 0 if good else 1
        print(f"{'OK  ' if good else 'ECHEC'} {label:36} -> {'reussi' if ok else 'refuse'} ({detail})")
    conn.close()
    print("\nTout est conforme." if failures == 0 else f"\n{failures} controle(s) non conforme(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())