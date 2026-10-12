"""Rapport des cas douteux : fiches qui se ressemblent mais n'ont PAS ete fusionnees.

Usage :
    python -m hub.review_core

Lecture seule : ne modifie rien. Une paire est signalee quand deux fiches de clients
core differents ont une preuve de ressemblance (meme e-mail, meme nom normalise, ou
nom tres proche avec meme code postal) sans avoir ete fusionnees. Les raisons possibles :
fiches du meme ERP, preuve ambigue, ou client deja present dans cet ERP.
A relire a la main ; au Sprint 4 ces cas deviendront des anomalies suivies.

Limite : comparaison de toutes les paires (acceptable pour quelques milliers de fiches).
"""
import re
import sys
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from dotenv import load_dotenv
from psycopg.rows import tuple_row

from hub import load
from hub.matching import (
    SIMILARITY_THRESHOLD, CustomerRow, country_to_iso, name_similarity,
    normalize_email, normalize_name, normalize_postal,
)


@dataclass(frozen=True)
class Suspect:
    a: CustomerRow
    b: CustomerRow
    evidence: str       # 'meme_email', 'meme_nom' ou 'nom_proche_meme_cp'
    why_not_merged: str


def _evidence(a: CustomerRow, b: CustomerRow) -> str | None:
    email_a, email_b = normalize_email(a.email), normalize_email(b.email)
    if email_a and email_a == email_b:
        return "meme_email"

    if a.country_code and b.country_code and a.country_code != b.country_code:
        return None
    name_a, name_b = normalize_name(a.name), normalize_name(b.name)
    if not name_a or not name_b:
        return None
    if name_a == name_b:
        return "meme_nom"

    postal_a, postal_b = normalize_postal(a.postal_code), normalize_postal(b.postal_code)
    if (postal_a and postal_a == postal_b
            and re.findall(r"\d+", name_a) == re.findall(r"\d+", name_b)
            and name_similarity(name_a, name_b) >= SIMILARITY_THRESHOLD):
        return "nom_proche_meme_cp"
    return None


def find_suspects(rows: Iterable[CustomerRow]) -> list[Suspect]:
    """Paires de fiches de clients differents qui se ressemblent."""
    suspects = []
    for a, b in combinations(rows, 2):
        if a.customer_id == b.customer_id:
            continue
        evidence = _evidence(a, b)
        if evidence:
            why = ("meme ERP" if a.source == b.source
                   else "preuve ambigue ou client deja present dans cet ERP")
            suspects.append(Suspect(a, b, evidence, why))
    return suspects


def read_rows(conn) -> list[CustomerRow]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT l.customer_id, r.source, r.source_id, r.name, r.email, r.postal_code, r.country "
            "FROM core.customer_links l JOIN raw.customers r USING (source, source_id) "
            "ORDER BY r.source, r.source_id"
        )
        return [CustomerRow(s, i, n, e, p, country_to_iso(c), cid)
                for cid, s, i, n, e, p, c in cur.fetchall()]


def main():
    load_dotenv()
    conn = load.connect()
    try:
        suspects = find_suspects(read_rows(conn))
    finally:
        conn.close()

    print(f"Cas douteux à relire : {len(suspects)}")
    for s in suspects:
        print(f"  - {s.a.source}:{s.a.source_id} ({s.a.name}) <-> "
              f"{s.b.source}:{s.b.source_id} ({s.b.name})")
        print(f"    preuve : {s.evidence} ; non fusionné car : {s.why_not_merged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())