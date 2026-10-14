-- Sprint 6.1 : compte de lecture seule pour le serveur MCP. Rejouable.
-- Usage : Get-Content sql\007_reader_role.sql | docker exec -i hub-db psql -U hub -d hub -v ON_ERROR_STOP=1 -v reader_password=MOT_DE_PASSE
-- Le mot de passe vient de la ligne de commande, jamais d'un fichier du depot.

-- Cree le compte seulement s'il n'existe pas.
SELECT format('CREATE ROLE hub_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hub_reader')
\gexec

ALTER ROLE hub_reader WITH LOGIN PASSWORD :'reader_password';
-- Toute session de ce compte est en lecture seule, meme si le code essaie d'ecrire.
ALTER ROLE hub_reader SET default_transaction_read_only = on;

SELECT format('GRANT CONNECT ON DATABASE %I TO hub_reader', current_database())
\gexec

-- Acces au seul schema reporting. Les schemas raw, core et quality restent fermes :
-- les vues lisent leurs tables avec les droits de leur proprietaire.
GRANT USAGE ON SCHEMA reporting TO hub_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO hub_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting GRANT SELECT ON TABLES TO hub_reader;