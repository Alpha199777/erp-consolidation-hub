"""Tests de la logique de rapprochement (sans base de donnees)."""
import pytest

from hub.matching import (
    CustomerRow, country_to_iso, find_match, name_similarity,
    normalize_email, normalize_name, normalize_postal,
)


def row(source, source_id, name=None, email=None, postal=None, country=None, cid=None):
    return CustomerRow(source, source_id, name, email, postal, country, cid)


# --- normalisations -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("INFO@EasyClean.CH", "info@easyclean.ch"),
    ("  a@b.fr ", "a@b.fr"),
    ("", None), (None, None), ("pas-un-email", None),
])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Easy Clean Lausanne SA", "easy clean lausanne"),
    ("EASY CLEAN LAUSANNE", "easy clean lausanne"),
    ("Grant Plastics Ltd.", "grant plastics"),
    ("Dupont S.A.", "dupont"),
    ("Societe Genevoise Sàrl", "societe genevoise"),
    ("Café  de  l'Étoile", "cafe de l etoile"),
    ("Company Corp 1", "company 1"),
    ("SA", None), ("   ", None), (None, None),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_normalize_postal():
    assert normalize_postal(" 1004 ") == "1004"
    assert normalize_postal("sw1a 1aa") == "SW1A1AA"
    assert normalize_postal("") is None
    assert normalize_postal(None) is None


@pytest.mark.parametrize("raw,expected", [
    ("CH", "CH"), ("ch", "CH"), ("Switzerland", "CH"), ("Suisse", "CH"),
    ("United States", "US"), ("États-Unis", "US"), ("FR", "FR"),
    ("Atlantide", None), ("", None), (None, None),
])
def test_country_to_iso(raw, expected):
    assert country_to_iso(raw) == expected


def test_similarity_bounds():
    assert name_similarity("grant plastic", "grant plastics") > 0.9
    assert name_similarity("abc", "xyz") < 0.5
    assert name_similarity(None, "abc") == 0.0


# --- regle 1 : e-mail ---------------------------------------------------

def test_rule_email_matches_across_erp_ignoring_case():
    linked = [row("dolibarr", "65", "Easy Clean Lausanne SA", "info@easycleanlausanne.ch", cid=1)]
    new = row("odoo", "43", "Autre nom", "INFO@EasyCleanLausanne.ch")
    match = find_match(new, linked)
    assert (match.customer_id, match.rule) == (1, "email")


def test_email_beats_name_when_both_could_apply():
    linked = [row("dolibarr", "1", "Zeta", "x@x.ch", cid=1),
              row("dolibarr", "2", "Alpha", None, cid=2)]
    match = find_match(row("odoo", "9", "Alpha", "x@x.ch"), linked)
    assert (match.customer_id, match.rule) == (1, "email")


# --- regle 2 : nom normalise --------------------------------------------

def test_rule_name_matches_despite_legal_form_and_case():
    linked = [row("dolibarr", "65", "Easy Clean Lausanne SA", cid=1)]
    match = find_match(row("erpnext", "EC", "EASY CLEAN LAUSANNE"), linked)
    assert (match.customer_id, match.rule) == (1, "name")


def test_name_rule_blocked_when_countries_differ():
    linked = [row("dolibarr", "1", "Dupont SA", country="FR", cid=1)]
    assert find_match(row("odoo", "2", "Dupont", country="CH"), linked) is None


def test_name_rule_allowed_when_one_country_unknown():
    linked = [row("dolibarr", "1", "Dupont SA", country="FR", cid=1)]
    assert find_match(row("odoo", "2", "Dupont", country=None), linked).rule == "name"


# --- regle 3 : nom proche + code postal ---------------------------------

def test_rule_name_postal_matches_close_names_same_postal():
    linked = [row("erpnext", "G1", "Grant Plastics Ltd.", postal="8001", cid=1)]
    match = find_match(row("dolibarr", "70", "Grant Plastic", postal="8001"), linked)
    assert (match.customer_id, match.rule) == (1, "name_postal")


def test_close_names_without_same_postal_do_not_match():
    linked = [row("erpnext", "G1", "Grant Plastics Ltd.", postal="8001", cid=1)]
    assert find_match(row("dolibarr", "70", "Grant Plastic", postal="1204"), linked) is None
    assert find_match(row("dolibarr", "71", "Grant Plastic", postal=None), linked) is None


def test_numbers_in_names_prevent_false_merge():
    linked = [row("dolibarr", "11", "Company Corp 1", postal="75500", cid=1)]
    assert find_match(row("odoo", "5", "Company Corp 2", postal="75500"), linked) is None


def test_distant_names_same_postal_do_not_match():
    linked = [row("erpnext", "A", "Boulangerie Dupuis", postal="1004", cid=1)]
    assert find_match(row("odoo", "B", "Garage Martin", postal="1004"), linked) is None


# --- garde-fous generaux ------------------------------------------------

def test_never_merges_two_rows_of_same_source():
    linked = [row("erpnext", "Grant Plastics Ltd.", "Grant Plastics Ltd.", postal="8001", cid=1)]
    assert find_match(row("erpnext", "Grant Plastic", "Grant Plastic", postal="8001"), linked) is None


def test_same_source_blocked_even_with_same_email():
    linked = [row("odoo", "1", "A", "a@a.ch", cid=1)]
    assert find_match(row("odoo", "2", "B", "a@a.ch"), linked) is None


def test_rows_without_name_or_email_never_match_each_other():
    linked = [row("dolibarr", "1", None, None, cid=1)]
    assert find_match(row("odoo", "2", None, None), linked) is None


def test_ambiguous_evidence_is_not_resolved():
    linked = [row("dolibarr", "1", "Alpha", "x@x.ch", cid=1),
              row("erpnext", "2", "Beta", "x@x.ch", cid=2)]
    assert find_match(row("odoo", "3", "Gamma", "x@x.ch"), linked) is None


def test_third_erp_joins_existing_group():
    linked = [row("dolibarr", "65", "Easy Clean Lausanne SA", "info@ec.ch", cid=1),
              row("erpnext", "EC", "EASY CLEAN LAUSANNE", cid=1)]
    assert find_match(row("odoo", "43", "Easy Clean Lausanne", "info@ec.ch"), linked).customer_id == 1


def test_no_evidence_means_no_match():
    linked = [row("dolibarr", "1", "Alpha", "a@a.ch", "1000", cid=1)]
    assert find_match(row("odoo", "2", "Omega", "o@o.ch", "2000"), linked) is None
    assert find_match(row("odoo", "3", "Omega"), []) is None