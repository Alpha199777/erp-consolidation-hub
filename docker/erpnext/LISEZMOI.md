# ERPNext (via frappe_docker)

ERPNext n'est pas lancé par un fichier de ce dépôt : on utilise le `pwd.yml`
officiel de `frappe_docker`, cloné à côté du projet (hors de ce dépôt).

## Lancer

    git clone https://github.com/frappe/frappe_docker ..\frappe_docker
    docker compose -f ..\frappe_docker\pwd.yml up -d

Attendre quelques minutes que le conteneur `create-site` se termine (statut `Exited (0)`).
Accès : http://localhost:8080 (image `frappe/erpnext:v16.37.0`).

## Première connexion

Un assistant de configuration s'ouvre : créer un utilisateur, choisir France / EUR,
cocher Comptabilité et Stock, créer la société et cocher « Generate Demo Data ».

## Clés API

Fiche de l'utilisateur > section API Access > Generate Keys. Le secret ne
s'affiche qu'une fois. Les copier dans `.env` (jamais dans le code ni sur GitHub) :

    ERPNEXT_URL=http://localhost:8080
    ERPNEXT_API_KEY=...
    ERPNEXT_API_SECRET=...

## Volume constaté

3 clients de démonstration.