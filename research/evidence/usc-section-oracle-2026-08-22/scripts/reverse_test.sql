-- The reverse test: values written "NN U.S. XXX" / "NN US XXX" (the "C" lost),
-- whatever they parsed as, joined to the section oracle.
-- Run 2026-08-22:  duckdb /tmp/silent/usc.duckdb < reverse_test.sql
-- Result: 12 distinct texts / 22 rows; 12/12 name a real section;
--   2 texts / 6 rows parse as case_citation/ok (40 U.S. 550, 43 U.S. 1763),
--   1 text / 4 rows parses usc/partial and drops the head (49 US 106(g), ...),
--   9 texts / 12 rows fail loudly as other/failed.

CREATE OR REPLACE TABLE usdot AS
SELECT authority_text, authority_type, parse_status, case_volume, case_page,
       regexp_extract(authority_text, '^\s*([0-9]{1,2})\s*U\.?\s?S\.?\s+([0-9][0-9a-zA-Z\-]*)', 1) AS t,
       lower(regexp_extract(authority_text, '^\s*([0-9]{1,2})\s*U\.?\s?S\.?\s+([0-9][0-9a-zA-Z\-]*)', 2)) AS s,
       count(*) AS rows, count(DISTINCT rin) AS rins, min(publication_id) AS fp, max(publication_id) AS lp
FROM '/tmp/silent/AGENDA_SNAPSHOT.parquet'
WHERE regexp_matches(authority_text, '^\s*[0-9]{1,2}\s*U\.?\s?S\.?\s+[0-9]')
GROUP BY ALL;

SELECT u.authority_type, u.parse_status, u.authority_text, u.t, u.s, u.rows, u.rins, u.fp, u.lp,
       (e.title IS NOT NULL) AS section_is_real, e.status
FROM usdot u LEFT JOIN ora_exact e ON e.title=TRY_CAST(u.t AS INT) AND e.section=u.s
ORDER BY u.rows DESC;
