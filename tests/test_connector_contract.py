"""Test de contrat : les 3 connecteurs exposent les memes methodes, avec les memes signatures.

Aucun reseau : on inspecte seulement les signatures des classes.
"""
from __future__ import annotations

import importlib
import inspect

import pytest

MODULES = [
    "hub.connectors.odoo",
    "hub.connectors.dolibarr",
    "hub.connectors.erpnext",
]

METHODES = [
    "ping",
    "fetch_customers",
    "normalize",
    "fetch_invoices",
    "normalize_invoice",
    "fetch_invoice_lines",
    "normalize_invoice_line",
    "fetch_items",
    "normalize_item",
]

LECTURES_SANS_ARGUMENT = ["fetch_customers", "fetch_invoices", "fetch_items"]

NORMALISATIONS = [
    "normalize",
    "normalize_invoice",
    "normalize_invoice_line",
    "normalize_item",
]


def _classe_connecteur(nom_module: str):
    module = importlib.import_module(nom_module)
    candidates = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__ and hasattr(cls, "fetch_invoices")
    ]
    assert len(candidates) == 1, f"{nom_module} : {len(candidates)} classe(s) trouvee(s)"
    return candidates[0]


def _parametres_obligatoires(methode) -> list[str]:
    """Noms des parametres sans valeur par defaut, hors self."""
    return [
        nom
        for nom, p in inspect.signature(methode).parameters.items()
        if nom != "self"
        and p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]


@pytest.mark.parametrize("nom_module", MODULES)
def test_methodes_du_contrat_presentes(nom_module):
    cls = _classe_connecteur(nom_module)
    manquantes = [m for m in METHODES if not callable(getattr(cls, m, None))]
    assert manquantes == [], f"{nom_module} : methodes absentes {manquantes}"


@pytest.mark.parametrize("nom_module", MODULES)
def test_lectures_sans_argument_obligatoire(nom_module):
    cls = _classe_connecteur(nom_module)
    for name in LECTURES_SANS_ARGUMENT:
        assert _parametres_obligatoires(getattr(cls, name)) == [], name


@pytest.mark.parametrize("nom_module", MODULES)
def test_fetch_invoice_lines_accepte_la_liste_des_factures(nom_module):
    """load.py appelle fetch_invoice_lines(liste_des_factures) sur tous les ERP."""
    cls = _classe_connecteur(nom_module)
    parametres = inspect.signature(cls.fetch_invoice_lines).parameters
    assert "invoices" in parametres, f"{nom_module} : parametre 'invoices' absent"
    assert parametres["invoices"].default is None
    assert _parametres_obligatoires(cls.fetch_invoice_lines) == []


@pytest.mark.parametrize("nom_module", MODULES)
def test_normalisations_prennent_un_record(nom_module):
    cls = _classe_connecteur(nom_module)
    for name in NORMALISATIONS:
        params = _parametres_obligatoires(getattr(cls, name))
        assert params == ["record"], f"{name} : {params}"