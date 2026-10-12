"""Construction de la couche core : un client = une ligne.

Usage :
    python -m hub.build_core              # rattache les nouvelles fiches de raw
    python -m hub.build_core --rebuild    # repart de zero (a faire si on change les regles)

Principe :
  - une fiche de raw deja rattachee garde son client (les customer_id restent stables) ;
  - une nouvelle fiche est rapprochee avec hub.matching.find_match, sinon elle cree un client ;
  - la fiche "maitre" de chaque client (core.customers) est recalculee a chaque passage,
    champ par champ, en prenant la premiere valeur renseignee selon SOURCE_PRIORITY ;
  - tout se passe dans une seule transaction : tout est applique, ou rien.

Limite connue : une fiche deja rattachee n'est pas re-evaluee si son contenu change
dans raw. Apres un changement de regles, utiliser --rebuild.
"""
import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping

from dotenv import load_dotenv
from psycopg.rows import tuple_row

from hub import load
from hub.matching import CustomerRow, country_to_iso, find_match, normalize_email

# Ordre de confiance pour choisir les valeurs du client unifie.
SOURCE_PRIORITY = ("odoo", "erpnext", "dolibarr")

MASTER_FIELDS = ("name", "email", "postal_code", "city", "country_code")


@dataclass(frozen=True)
class Decision:
    row: CustomerRow
    customer_id: int
    rule: str


def link_rows(unlinked: Iterable[CustomerRow], linked: Iterable[CustomerRow],
              allocate: Callable[[], int]) -> list[Decision]:
    """Decide, fiche par fiche, a quel client rattacher chaque nouvelle fiche.

    Une fiche rattachee est aussitot ajoutee au lot de comparaison : la suivante peut
    donc la retrouver. `allocate` fournit l'identifiant d'un nouveau client.
    """
    pool = list(linked)
    decisions = []
    for row in unlinked:
        match = find_match(row, pool)
        if match:
            customer_id, rule = match.customer_id, match.rule
        else:
            customer_id, rule = allocate(), "new_customer"
        decisions.append(Decision(row, customer_id, rule))
        pool.append(replace(row, customer_id=customer_id))
    return decisions


def _priority(source: str) -> int:
    return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def golden_record(members: Iterable[Mapping]) -> dict:
    """Valeurs du client unifie : premiere valeur renseignee, par ordre de priorite des ERP."""
    ordered = sorted(members, key=lambda m: (_priority(m["source"]), m["source_id"]))

    def first(field, accept=lambda v: v is not None):
        for member in ordered:
            value = member.get(field)
            if isinstance(value, str):
                value = value.strip() or None
            if accept(value):
                return value
        return None

    emails = [normalize_email(m.get("email")) for m in ordered]
    return {
        "name": first("name"),
        "email": next((e for e in emails if e), None),
        "postal_code": first("postal_code"),
        "city": first("city"),
        "country_code": first("country_code"),
    }


@dataclass
class BuildResult:
    raw_rows: int = 0
    new_links: int = 0
    new_customers: int = 0
    updated_customers: int = 0


def _read_raw(cur) -> dict:
    cur.execute(
        "SELECT source, source_id, name, email, postal_code, city, country "
        "FROM raw.customers ORDER BY source, source_id"
    )
    rows = {}
    for source, source_id, name, email, postal_code, city, country in cur.fetchall():
        rows[(source, source_id)] = {
            "source": source, "source_id": source_id, "name": name, "email": email,
            "postal_code": postal_code, "city": city,
            "country_code": country_to_iso(country),
        }
    return rows


def build(conn, rebuild: bool = False) -> BuildResult:
    """Met a jour core.customers et core.customer_links depuis raw.customers."""
    result = BuildResult()
    with conn.transaction():
        with conn.cursor(row_factory=tuple_row) as cur:
            if rebuild:
                cur.execute("TRUNCATE core.customer_links, core.customers RESTART IDENTITY")

            raw = _read_raw(cur)
            result.raw_rows = len(raw)

            cur.execute("SELECT source, source_id, customer_id FROM core.customer_links")
            link_of = {(s, i): cid for s, i, cid in cur.fetchall()}

            def as_row(rec, customer_id=None):
                return CustomerRow(rec["source"], rec["source_id"], rec["name"], rec["email"],
                                   rec["postal_code"], rec["country_code"], customer_id)

            linked = [as_row(rec, link_of[key]) for key, rec in raw.items() if key in link_of]
            unlinked = [as_row(rec) for key, rec in raw.items() if key not in link_of]

            def allocate():
                cur.execute("INSERT INTO core.customers DEFAULT VALUES RETURNING customer_id")
                result.new_customers += 1
                return cur.fetchone()[0]

            for d in link_rows(unlinked, linked, allocate):
                cur.execute(
                    "INSERT INTO core.customer_links (source, source_id, customer_id, rule) "
                    "VALUES (%s, %s, %s, %s)",
                    (d.row.source, d.row.source_id, d.customer_id, d.rule),
                )
                link_of[(d.row.source, d.row.source_id)] = d.customer_id
                result.new_links += 1

            members = defaultdict(list)
            for key, customer_id in link_of.items():
                if key in raw:
                    members[customer_id].append(raw[key])

            cur.execute("SELECT customer_id, name, email, postal_code, city, country_code "
                        "FROM core.customers")
            current = {r[0]: dict(zip(MASTER_FIELDS, r[1:])) for r in cur.fetchall()}

            for customer_id, group in members.items():
                wanted = golden_record(group)
                if current.get(customer_id) != wanted:
                    cur.execute(
                        "UPDATE core.customers SET name = %s, email = %s, postal_code = %s, "
                        "city = %s, country_code = %s, updated_at = now() "
                        "WHERE customer_id = %s",
                        (*(wanted[f] for f in MASTER_FIELDS), customer_id),
                    )
                    result.updated_customers += 1
    return result


def summary(conn) -> None:
    """Affiche l'etat de core (lecture seule)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT count(*) FROM raw.customers")
        raw_total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM core.customers")
        core_total = cur.fetchone()[0]
        cur.execute("SELECT rule, count(*) FROM core.customer_links GROUP BY rule ORDER BY rule")
        rules = cur.fetchall()
        cur.execute(
            "SELECT n, count(*) FROM (SELECT customer_id, count(DISTINCT source) AS n "
            "FROM core.customer_links GROUP BY customer_id) t GROUP BY n ORDER BY n"
        )
        by_sources = cur.fetchall()
    print(f"  fiches dans raw.customers : {raw_total}")
    print(f"  clients dans core.customers : {core_total}")
    print("  liens par règle : " + ", ".join(f"{r}={n}" for r, n in rules))
    print("  clients présents dans : " + ", ".join(
        f"{n} ERP={c}" for n, c in by_sources))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hub de consolidation ERP - couche core")
    parser.add_argument("--rebuild", action="store_true",
                        help="vide core puis reconstruit tout depuis raw")
    args = parser.parse_args(argv)

    load_dotenv()
    conn = load.connect()
    try:
        result = build(conn, rebuild=args.rebuild)
        print("Couche core :")
        print(f"  nouveaux liens : {result.new_links}, nouveaux clients : {result.new_customers}, "
              f"clients mis à jour : {result.updated_customers}")
        summary(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())