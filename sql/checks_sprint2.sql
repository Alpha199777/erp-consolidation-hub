-- Sprint 2 : controles de la couche raw (LECTURE SEULE, que des SELECT).

\echo
\echo === 1. Volumes par table et par ERP ===
SELECT 'customers' AS table_raw, source, count(*) AS lignes FROM raw.customers GROUP BY source
UNION ALL
SELECT 'items', source, count(*) FROM raw.items GROUP BY source
UNION ALL
SELECT 'invoices', source, count(*) FROM raw.invoices GROUP BY source
UNION ALL
SELECT 'invoice_lines', source, count(*) FROM raw.invoice_lines GROUP BY source
ORDER BY 1, 2;

\echo
\echo === 2. Doublons sur (source, source_id), attendu : 0 ligne ===
SELECT 'customers' AS table_raw, source, source_id, count(*) AS n
FROM raw.customers GROUP BY source, source_id HAVING count(*) > 1
UNION ALL
SELECT 'items', source, source_id, count(*)
FROM raw.items GROUP BY source, source_id HAVING count(*) > 1
UNION ALL
SELECT 'invoices', source, source_id, count(*)
FROM raw.invoices GROUP BY source, source_id HAVING count(*) > 1
UNION ALL
SELECT 'invoice_lines', source, source_id, count(*)
FROM raw.invoice_lines GROUP BY source, source_id HAVING count(*) > 1;

\echo
\echo === 3. Lignes sans facture, attendu : 0 ===
SELECT l.source, count(*) AS lignes_sans_facture
FROM raw.invoice_lines l
LEFT JOIN raw.invoices i
  ON i.source = l.source AND i.source_id = l.invoice_source_id
WHERE i.source_id IS NULL
GROUP BY l.source;

\echo
\echo === 4. Lignes sans produit (texte libre) par ERP ===
SELECT source, count(*) AS lignes_sans_produit
FROM raw.invoice_lines
WHERE product_source_id IS NULL
GROUP BY source
ORDER BY source;

\echo
\echo === 5. Lignes dont le produit est absent de raw.items, attendu : 0 ===
SELECT l.source, count(*) AS produits_absents,
       min(l.product_source_id) AS exemple
FROM raw.invoice_lines l
LEFT JOIN raw.items it
  ON it.source = l.source AND it.source_id = l.product_source_id
WHERE l.product_source_id IS NOT NULL AND it.source_id IS NULL
GROUP BY l.source;

\echo
\echo === 6. Clients de factures absents de raw.customers, attendu : 0 ===
SELECT i.source, count(*) AS factures_client_absent,
       min(i.customer_source_id) AS exemple
FROM raw.invoices i
LEFT JOIN raw.customers c
  ON c.source = i.source AND c.source_id = i.customer_source_id
WHERE i.customer_source_id IS NOT NULL AND c.source_id IS NULL
GROUP BY i.source;

\echo
\echo === 7. Factures par ERP, type, statut et devise ===
SELECT source, doc_type, status, currency, count(*) AS n,
       sum(total_incl_tax) AS total_ttc
FROM raw.invoices
GROUP BY source, doc_type, status, currency
ORDER BY source, doc_type, status;

\echo
\echo === 8. Signe des montants des avoirs (point ouvert) ===
SELECT source, doc_type, count(*) AS n,
       min(total_incl_tax) AS min_ttc, max(total_incl_tax) AS max_ttc
FROM raw.invoices
GROUP BY source, doc_type
ORDER BY source, doc_type;

\echo
\echo === 9. Total HT de la facture contre somme de ses lignes (ecart > 0.01) ===
SELECT i.source, count(*) AS factures_en_ecart
FROM raw.invoices i
LEFT JOIN (
    SELECT source, invoice_source_id, sum(total_excl_tax) AS somme_lignes
    FROM raw.invoice_lines
    GROUP BY source, invoice_source_id
) s ON s.source = i.source AND s.invoice_source_id = i.source_id
WHERE abs(coalesce(i.total_excl_tax, 0) - coalesce(s.somme_lignes, 0)) > 0.01
GROUP BY i.source;

\echo
\echo === 10. Journal : runs par ERP, entite et statut ===
SELECT source, entity, status, count(*) AS runs,
       min(run_id) AS premier_run, max(run_id) AS dernier_run
FROM raw.sync_runs
GROUP BY source, entity, status
ORDER BY source, entity, status;

\echo
\echo === 11. Ecart Odoo : clients et date de premiere vue ===
SELECT source_id, name, first_seen_at, last_synced_at
FROM raw.customers
WHERE source = 'odoo'
ORDER BY first_seen_at, source_id;