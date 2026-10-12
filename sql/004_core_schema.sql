-- Sprint 3 : couche core (referentiel unifie des clients).
-- Un client = une ligne dans core.customers, meme s'il existe dans plusieurs ERP.
-- core.customer_links dit quelle ligne de raw.customers appartient a quel client.
-- Script rejouable : peut etre lance plusieurs fois sans erreur.

CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.customers (
    customer_id   BIGSERIAL PRIMARY KEY,
    name          TEXT,
    email         TEXT,
    postal_code   TEXT,
    city          TEXT,
    country_code  CHAR(2),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.customer_links (
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    customer_id   BIGINT NOT NULL REFERENCES core.customers (customer_id),
    rule          TEXT NOT NULL
                  CHECK (rule IN ('email', 'name', 'name_postal', 'new_customer')),
    linked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id),
    FOREIGN KEY (source, source_id) REFERENCES raw.customers (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_customer_links_customer
    ON core.customer_links (customer_id);