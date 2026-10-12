"""Tests de la construction de core (parties pures, sans base de donnees)."""
import itertools

from hub.build_core import Decision, golden_record, link_rows
from hub.matching import CustomerRow


def row(source, source_id, name=None, email=None, postal=None, country=None, cid=None):
    return CustomerRow(source, source_id, name, email, postal, country, cid)


def counter(start=100):
    numbers = itertools.count(start)
    return lambda: next(numbers)


# --- link_rows ----------------------------------------------------------

def test_three_erp_same_client_end_up_in_one_customer():
    unlinked = [
        row("dolibarr", "65", "Easy Clean Lausanne SA", "info@ec.ch", "1004", "CH"),
        row("erpnext", "EC", "EASY CLEAN LAUSANNE"),
        row("odoo", "43", "Easy Clean Lausanne", "info@ec.ch", "1004", "CH"),
    ]
    decisions = link_rows(unlinked, [], counter())
    assert {d.customer_id for d in decisions} == {100}
    assert [d.rule for d in decisions] == ["new_customer", "name", "email"]


def test_different_clients_stay_separate():
    unlinked = [row("dolibarr", "11", "Company Corp 1", postal="75500"),
                row("dolibarr", "13", "Company Corp 2")]
    decisions = link_rows(unlinked, [], counter())
    assert [d.customer_id for d in decisions] == [100, 101]
    assert all(d.rule == "new_customer" for d in decisions)


def test_new_row_joins_an_already_linked_customer():
    linked = [row("dolibarr", "65", "Easy Clean Lausanne SA", "info@ec.ch", cid=7)]
    decisions = link_rows([row("odoo", "43", "Easy Clean", "info@ec.ch")], linked, counter())
    assert decisions == [Decision(row("odoo", "43", "Easy Clean", "info@ec.ch"), 7, "email")]


def test_allocate_is_called_only_for_new_customers():
    calls = []

    def allocate():
        calls.append(1)
        return 50

    linked = [row("dolibarr", "1", "Alpha", cid=7)]
    link_rows([row("odoo", "2", "Alpha"), row("odoo", "3", "Omega")], linked, allocate)
    assert len(calls) == 1


def test_same_erp_near_duplicates_are_not_merged():
    unlinked = [row("erpnext", "Grant Plastic", "Grant Plastic", postal="8001"),
                row("erpnext", "Grant Plastics Ltd.", "Grant Plastics Ltd.", postal="8001")]
    decisions = link_rows(unlinked, [], counter())
    assert len({d.customer_id for d in decisions}) == 2


def test_empty_input():
    assert link_rows([], [], counter()) == []


# --- golden_record ------------------------------------------------------

def member(source, source_id, **kw):
    base = {"source": source, "source_id": source_id, "name": None, "email": None,
            "postal_code": None, "city": None, "country_code": None}
    base.update(kw)
    return base


def test_golden_record_prefers_odoo_then_erpnext_then_dolibarr():
    record = golden_record([
        member("dolibarr", "65", name="Easy Clean Lausanne SA", city="Lausanne"),
        member("erpnext", "EC", name="EASY CLEAN LAUSANNE"),
        member("odoo", "43", name="Easy Clean Lausanne"),
    ])
    assert record["name"] == "Easy Clean Lausanne"
    assert record["city"] == "Lausanne"  # seule valeur renseignee


def test_golden_record_fills_gaps_field_by_field():
    record = golden_record([
        member("odoo", "1", name="Acme", email=None, postal_code="1004"),
        member("dolibarr", "2", name="Acme SA", email="Info@Acme.ch", country_code="CH"),
    ])
    assert record == {"name": "Acme", "email": "info@acme.ch", "postal_code": "1004",
                      "city": None, "country_code": "CH"}


def test_golden_record_ignores_blank_strings_and_invalid_emails():
    record = golden_record([
        member("odoo", "1", name="  ", email="pas-un-email"),
        member("dolibarr", "2", name="Acme", email="a@acme.ch"),
    ])
    assert record["name"] == "Acme"
    assert record["email"] == "a@acme.ch"


def test_golden_record_unknown_source_comes_last_and_is_deterministic():
    members = [member("autre", "9", name="Z"), member("odoo", "1", name="A")]
    assert golden_record(members)["name"] == "A"
    assert golden_record(list(reversed(members)))["name"] == "A"