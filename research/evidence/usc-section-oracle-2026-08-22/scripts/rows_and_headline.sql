-- After `duckdb /tmp/silent/usc.duckdb -c ".read join.sql"`:
-- join every agenda row back to its verdict, then the headline counts.
-- Run 2026-08-22:  duckdb /tmp/silent/usc.duckdb < rows_and_headline.sql

CREATE OR REPLACE TABLE rowsv AS
SELECT l.*, v.exists_anywhere, v.annual_years, v.annual_rng_years, v.cur_status,
       v.in_current, v.in_current_range, v.live_now
FROM '/tmp/silent/AGENDA_SNAPSHOT.parquet' l
JOIN verdict2 v ON v.title=l.usc_title AND v.section=l.usc_section AND v.appendix=l.usc_appendix
WHERE l.authority_type='usc' AND l.usc_title IS NOT NULL AND l.usc_section IS NOT NULL;

SELECT count(*) AS joined FROM rowsv;                       -- 685431

SELECT exists_anywhere, appendix, count(*) AS pairs, sum(rows) AS rows
FROM verdict2 GROUP BY ALL ORDER BY 1,2;
--  false false 1683 17805 / false true 45 312 / true false 9302 664095 / true true 94 3219

SELECT
 (SELECT count(DISTINCT authority_text) FROM rowsv WHERE NOT exists_anywhere) AS texts_miss,   -- 2372
 (SELECT count(*)                       FROM rowsv WHERE NOT exists_anywhere) AS rows_miss,    -- 18117
 (SELECT count(DISTINCT authority_text) FROM rowsv)                           AS texts_all,    -- 30858
 (SELECT count(*)                       FROM rowsv)                           AS rows_all,     -- 685431
 (SELECT count(DISTINCT rin)            FROM rowsv WHERE NOT exists_anywhere) AS rins_miss,    -- 2622
 (SELECT count(DISTINCT rin)            FROM rowsv)                           AS rins_all,     -- 42207
 (SELECT count(*) FROM verdict2 WHERE NOT exists_anywhere)                    AS miss_pairs,   -- 1728
 (SELECT count(*) FROM verdict2)                                              AS all_pairs;    -- 11124

SELECT parse_status, count(*) AS rows, count(DISTINCT authority_text) AS texts
FROM rowsv WHERE NOT exists_anywhere GROUP BY 1 ORDER BY rows DESC;
--  ok 13612 / 1508 ; partial 4485 / 860 ; corroborated 20 / 4

SELECT authority_text, usc_title, usc_section, corroboration_rule, count(*) AS n
FROM rowsv WHERE NOT exists_anywhere AND parse_status='corroborated' GROUP BY ALL ORDER BY n DESC;
