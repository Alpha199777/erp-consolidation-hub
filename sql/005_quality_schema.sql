-- Sprint 4 : couche quality (anomalies detectees, avec statut de resolution).
-- Une anomalie est identifiee par sa regle et son objet : (rule_code, entity_key).
-- Statuts : open (a traiter), fixed (n'est plus detectee), accepted (ignoree a la main).
-- Script rejouable : peut etre lance plusieurs fois sans erreur.

CREATE SCHEMA IF NOT EXISTS quality;

CREATE TABLE IF NOT EXISTS quality.anomalies (
    anomaly_id        BIGSERIAL PRIMARY KEY,
    rule_code         TEXT NOT NULL,
    entity_type       TEXT NOT NULL,
    entity_key        TEXT NOT NULL,
    severity          TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    message           TEXT NOT NULL,
    details           JSONB NOT NULL DEFAULT '{}'::jsonb,
    status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'fixed', 'accepted')),
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_detected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution_note   TEXT,
    UNIQUE (rule_code, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_status
    ON quality.anomalies (status, rule_code);