-- Sprint 2 etape 5 : point de reprise de la synchronisation incrementale.
-- Une ligne par ERP et par entite (customers, items, invoices).
-- Les lignes de facture suivent leur facture : elles n'ont pas de ligne propre.

CREATE TABLE IF NOT EXISTS raw.sync_state (
    source             TEXT        NOT NULL,   -- 'odoo', 'dolibarr', 'erpnext'
    entity             TEXT        NOT NULL,   -- 'customers', 'items', 'invoices'
    watermark          TIMESTAMPTZ,            -- plus grande date de modification vue chez l'ERP
                                               -- (ERPNext : heure du serveur lue comme UTC)
    last_full_sync_at  TIMESTAMPTZ,            -- dernier rechargement complet (suppressions, statuts calcules)
    last_run_id        BIGINT,                 -- dernier run reussi qui a avance le point de reprise
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, entity)
);