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
| 4 | Couche `quality` : règles de contrôle et anomalies | Terminé (voir limites) |
| 5 | Rapport Power BI : modèle en étoile et page anomalies | Terminé (voir limites) |
| 6 | Serveur MCP : `core` et `quality` interrogeables par Claude (via le schéma `reporting`) | Terminé (voir limites) |

## Architecture

- `raw` : copie fidèle de chaque ERP, avec l'enregistrement brut en JSON.
  Tables : `raw.customers`, `raw.items`, `raw.invoices`, `raw.invoice_lines`,
  `raw.sync_runs` (journal) et `raw.sync_state` (points de reprise).
- `core` : référentiel unifié des clients. `core.customers` (un client = une ligne) et
  `core.customer_links` (quelle fiche de `raw.customers` appartient à quel client, et par
  quelle règle). Voir « Rapprochement des clients ».
- `quality` : anomalies détectées. `quality.anomalies` (une ligne par anomalie, avec sa
  gravité, son statut et ses dates). Voir « Contrôle qualité ».
- `reporting` : vues en lecture seule pour Power BI (`dim_customer`, `fact_invoice`, `dim_date`,
  `anomalies`). Voir « Rapport Power BI ». Le serveur MCP lit aussi ce schéma.

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
fusionnées. Ces cas sont aussi suivis comme anomalies (règle `lookalike_customers`).

## Contrôle qualité (couche `quality`)

Principe : une anomalie est un fait suivi dans le temps, pas une ligne d'un rapport jetable.
Elle est identifiée par `(rule_code, entity_key)` (contrainte UNIQUE), donc une relance ne
crée jamais de doublon.

7 règles (`hub/quality_rules.py`, logique pure testée sans base) :

| Règle | Gravité | Contrôle |
|---|---|---|
| `customer_missing_email` | basse | client sans e-mail |
| `cross_erp_mismatch` | moyenne | client présent dans plusieurs ERP avec e-mail, code postal, ville ou pays différents |
| `lookalike_customers` | moyenne | fiches qui se ressemblent sans avoir été fusionnées (reprend `review_core`) |
| `unknown_country` | basse | pays non reconnu |
| `invoice_unknown_customer` | haute | facture dont le client est introuvable |
| `invoice_total_mismatch` | haute | total de la facture différent de la somme des lignes (tolérance 0,01) |
| `invoice_due_before_date` | moyenne | échéance antérieure à la date de facture |

Cycle de vie (`hub/run_quality.py`, fonction pure `plan_sync`, écriture en une transaction) :

| Situation | Effet |
|---|---|
| Nouvelle anomalie | créée au statut `open` |
| Déjà connue, toujours détectée | date de dernière détection mise à jour |
| `fixed` qui réapparaît | repasse en `open` |
| `open` ou `accepted` qui disparaît | passe en `fixed`, `resolved_at` renseigné |
| `accepted` | posé à la main par `UPDATE` pour ignorer une anomalie connue |

## Rapport Power BI (sprint 5)

Principe : les jointures et les règles métier restent en SQL, où elles se testent. Power BI ne
lit que le schéma `reporting`, jamais `raw`, `core` ou `quality` directement.

Vues (`sql/006_reporting_views.sql`) :

| Vue | Contenu |
|---|---|
| `reporting.dim_customer` | un client unifié par ligne, avec le nombre d'ERP et la liste des ERP où il existe |
| `reporting.fact_invoice` | une facture par ligne, rattachée au client unifié par `core.customer_links` (`customer_id` vide si aucun rattachement) |
| `reporting.dim_date` | calendrier en années complètes autour des dates de factures |
| `reporting.anomalies` | `quality.anomalies` avec un rang de gravité |

`fact_invoice` garde les montants de l'ERP tels quels et ajoute `signed_total_excl_tax` :
négatif quand `doc_type = 'credit_note'`. Aucun montant n'est converti d'une devise à l'autre.

Fichier : `powerbi/erp_hub.pbix` (mode Importer, serveur `localhost:5433`, base `hub`).
Modèle : `dim_customer` 1 à plusieurs `fact_invoice` sur `customer_id`, `dim_date` 1 à plusieurs
`fact_invoice` sur `invoice_date`, filtre à sens unique. `anomalies` n'a pas de relation : elle
décrit des entités de plusieurs types. Le fichier contient une copie des données de démonstration ;
pour la mettre à jour, utiliser Actualiser dans Power BI.

Page « Anomalies » : nombre d'anomalies ouvertes, anomalies ouvertes par règle, tableau de détail
avec statut. Page « Factures » : chiffre d'affaires net par devise (CHF, EUR).

## Serveur MCP (sprint 6)

Principe : Claude ne reçoit jamais un accès libre à la base. Il appelle 4 outils fixes, qui
lisent uniquement le schéma `reporting`. La lecture seule est garantie par PostgreSQL, pas
seulement par le code.

Outils (`hub/mcp_server.py`, transport stdio) :

| Outil | Rôle |
|---|---|
| `list_open_anomalies` | anomalies ouvertes, les plus graves d'abord ; filtres `rule_code`, `severity`, `limit` (1 à 100) |
| `get_anomaly` | détail d'une anomalie par son identifiant (`found: false` si elle n'existe pas) |
| `find_customer` | recherche d'un client unifié par nom ou e-mail (2 caractères minimum) |
| `invoice_totals_by_currency` | factures, avoirs et net hors taxes, une ligne par devise |

Sécurité :

- compte `hub_reader` (`sql/007_reader_role.sql`) : `default_transaction_read_only = on`,
  accès au seul schéma `reporting` ; `raw`, `core` et `quality` lui sont fermés. Les vues lisent
  leurs tables avec les droits de leur propriétaire. `scripts/check_reader.py` lance 9 contrôles.
- le mot de passe est dans `.env` (`HUB_READER_PASSWORD`), jamais dans le code.
- les noms et messages renvoyés viennent des ERP : ce sont des données, pas des instructions.
  Le serveur le rappelle à Claude dans ses instructions.
- en stdio, la sortie standard est le canal du protocole : aucun `print()` dans le serveur.

Fonctionnement : `hub/read_api.py` contient les requêtes (testables sans MCP) ; chaque appel
ouvre sa propre connexion, puis la referme. Une demande invalide renvoie son message à Claude
(`ToolError`) au lieu d'une erreur générique.

Connexion à Claude Desktop : ajouter dans `%APPDATA%\Claude\claude_desktop_config.json`
(adapter les chemins) puis quitter complètement l'application et la relancer :

```json
"mcpServers": {
  "erp-hub": {
    "command": "C:\\chemin\\vers\\erp-consolidation-hub\\.venv\\Scripts\\python.exe",
    "args": ["-m", "hub.mcp_server"],
    "env": { "PYTHONPATH": "C:\\chemin\\vers\\erp-consolidation-hub" }
  }
}
```

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

## Résultats du sprint 4 (mesuré en local, 12 octobre 2026)

- 18 anomalies ouvertes sur les données de démonstration : 17 `customer_missing_email`
  (19 fiches sans e-mail, dont 2 rattachées à un client qui en a un) et 1
  `lookalike_customers` (`Grant Plastic` et `Grant Plastics Ltd.`, même ERP).
- 5 règles à 0 sur ces données : `cross_erp_mismatch`, `unknown_country` et les 3 règles de
  factures. Ce sont des contrôles vérifiés à zéro, jamais déclenchés par des données réelles.
- Relance de `hub.run_quality` : 0 nouvelle, 0 réapparue, 0 corrigée.
- Cycle de vie prouvé sur un cas construit : le code postal d'`Easy Clean Lausanne SA` a été
  changé à la main dans Dolibarr (1004 puis 1003), `cross_erp_mismatch` a détecté l'écart
  (19 détectées, 1 nouvelle), puis le code postal a été remis à 1004 : l'anomalie est passée
  en `fixed` avec `resolved_at` renseigné.
- 313 tests pytest.

## Résultats du sprint 5 (mesuré en local, 14 octobre 2026)

- 4 vues dans le schéma `reporting`. Contrôles SQL : 20 factures dans `raw.invoices` et 20 dans
  `reporting.fact_invoice`, 0 clé en double, 0 facture sans client unifié ; 38 clients dans
  `core.customers` et dans `reporting.dim_customer`.
- Valeurs réelles des factures : Dolibarr 6 en EUR, ERPNext 5 en CHF, Odoo 9 en CHF
  (4 `invoice`, 5 `credit_note`). Seul Odoo a des avoirs.
- Rapprochement avec SQL : la page « Anomalies » affiche 18 anomalies ouvertes (17
  `customer_missing_email`, 1 `lookalike_customers`), plus 1 `cross_erp_mismatch` en `fixed` dans
  le tableau (19 lignes au total). La page « Factures » affiche 363 000 CHF et 122,24 EUR de
  chiffre d'affaires net, identiques aux sommes SQL. Chez Odoo, factures et avoirs valent chacun
  124 500 CHF : le net est nul, particularité des données de démonstration.
- Aucun nouveau test pytest (313 au total) : les vues sont contrôlées par des requêtes SQL
  lancées à la main, pas par des tests automatiques.

## Résultats du sprint 6 (mesuré en local, 14 octobre 2026)

- Compte `hub_reader` : 9 contrôles réussis (lecture de `reporting`, refus sur `raw`, `core`,
  `quality`, refus d'écriture).
- 335 tests pytest (22 de plus qu'au sprint 5 : 15 sur `read_api`, 7 sur le serveur MCP).
- Serveur connecté à Claude Desktop, 4 outils visibles, réglés sur « Nécessite une approbation ».
- 4 questions réelles posées à Claude, réponses rapprochées de la base :
  18 anomalies ouvertes (1 `lookalike_customers`, 17 `customer_missing_email`), comme Power BI ;
  `Easy Clean Lausanne` (client n° 25, 3 ERP, `info@easycleanlausanne.ch`, CH, 1004), identique à
  `reporting.dim_customer` ; 363 000 CHF (9 factures, 5 avoirs) et 122,24 EUR (6 factures), comme
  Power BI, et Claude refuse de les additionner ; anomalie 18 détaillée, anomalie 9999 renvoie
  `found: false`.
- Contrôle SQL de `reporting.fact_invoice` par source : les 5 avoirs viennent tous d'Odoo
  (net signé -124 500 CHF contre 124 500 CHF de factures). Aucun brouillon ni facture annulée
  dans les données.

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
- Qualité : les gravités (basse, moyenne, haute) sont un choix de départ, pas validé par un
  métier. Les règles de factures et `unknown_country` n'ont jamais détecté d'anomalie sur les
  données de démonstration ; elles ne sont éprouvées que par des tests unitaires.
- Qualité : les statuts `accepted` et « réapparue » sont testés en tests unitaires (et sur une
  base temporaire), pas sur la base de démonstration. `accepted` se pose à la main.
- Qualité : le message de `cross_erp_mismatch` cite le premier nom par ordre alphabétique,
  pas le nom retenu pour le client unifié (cosmétique).
- Qualité : `core` ne contient que les clients ; les factures ne sont pas encore rattachées
  à un client unifié.

- Power BI : le rapport est minimal (deux pages, trois mesures). Les cartes de la page « Factures »
  affichent encore le format par défaut de Power BI (par exemple « 363,000K ») ; les valeurs sont
  justes.
- Power BI : le mode Importer fige une copie des données ; il n'y a pas d'actualisation planifiée.
  La connexion à la base locale n'est pas chiffrée (acceptable en local, pas ailleurs).
- Power BI : le chiffre d'affaires additionne tous les statuts de facture (`Overdue`, `Paid`,
  `posted`, brouillons éventuels) sans les interpréter. Seul `invoice_date` est relié au calendrier,
  pas `due_date`. `signed_total_excl_tax` n'est vérifié que pour Odoo : Dolibarr et ERPNext n'ont
  aucun avoir dans les données. Aucune conversion CHF/EUR.

- MCP : les outils ne renvoient que des anomalies ouvertes (sauf `get_anomaly`) et des fiches
  unifiées. Ils n'exposent ni le score de similarité, ni les valeurs comparées par une règle, ni la
  liste des règles actives : Claude ne peut pas distinguer « règle sans résultat » de « règle jamais
  exécutée ». Pas de détail par ERP pour un client.
- MCP : transport stdio uniquement (un client local lance le processus). Pas d'accès à distance,
  pas d'authentification applicative : la protection repose sur le compte `hub_reader` en lecture
  seule et sur l'approbation de chaque appel dans Claude Desktop.
- MCP : `invoice_totals_by_currency` additionne tous les statuts de facture sans les interpréter ;
  les données de démonstration ne contiennent ni brouillon ni facture annulée.
- MCP : les réponses de Claude (par exemple « doublon probable dans le même ERP ») sont des
  déductions à partir des données renvoyées, à vérifier ; l'API du SDK `mcp` 2.3.0 n'a été
  vérifiée que pour les fonctions utilisées.
- Tests : les vues `reporting` et la connexion réelle à Claude Desktop sont contrôlées à la main,
  pas par des tests automatiques ; les tests de base de données sont ignorés sans `HUB_READER_PASSWORD`.

## Prérequis

Python 3.11+ (testé avec 3.12.9), Docker Desktop, Git. Power BI Desktop (Windows) pour ouvrir `powerbi/erp_hub.pbix`.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Renseigner ensuite `.env` (clés API, URL de la base, `HUB_READER_PASSWORD`). Ne jamais commiter `.env`.
`ERPNEXT_TIMEZONE` est optionnelle (`Europe/Paris` par défaut).

Créer les tables et les vues des couches `raw`, `core`, `quality` et `reporting` (les scripts sont rejouables sans risque) :

```powershell
Get-Content sql\001_raw_schema.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\002_raw_invoices_items.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\003_sync_state.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\004_core_schema.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\005_quality_schema.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
Get-Content sql\006_reporting_views.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1
```

Créer le compte de lecture seule du serveur MCP (choisir le mot de passe, le même que dans `.env`) :

```powershell
Get-Content sql\007_reader_role.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1 -v reader_password=VOTRE_MOT_DE_PASSE
python scripts\check_reader.py          # 9 contrôles du compte hub_reader
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
python -m hub.run_quality                # applique les règles, met à jour quality.anomalies
Get-Content sql\checks_sprint2.sql | docker exec -i hub-db psql -U hub -d hub   # contrôles en lecture seule
python -m hub.mcp_server                 # serveur MCP (lancé par le client MCP, pas à la main)
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
- `hub/quality_rules.py` : les 7 règles de contrôle (logique pure)
- `hub/run_quality.py` : cycle de vie des anomalies et écriture dans `quality`
- `sql/001_raw_schema.sql`, `sql/002_raw_invoices_items.sql`, `sql/003_sync_state.sql` : schéma `raw`
- `sql/004_core_schema.sql` : schéma `core`
- `sql/005_quality_schema.sql` : schéma `quality`
- `sql/006_reporting_views.sql` : vues `reporting` pour Power BI
- `powerbi/erp_hub.pbix` : rapport Power BI (modèle en étoile, pages Anomalies et Factures)
- `hub/read_api.py` : requêtes de lecture sur `reporting` (compte `hub_reader`)
- `hub/mcp_server.py` : serveur MCP, 4 outils en lecture seule
- `sql/007_reader_role.sql` : compte `hub_reader` en lecture seule
- `scripts/check_reader.py` : 9 contrôles du compte de lecture seule
- `sql/checks_sprint2.sql` : contrôles de la couche `raw` (lecture seule)
- `scripts/` : explorations et vérifications en lecture seule
- `tests/` : tests unitaires et d'intégration