"""Rapprochement des clients entre ERP (logique pure, sans base de donnees).

Principe : on ne rattache une fiche a un client existant que sur une preuve
explicite. Une fusion a tort est silencieuse, donc pire qu'un doublon manque.

Regles, par ordre de fiabilite :
  1. 'email'       : meme e-mail (en minuscules)
  2. 'name'        : meme nom une fois normalise (casse, accents, SA, Ltd...)
  3. 'name_postal' : nom tres proche ET meme code postal

Garde-fous communs :
  - on ne fusionne jamais deux fiches du meme ERP (un ERP distingue deja
    ses clients ; les quasi-doublons internes sont a relire, pas a fusionner) ;
  - regles 2 et 3 : deux pays connus et differents interdisent la fusion ;
  - regle 3 : les chiffres du nom doivent etre identiques
    ('Company Corp 1' et 'Company Corp 2' restent separes) ;
  - si la preuve designe plusieurs clients differents, on ne tranche pas.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

SIMILARITY_THRESHOLD = 0.85

LEGAL_FORMS = frozenset({
    "sa", "sarl", "sas", "sasu", "ag", "gmbh", "ltd", "limited", "llc",
    "inc", "corp", "corporation", "plc", "spa", "srl", "bv", "nv", "co",
})

# Pays vus dans les trois ERP : code ISO, nom anglais ou francais.
# Un pays inconnu donne None : on ne devine pas.
_COUNTRY_NAMES = {
    "switzerland": "CH", "suisse": "CH",
    "france": "FR",
    "united states": "US", "united states of america": "US", "usa": "US",
    "etats-unis": "US", "etats unis": "US",
    "belgium": "BE", "belgique": "BE",
    "germany": "DE", "allemagne": "DE",
    "italy": "IT", "italie": "IT",
    "spain": "ES", "espagne": "ES",
    "india": "IN", "inde": "IN",
    "canada": "CA",
    "united kingdom": "GB", "royaume-uni": "GB", "uk": "GB",
    "greece": "GR", "grece": "GR",
}


def _ascii_lower(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    return value if "@" in value else None


def normalize_name(value: str | None) -> str | None:
    """Nom comparable : sans accents, sans casse, sans ponctuation ni forme juridique.

    Les points sont supprimes d'abord pour que 'S.A.' devienne 'SA'.
    """
    if value is None:
        return None
    tokens = re.findall(r"[a-z0-9]+", _ascii_lower(value.replace(".", "")))
    tokens = [t for t in tokens if t not in LEGAL_FORMS]
    return " ".join(tokens) or None


def normalize_postal(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", "", value).upper()
    return value or None


def country_to_iso(value: str | None) -> str | None:
    """'CH', 'Switzerland', 'Suisse' -> 'CH'. Pays inconnu -> None."""
    if value is None:
        return None
    value = value.strip()
    if len(value) == 2 and value.isalpha():
        return value.upper()
    return _COUNTRY_NAMES.get(_ascii_lower(value))


def name_similarity(a: str | None, b: str | None) -> float:
    """Ressemblance entre deux noms deja normalises, de 0 a 1."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _digits(name: str) -> list[str]:
    return re.findall(r"\d+", name)


@dataclass(frozen=True)
class CustomerRow:
    """Une fiche client de raw, avec le client core auquel elle est rattachee (si deja fait)."""

    source: str
    source_id: str
    name: str | None
    email: str | None
    postal_code: str | None
    country_code: str | None = None
    customer_id: int | None = None


@dataclass(frozen=True)
class Match:
    customer_id: int
    rule: str
    matched: CustomerRow


def _countries_conflict(a: CustomerRow, b: CustomerRow) -> bool:
    return bool(a.country_code and b.country_code and a.country_code != b.country_code)


def _single_customer(hits: list[CustomerRow]) -> int | None:
    """Id du client designe par les preuves, ou None si aucune ou ambigue."""
    ids = {h.customer_id for h in hits}
    return ids.pop() if len(ids) == 1 else None


def find_match(row: CustomerRow, linked: Iterable[CustomerRow]) -> Match | None:
    """Cherche, parmi les fiches deja rattachees, le client auquel `row` appartient."""
    linked = list(linked)
    sources_of = defaultdict(set)
    for other in linked:
        sources_of[other.customer_id].add(other.source)
    candidates = [o for o in linked if row.source not in sources_of[o.customer_id]]

    email = normalize_email(row.email)
    if email:
        hits = [o for o in candidates if normalize_email(o.email) == email]
        if hits:
            cid = _single_customer(hits)
            return Match(cid, "email", hits[0]) if cid is not None else None

    name = normalize_name(row.name)
    if not name:
        return None

    hits = [o for o in candidates
            if normalize_name(o.name) == name and not _countries_conflict(row, o)]
    if hits:
        cid = _single_customer(hits)
        return Match(cid, "name", hits[0]) if cid is not None else None

    postal = normalize_postal(row.postal_code)
    if postal:
        hits = []
        for o in candidates:
            other_name = normalize_name(o.name)
            if (other_name
                    and normalize_postal(o.postal_code) == postal
                    and _digits(other_name) == _digits(name)
                    and not _countries_conflict(row, o)
                    and name_similarity(name, other_name) >= SIMILARITY_THRESHOLD):
                hits.append(o)
        if hits:
            cid = _single_customer(hits)
            return Match(cid, "name_postal", hits[0]) if cid is not None else None

    return None