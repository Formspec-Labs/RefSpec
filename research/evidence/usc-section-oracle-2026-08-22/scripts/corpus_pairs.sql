-- Every distinct parsed (title, section, appendix) the agenda artifact carries,
-- with its row/text/RIN weight. Run 2026-08-22 against the 797,170-row build
-- (agenda-legal-authorities-as-measured-797170.parquet), here as
-- /tmp/silent/AGENDA_SNAPSHOT.parquet.
--
--   duckdb < corpus_pairs.sql
--
-- Emits /tmp/silent/usc_corpus_pairs.parquet: 11,124 pairs, 685,431 rows.

COPY (
  SELECT usc_title AS title, usc_section AS section, usc_appendix AS appendix,
         count(*) AS rows, count(DISTINCT authority_text) AS texts, count(DISTINCT rin) AS rins,
         min(publication_id) AS first_pub, max(publication_id) AS last_pub,
         bool_or(usc_note) AS any_note, bool_and(usc_note) AS all_note,
         bool_or(parse_status='ok') AS any_ok
  FROM '/tmp/silent/AGENDA_SNAPSHOT.parquet'
  WHERE authority_type='usc' AND usc_title IS NOT NULL AND usc_section IS NOT NULL
  GROUP BY 1,2,3
) TO '/tmp/silent/usc_corpus_pairs.parquet' (FORMAT PARQUET);
SELECT count(*) AS pairs, sum(rows) AS rows FROM '/tmp/silent/usc_corpus_pairs.parquet';
