"""Point d'entree du Sprint 4 : detecte les anomalies et met a jour quality.anomalies.

Usage :
    python -m hub.run_quality

A chaque passage (une seule transaction) :
  - une anomalie nouvelle est creee avec le statut 'open' ;
  - une anomalie deja connue voit sa date de derniere detection mise a jour ;
  - une anomalie 'fixed' qui reapparait repasse en 'open' ;
  - une anomalie 'open' ou 'accepted' qui n'est plus detectee passe en 'fixed'.
Le statut 'accepted' se pose a la main (UPDATE) pour ignorer une anomalie connue.
"""
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from dotenv import load_dotenv
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from hub import load
from hub.matching import CustomerRow, country_to_iso
from hub.quality_rules import Anomaly, QualityData, detect_all

RULE_CODES = (
    "customer_missing_email", "cross_erp_mismatch", "lookalike_customers", "unknown_country",
    "invoice_unknown_customer", "invoice_total_mismatch", "invoice_due_before_date",
)


@dataclass
class SyncPlan:
    to_insert: list = field(default_factory=list)   # cles (rule_code, entity_key)
    to_touch: list = field(default_factory=list)    # deja connues et encore detectees
    to_reopen: list = field(default_factory=list)   # 'fixed' qui reapparaissent
    to_fix: list = field(default_factory=list)      # 'open'/'accepted' qui ont disparu


def plan_sync(existing: dict, detected_keys: set) -> SyncPlan:
    """existing : {(rule_code, entity_key): statut}. Pure, sans base de donnees."""
    plan = SyncPlan()
    for key in sorted(detected_keys):
        if key not in existing:
            plan.to_insert.append(key)
        elif existing[key] == "fixed":
            plan.to_reopen.append(key)
        else:
            plan.to_touch.append(key)
    for key, status in sorted(existing.items()):
        if key not in detected_keys and status in ("open", "accepted"):
            plan.to_fix.append(key)
    return plan


def load_data(conn) -> QualityData:
    data = QualityData()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT customer_id, name, email FROM core.customers ORDER BY customer_id")
        data.customers = [{"customer_id": i, "name": n, "email": e} for i, n, e in cur.fetchall()]

        cur.execute(
            "SELECT l.customer_id, r.source, r.source_id, r.name, r.email, r.postal_code, "
            "r.city, r.country FROM core.customer_links l "
            "JOIN raw.customers r USING (source, source_id) ORDER BY r.source, r.source_id"
        )
        members = defaultdict(list)
        for cid, source, source_id, name, email, postal, city, country in cur.fetchall():
            iso = country_to_iso(country)
            members[cid].append({"source": source, "source_id": source_id, "name": name,
                                 "email": email, "postal_code": postal, "city": city,
                                 "country_code": iso})
            data.rows.append(CustomerRow(source, source_id, name, email, postal, iso, cid))
        data.members = dict(members)

        cur.execute("SELECT source, source_id, name, country FROM raw.customers")
        raw = cur.fetchall()
        data.raw_customers = [{"source": s, "source_id": i, "name": n, "country": c}
                              for s, i, n, c in raw]
        data.customer_keys = {(s, i) for s, i, _, _ in raw}

        cur.execute("SELECT source, source_id, number, customer_source_id, invoice_date, "
                    "due_date, total_excl_tax FROM raw.invoices ORDER BY source, source_id")
        data.invoices = [
            {"source": s, "source_id": i, "number": n, "customer_source_id": c,
             "invoice_date": d, "due_date": due, "total_excl_tax": t}
            for s, i, n, c, d, due, t in cur.fetchall()
        ]

        cur.execute("SELECT source, invoice_source_id, sum(total_excl_tax) FROM raw.invoice_lines "
                    "GROUP BY source, invoice_source_id")
        data.line_totals = {(s, i): Decimal(t) for s, i, t in cur.fetchall() if t is not None}
    conn.commit()  # termine la lecture ; sans effet si la connexion est en autocommit
    return data


def sync_anomalies(conn, anomalies: list[Anomaly]) -> SyncPlan:
    """Applique le plan de synchronisation dans une seule transaction."""
    by_key = {(a.rule_code, a.entity_key): a for a in anomalies}
    with conn.transaction():
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT rule_code, entity_key, status FROM quality.anomalies")
            existing = {(r, k): s for r, k, s in cur.fetchall()}
            plan = plan_sync(existing, set(by_key))

            for key in plan.to_insert:
                a = by_key[key]
                cur.execute(
                    "INSERT INTO quality.anomalies "
                    "(rule_code, entity_type, entity_key, severity, message, details) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (a.rule_code, a.entity_type, a.entity_key, a.severity, a.message,
                     Jsonb(a.details)),
                )
            for key in plan.to_touch + plan.to_reopen:
                a = by_key[key]
                reopen = key in plan.to_reopen
                cur.execute(
                    "UPDATE quality.anomalies SET severity = %s, message = %s, details = %s, "
                    "last_detected_at = now(), "
                    "status = CASE WHEN %s THEN 'open' ELSE status END, "
                    "resolved_at = CASE WHEN %s THEN NULL ELSE resolved_at END "
                    "WHERE rule_code = %s AND entity_key = %s",
                    (a.severity, a.message, Jsonb(a.details), reopen, reopen, key[0], key[1]),
                )
            for rule_code, entity_key in plan.to_fix:
                cur.execute(
                    "UPDATE quality.anomalies SET status = 'fixed', resolved_at = now() "
                    "WHERE rule_code = %s AND entity_key = %s",
                    (rule_code, entity_key),
                )
    return plan


def summary(conn) -> None:
    """Affiche le nombre d'anomalies par regle et par statut (lecture seule)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT rule_code, status, count(*) FROM quality.anomalies "
                    "GROUP BY rule_code, status")
        counts = defaultdict(dict)
        for rule, status, n in cur.fetchall():
            counts[rule][status] = n
    print(f"  {'règle':<26} {'open':>5} {'fixed':>6} {'accepted':>9}")
    for rule in RULE_CODES:
        c = counts.get(rule, {})
        print(f"  {rule:<26} {c.get('open', 0):>5} {c.get('fixed', 0):>6} {c.get('accepted', 0):>9}")


def main():
    load_dotenv()
    conn = load.connect()
    try:
        anomalies = detect_all(load_data(conn))
        plan = sync_anomalies(conn, anomalies)
        print("Couche quality :")
        print(f"  détectées : {len(anomalies)} ; nouvelles : {len(plan.to_insert)}, "
              f"réapparues : {len(plan.to_reopen)}, corrigées : {len(plan.to_fix)}")
        summary(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())