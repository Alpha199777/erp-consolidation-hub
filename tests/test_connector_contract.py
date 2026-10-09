"""Test de contrat : les 3 connecteurs exposent les memes methodes, avec les memes signatures.

Aucun reseau : on inspecte seulement les signatures des classes.
"""
from __future__ import annotations

import importlib
import inspect
from datetime import timedelta

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
    "record_modified_at",
]

LECTURES_SANS_ARGUMENT = ["fetch_customers", "fetch_invoices", "fetch_items"]

NORMALISATIONS = [
    "normalize",
    "normalize_invoice",
    "normalize_invoice_line",
    "normalize_item",
    "record_modified_at",
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


@pytest.mark.parametrize("nom_module", MODULES)
def test_lectures_acceptent_since_optionnel(nom_module):
    """Synchronisation incrementale : since=None = lecture complete."""
    cls = _classe_connecteur(nom_module)
    for name in LECTURES_SANS_ARGUMENT:
        parametres = inspect.signature(getattr(cls, name)).parameters
        assert "since" in parametres, f"{nom_module}.{name} : parametre 'since' absent"
        assert parametres["since"].default is None, f"{nom_module}.{name} : since doit valoir None par defaut"


@pytest.mark.parametrize("nom_module", MODULES)
def test_marge_de_recouvrement_positive(nom_module):
    cls = _classe_connecteur(nom_module)
    assert isinstance(cls.overlap, timedelta), f"{nom_module} : overlap doit etre un timedelta"
    assert cls.overlap > timedelta(0), f"{nom_module} : overlap doit etre positif"


@pytest.mark.parametrize("nom_module", MODULES)
def test_record_modified_at_tolere_un_enregistrement_vide(nom_module):
    cls = _classe_connecteur(nom_module)
    connecteur = cls.__new__(cls)  # sans __init__ : ni reseau, ni variables .env
    assert connecteur.record_modified_at({}) is None