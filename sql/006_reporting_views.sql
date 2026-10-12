-- Sprint 5.1 : couche reporting (vues pour Power BI). Lecture seule, rejouable.
CREATE SCHEMA IF NOT EXISTS reporting;

-- Un client unifie = une ligne, avec les ERP ou il existe.
CREATE OR REPLACE VIEW reporting.dim_customer AS
SELECT
    c.customer_id,
    c.name,
    c.email,
    c.postal_code,
    c.city,
    c.country_code,
    COUNT(DISTINCT l.source)                           AS erp_count,
    STRING_AGG(DISTINCT l.source, ', ' ORDER BY l.source) AS erp_list
FROM core.customers c
LEFT JOIN core.customer_links l ON l.customer_id = c.customer_id
GROUP BY c.customer_id, c.name, c.email, c.postal_code, c.city, c.country_code;

-- Une facture = une ligne. customer_id est NULL si la facture n'a pas de client unifie.
-- total_excl_tax / total_incl_tax : montants de l'ERP, tels quels (un avoir Odoo est positif).
-- signed_total_excl_tax : meme montant, negatif pour un avoir (doc_type = 'credit_note').
-- Regle verifiee seulement pour Odoo : Dolibarr et ERPNext n'ont aucun avoir dans les donnees.
-- Aucune conversion de devise : ne jamais additionner entre devises (colonne currency).
CREATE OR REPLACE VIEW reporting.fact_invoice AS
SELECT
    i.source,
    i.source_id,
    i.source || ':' || i.source_id AS invoice_key,
    i.number,
    l.customer_id,
    i.doc_type,
    i.invoice_date,
    i.due_date,
    i.status,
    i.currency,
    i.total_excl_tax,
    i.total_incl_tax,
    CASE WHEN i.doc_type = 'credit_note' THEN -i.total_excl_tax
         ELSE i.total_excl_tax END AS signed_total_excl_tax
FROM raw.invoices i
LEFT JOIN core.customer_links l
       ON l.source = i.source
      AND l.source_id = i.customer_source_id;

-- Calendrier couvrant les dates de factures, annees completes.
CREATE OR REPLACE VIEW reporting.dim_date AS
SELECT
    d::date                          AS date,
    EXTRACT(YEAR FROM d)::int        AS year,
    EXTRACT(MONTH FROM d)::int       AS month,
    TO_CHAR(d, 'YYYY-MM')            AS year_month
FROM GENERATE_SERIES(
        (SELECT DATE_TRUNC('year', MIN(LEAST(invoice_date, COALESCE(due_date, invoice_date)))) FROM raw.invoices),
        (SELECT DATE_TRUNC('year', MAX(GREATEST(invoice_date, COALESCE(due_date, invoice_date)))) + INTERVAL '1 year - 1 day' FROM raw.invoices),
        INTERVAL '1 day'
     ) AS d;

-- Anomalies telles que suivies par la couche quality.
CREATE OR REPLACE VIEW reporting.anomalies AS
SELECT
    anomaly_id,
    rule_code,
    entity_type,
    entity_key,
    severity,
    CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END AS severity_rank,
    message,
    status,
    first_detected_at,
    last_detected_at,
    resolved_at
FROM quality.anomalies;