# ERP Consolidation Hub

Projet personnel (Data/BI) : consolider les données de 3 ERP open source
(Odoo, Dolibarr, ERPNext) dans une base PostgreSQL commune, détecter les
incohérences entre ERP, les restituer dans Power BI, puis les rendre
interrogeables par Claude via un serveur MCP.

> Projet personnel d'apprentissage. Les ERP tournent en local avec leurs
> données de démonstration : aucune donnée réelle d'entreprise.

## Avancement

| Sprint | Livrable | État |
|---|---|---|
| 1 | 3 ERP, 3 connecteurs, clients dans `raw`, journal `raw.sync_runs` | Terminé |
| 2 | Factures, articles, synchronisation incrémentale, adresses ERPNext | À faire |
| 3 | Couche `core` : rapprochement des clients entre ERP | À faire |
| 4 | Couche `quality` : règles de contrôle et anomalies | À faire |
| 5 | Rapport Power BI | À faire |
| 6 | Serveur MCP | À faire |

## Architecture

- `raw` : copie fidèle de chaque ERP, avec l'enregistrement brut en JSON.
- `core` : référentiel unifié (sprint 3).
- `quality` : anomalies détectées (sprint 4).

Chaque connecteur (`hub/connectors/`) respecte le même contrat :
`ping()`, `fetch_customers()`, `normalize()`. Ajouter un ERP = écrire un fichier.

Choix clés : payload brut conservé, upsert idempotent sur `(source, source_id)`,
chaque synchronisation tracée dans `raw.sync_runs`, valeurs vides unifiées en
`NULL` par `clean()`.

## Résultat du sprint 1 (mesuré en local)

- 36 clients chargés : 8 Odoo, 25 Dolibarr, 3 ERPNext.
- Relance de la synchronisation : aucun doublon, comptes identiques.
- 6 synchronisations tracées dans `raw.sync_runs`.
- 54 tests pytest.

## Prérequis

Python 3.11+, Docker Desktop, Git.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Renseigner ensuite `.env` (clés API, URL de la base). Ne jamais commiter `.env`.

## ERP et ports

| Service | Port | Accès |
|---|---|---|
| Odoo 18 | 8069 | XML-RPC, base `erp_demo` |
| Dolibarr | 8081 | API REST, en-tête `DOLAPIKEY` (module API REST activé) |
| ERPNext | 8080 | API REST, `Authorization: token clé:secret` (via `frappe_docker`) |
| Base du hub (PostgreSQL 16) | 5433 | base `hub` |

Lancement : voir `docker/odoo/`, `docker/dolibarr/` et `docker/erpnext/LISEZMOI.md`.

## Utilisation

```powershell
python -m hub.run_sprint1 --check-only   # teste les connexions, n'écrit rien
python -m hub.run_sprint1                # charge les clients dans raw.customers
python -m pytest -q                      # tests (certains nécessitent la base hub)
```

Un connecteur dont les variables `.env` sont absentes est ignoré.

## Structure

- `hub/connectors/` : un fichier par ERP
- `hub/models.py` : dataclass `Customer` et fonction `clean()`
- `hub/load.py` : upsert idempotent et journal
- `hub/run_sprint1.py` : point d'entrée
- `sql/001_raw_schema.sql` : schéma `raw`
- `scripts/` : explorations et vérifications en lecture seule
- `tests/` : tests unitaires et d'intégration