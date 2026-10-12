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
| 2 | Factures, articles, synchronisation incrémentale, adresses ERPNext | Terminé (voir limites) |
| 3 | Couche `core` : rapprochement des clients entre ERP | Terminé (voir limites) |
| 4 | Couche `quality` : règles de contrôle et anomalies | À faire |
| 5 | Rapport Power BI | À faire |
| 6 | Serveur MCP | À faire |

## Architecture

- `raw` : copie fidèle de chaque ERP, avec l'enregistrement brut en JSON.
  Tables : `raw.customers`, `raw.items`, `raw.invoices`, `raw.invoice_lines`,
  `raw.sync_runs` (journal) et `raw.sync_state` (points de reprise).
- `core` : référentiel unifié des clients. `core.customers` (un client = une ligne) et
  `core.customer_links` (quelle fiche de `raw.customers` appartient à quel client, et par
  quelle règle). Voir « Rapprochement des clients ».
- `quality` : anomalies détectées (sprint 4).

Chaque connecteur (`hub/connectors/`) respecte le même contrat :
`ping()`, `fetch_customers(since=None)` / `normalize()`,
`fetch_invoices(since=None)` / `normalize_invoice()`,
`fetch_invoice_lines(invoices=None)` / `normalize_invoice_line()`,
`fetch_items(since=None)` / `normalize_item()`, `record_modified_at(record)`
et `overlap`. Ajouter un ERP = écrire un fichier. Un test de contrat
(`tests/test_connector_contract.py`) vérifie les signatures des trois connecteurs.

Choix clés : payload brut conservé, upsert idempotent sur `(source, source_id)`,
chaque synchronisation tracée dans `raw.sync_runs`, valeurs vides unifiées en
`NULL` par `clean()`, devise stockée avec chaque montant.

## Synchronisation incrémentale

- `raw.sync_state` garde un point de reprise par ERP et par entité (`customers`,
  `items`, `invoices` ; les lignes de facture suivent leurs factures).
- Le point de reprise est la plus grande date de modification vue chez l'ERP, jamais
  l'heure du PC. Il est écrit dans la même transaction que les données et ne recule jamais.
- La lecture repart du point de reprise moins une marge de recouvrement
  (Odoo 5 min, ERPNext 5 min, Dolibarr 1 jour). Sans point de reprise, ou avec
  `--full`, la lecture est complète.
- ERPNext : ville, code postal et pays viennent du doctype Address, relié au client
  par une table enfant. Si un client a plusieurs adresses : adresse déclarée sur le
  client, sinon adresse principale, sinon type Billing, sinon nom le plus petit.
  Un client dont seule l'adresse a changé est relu.
- ERPNext écrit ses dates en heure du serveur, sans fuseau. Le connecteur les lit en
  `Europe/Paris` (variable optionnelle `ERPNEXT_TIMEZONE`) et les convertit en UTC.

## Rapprochement des clients (couche `core`)

Principe : une fiche de `raw.customers` n'est rattachée à un client existant que sur une
preuve explicite. Une fusion à tort est silencieuse, donc pire qu'un doublon manqué.

Règles, appliquées dans cet ordre (`hub/matching.py`) :

1. `email` : même e-mail, comparé en minuscules.
2. `name` : même nom une fois normalisé (sans accents, casse, ponctuation ni forme
   juridique comme SA, Ltd, Inc).
3. `name_postal` : nom très proche (ressemblance d'au moins 0,85) et même code postal.

Garde-fous :

- deux fiches du même ERP ne sont jamais fusionnées (un ERP distingue déjà ses clients) ;
- règles 2 et 3 : deux pays connus et différents interdisent la fusion ;
- règle 3 : les chiffres du nom doivent être identiques (`Company Corp 1` et
  `Company Corp 2` restent séparés) ;
- si la preuve désigne plusieurs clients différents, on ne tranche pas.

Fonctionnement (`hub/build_core.py`) : une fiche déjà rattachée garde son client, donc les
`customer_id` restent stables d'une relance à l'autre. Les nouvelles fiches sont rapprochées
ou créent un client. La fiche du client unifié est recalculée champ par champ, en prenant la
première valeur renseignée dans l'ordre Odoo, ERPNext, Dolibarr. Tout est fait dans une seule
transaction. Les pays sont ramenés à un code ISO sur 2 lettres.

`hub/review_core.py` liste, en lecture seule, les fiches qui se ressemblent sans avoir été
fusionnées. Au sprint 4, ces cas deviendront des anomalies suivies.

## Résultats du sprint 1 (mesuré en local)

- 36 clients chargés : 8 Odoo, 25 Dolibarr, 3 ERPNext.
- Relance de la synchronisation : aucun doublon, comptes identiques.
- 6 synchronisations tracées dans `raw.sync_runs`.
- 54 tests pytest.

## Résultats du sprint 2 (mesuré en local, 9 octobre 2026)

Volumes dans `raw` :

| Table | Odoo | Dolibarr | ERPNext |
|---|---|---|---|
| `customers` | 9 | 25 | 3 |
| `items` | 42 | 22 | 10 |
| `invoices` | 9 (4 factures, 5 avoirs) | 6 | 5 |
| `invoice_lines` | 16 | 9 | 10 |

- Aucun doublon après plusieurs relances (contrôles SQL : `sql/checks_sprint2.sql`),
  tous les runs en `success`, chaque entité tracée dans `raw.sync_runs`.
- Relance sans nouvelle modification (après les modifications de test), enregistrements
  relus sur le total de chaque ERP : Dolibarr 7 sur 62, ERPNext 17 sur 28, Odoo 61 sur 76.
- Une modification faite à la main dans chaque ERP a été reprise par la synchronisation
  suivante, avec le point de reprise avancé à sa date de modification : Indian SAS
  (Dolibarr, téléphone), Lumber Inc (Odoo, téléphone) et l'article SKU001 (ERPNext, nom).
- Clients ERPNext : 2 sur 3 ont une ville et un pays, grâce à 3 adresses de démonstration
  créées à la main (un client avec une adresse, un avec deux, un sans adresse).
- Odoo compte 9 clients contre 8 au sprint 1 : un client (Easy Clean Lausanne) est apparu
  ou a été modifié après le sprint 1 ; la cause exacte n'est pas vérifiée.
- 236 tests pytest.

## Résultats du sprint 3 (mesuré en local, 12 octobre 2026)

Les données de démonstration des trois ERP ne contenaient aucun client commun. Pour exercer
les règles, 4 fiches de test ont été créées à la main : `Easy Clean Lausanne SA` (Dolibarr),
`EASY CLEAN LAUSANNE` (ERPNext), `Azure Interiors` (Dolibarr) et `Grant Plastic` (ERPNext).
Les fusions ci-dessous portent donc sur un jeu de test construit, pas sur des doublons
trouvés dans des données réelles.

- 41 fiches dans `raw.customers` (27 Dolibarr, 9 Odoo, 5 ERPNext) pour 38 clients dans
  `core.customers`.
- 41 liens : 38 `new_customer`, 1 `email`, 1 `name`, 1 `name_postal`.
- Clients présents dans 1 ERP : 36 ; dans 2 ERP : 1 (`Azure Interior`) ; dans 3 ERP : 1
  (`Easy Clean Lausanne`).
- Relance de `hub.build_core` : 0 nouveau lien, 0 nouveau client, 0 mise à jour.
- Contrôle SQL : 0 fiche sans client, 0 client sans fiche, 0 fiche rattachée deux fois.
- `Company Corp 1` et `Company Corp 2` restent deux clients.
- Rapport des cas douteux : 1 paire (`Grant Plastic` et `Grant Plastics Ltd.`, même ERP,
  non fusionnées).
- 295 tests pytest.

## Limites connues

- Les suppressions ne sont pas détectées : un enregistrement supprimé dans un ERP reste
  dans `raw`. Seul un rechargement complet (`--full`) permet de les rattraper.
- Le statut « Overdue » d'ERPNext est calculé et peut changer sans que `modified` bouge.
  La marge de recouvrement ne couvre pas ce cas ; le rechargement complet le corrige.
- Le gain de la synchronisation incrémentale n'est démontré que sur Dolibarr. Les données
  de démonstration d'Odoo et d'ERPNext ont été écrites dans la même minute : la marge de
  5 minutes en fait relire une grande partie.
- Le fuseau d'ERPNext est supposé `Europe/Paris` (écart de +2 h constaté), pas confirmé
  dans ses paramètres système. Le passage à l'heure d'hiver du 25 octobre 2026 n'a pas été
  testé sur un vrai serveur : l'heure répétée est lue comme de l'heure d'été (erreur d'au
  plus une heure sur cette seule heure).
- Signe des avoirs : Odoo les stocke avec un montant positif (`doc_type = credit_note`),
  à unifier dans `core`. Dolibarr et ERPNext n'ont aucun avoir dans les données : leur signe
  n'est pas vérifié, ni les statuts Dolibarr 0 et 3.
- Devises : Dolibarr en EUR, Odoo et ERPNext en CHF. Aucun montant n'est converti ni
  additionné entre ERP.
- Le téléphone mobile Dolibarr (`phone_mobile`) reste dans le payload, pas dans la colonne
  `phone`.
- Rapprochement : le seuil de ressemblance (0,85) a été choisi sur quelques cas, pas calibré
  sur des données réelles ; aucune précision ni aucun rappel mesurés. La table des pays ne
  couvre que ceux vus dans les trois ERP : un pays inconnu donne un code vide et n'empêche
  pas la fusion.
- Rapprochement : une fiche déjà rattachée n'est pas réévaluée si son contenu change dans
  `raw` ; après un changement de règles, utiliser `python -m hub.build_core --rebuild`
  (les `customer_id` sont alors recréés).
- Rapprochement : la priorité Odoo, ERPNext, Dolibarr pour la fiche du client unifié est un
  choix de départ, pas une règle métier validée. Le rapport des cas douteux compare toutes
  les paires de fiches : acceptable pour quelques milliers de fiches, pas pour des centaines
  de milliers.

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
`ERPNEXT_TIMEZONE` est optionnelle (`Europe/Paris` par défaut).

Créer les tables des couches `raw` et `core` (les scripts sont rejouables sans risque) :

```powershell
Get-Content sql\001_raw_schema.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\002_raw_invoices_items.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\003_sync_state.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\004_core_schema.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
```

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
python -m hub.run_sprint2 --check-only   # teste les connexions, n'écrit rien
python -m hub.run_sprint2                # synchronisation incrémentale
python -m hub.run_sprint2 --full         # rechargement complet
python -m hub.build_core                 # rattache les nouvelles fiches de raw à core
python -m hub.build_core --rebuild       # vide core et reconstruit tout depuis raw
python -m hub.review_core                # cas douteux non fusionnés (lecture seule)
Get-Content sql\checks_sprint2.sql | docker exec -i hub-db psql -U hub -d hub   # contrôles en lecture seule
python -m pytest -q                      # tests (certains nécessitent la base hub)
```

`python -m hub.run_sprint1` (clients seulement) reste disponible. Un connecteur dont
les variables `.env` sont absentes est ignoré.

## Structure

- `hub/connectors/` : un fichier par ERP
- `hub/models.py` : dataclass `Customer`, `Invoice`, `InvoiceLine`, `Item`, fonction `clean()` et conversions montants/dates
- `hub/load.py` : upsert idempotent, journal et points de reprise
- `hub/run_sprint1.py`, `hub/run_sprint2.py` : points d'entrée de la synchronisation
- `hub/matching.py` : règles de rapprochement des clients (logique pure)
- `hub/build_core.py` : construction de la couche `core`
- `hub/review_core.py` : rapport des cas douteux
- `sql/001_raw_schema.sql`, `sql/002_raw_invoices_items.sql`, `sql/003_sync_state.sql` : schéma `raw`
- `sql/004_core_schema.sql` : schéma `core`
- `sql/checks_sprint2.sql` : contrôles de la couche `raw` (lecture seule)
- `scripts/` : explorations et vérifications en lecture seule
- `tests/` : tests unitaires et d'intégration