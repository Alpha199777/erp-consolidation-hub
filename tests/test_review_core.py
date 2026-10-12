"""Tests du rapport des cas douteux (sans base de donnees)."""
from hub.matching import CustomerRow
from hub.review_core import find_suspects


def row(source, source_id, name=None, email=None, postal=None, country=None, cid=None):
    return CustomerRow(source, source_id, name, email, postal, country, cid)


def test_same_erp_near_duplicates_are_reported():
    rows = [row("erpnext", "A", "Grant Plastic", postal="8001", cid=1),
            row("erpnext", "B", "Grant Plastics Ltd.", postal="8001", cid=2)]
    (suspect,) = find_suspects(rows)
    assert suspect.evidence == "nom_proche_meme_cp"
    assert suspect.why_not_merged == "meme ERP"


def test_merged_rows_are_not_reported():
    rows = [row("dolibarr", "1", "Alpha", "a@a.ch", cid=1),
            row("odoo", "2", "Alpha", "a@a.ch", cid=1)]
    assert find_suspects(rows) == []


def test_same_email_in_different_customers_is_reported():
    rows = [row("odoo", "1", "Alpha", "x@x.ch", cid=1),
            row("odoo", "2", "Beta", "X@x.ch", cid=2)]
    (suspect,) = find_suspects(rows)
    assert suspect.evidence == "meme_email"


def test_cross_erp_ambiguity_is_explained():
    rows = [row("erpnext", "A", "Alpha", cid=1), row("erpnext", "B", "Alpha SA", cid=2),
            row("odoo", "C", "Alpha", cid=3)]
    reasons = {(s.a.source_id, s.b.source_id): s.why_not_merged for s in find_suspects(rows)}
    assert reasons[("A", "B")] == "meme ERP"
    assert reasons[("A", "C")] != "meme ERP"


def test_numbers_and_missing_postal_are_not_reported():
    rows = [row("dolibarr", "11", "Company Corp 1", postal="75500", cid=1),
            row("dolibarr", "13", "Company Corp 2", postal="75500", cid=2),
            row("odoo", "5", "Grant Plastic", cid=3), row("odoo", "6", "Grant Plastics", cid=4)]
    assert find_suspects(rows) == []


def test_different_countries_block_name_evidence():
    rows = [row("odoo", "1", "Dupont", country="FR", cid=1),
            row("dolibarr", "2", "Dupont SA", country="CH", cid=2)]
    assert find_suspects(rows) == []


def test_rows_without_any_evidence():
    assert find_suspects([row("odoo", "1", None, cid=1), row("odoo", "2", None, cid=2)]) == []
    assert find_suspects([]) == []