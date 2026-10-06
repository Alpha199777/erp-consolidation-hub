-- Sprint 2 : factures, lignes de facture et articles (couche raw).
-- Memes principes que raw.customers : copie fidele + payload JSON brut,
-- cle (source, source_id), dates de premiere vue et de derniere synchro.

CREATE TABLE IF NOT EXISTS raw.invoices (
    source              TEXT        NOT NULL,
    source_id           TEXT        NOT NULL,
    number              TEXT,
    customer_source_id  TEXT,
    doc_type            TEXT        NOT NULL
                        CHECK (doc_type IN ('invoice', 'credit_note')),
    invoice_date        DATE,
    due_date            DATE,
    status              TEXT,
    currency            TEXT,
    total_excl_tax      NUMERIC(18,4),
    total_incl_tax      NUMERIC(18,4),
    source_modified_at  TIMESTAMPTZ,
    payload             JSONB       NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS raw.invoice_lines (
    source              TEXT        NOT NULL,
    source_id           TEXT        NOT NULL,
    invoice_source_id   TEXT        NOT NULL,
    product_source_id   TEXT,
    description         TEXT,
    quantity            NUMERIC(18,4),
    unit_price          NUMERIC(18,4),
    total_excl_tax      NUMERIC(18,4),
    source_modified_at  TIMESTAMPTZ,
    payload             JSONB       NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

CREATE INDEX IF NOT EXISTS ix_invoice_lines_invoice
    ON raw.invoice_lines (source, invoice_source_id);

CREATE TABLE IF NOT EXISTS raw.items (
    source              TEXT        NOT NULL,
    source_id           TEXT        NOT NULL,
    code                TEXT,
    name                TEXT,
    category            TEXT,
    sale_price          NUMERIC(18,4),
    is_sellable         BOOLEAN,
    source_modified_at  TIMESTAMPTZ,
    payload             JSONB       NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);