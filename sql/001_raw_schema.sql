-- Sprint 1 : couche raw (copie fidele des ERP)
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.customers (
    source          TEXT        NOT NULL,   -- 'odoo', 'dolibarr', 'erpnext'
    source_id       TEXT        NOT NULL,   -- identifiant du client dans l'ERP
    name            TEXT,
    email           TEXT,
    phone           TEXT,
    city            TEXT,
    postal_code     TEXT,
    country         TEXT,
    payload         JSONB       NOT NULL,   -- enregistrement brut de l'ERP
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)         -- anti-doublon
);

CREATE TABLE IF NOT EXISTS raw.sync_runs (
    run_id         BIGSERIAL   PRIMARY KEY,
    source         TEXT        NOT NULL,
    entity         TEXT        NOT NULL,    -- 'customers' au sprint 1
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'success', 'failed')),
    rows_fetched   INTEGER,
    rows_loaded    INTEGER,
    error_message  
    TEXT );