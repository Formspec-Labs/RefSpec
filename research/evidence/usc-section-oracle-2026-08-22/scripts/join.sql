-- Join the parsed corpus pairs against the U.S.C. section-existence oracle.

CREATE OR REPLACE MACRO seckey(s) AS {
  'n': CAST(COALESCE(NULLIF(regexp_extract(s, '^([0-9]+)', 1), ''), '0') AS BIGINT),
  's': regexp_replace(s, '^[0-9]+', '')
};

CREATE OR REPLACE TABLE ora_exact AS
  SELECT title, section, min(status) AS status, bool_or(status = 'current') AS live
  FROM '/tmp/silent/usc_oracle_exact.parquet' GROUP BY 1,2;

CREATE OR REPLACE TABLE ora_rng AS
  SELECT title, lo, hi, status, raw, seckey(lo) AS klo, seckey(hi) AS khi
  FROM '/tmp/silent/usc_oracle_ranges.parquet';

CREATE OR REPLACE TABLE ora_ann AS SELECT * FROM '/tmp/silent/usc_oracle_annual.parquet';

CREATE OR REPLACE TABLE ora_ann_rng AS
  SELECT year, title, appendix, lo, hi, seckey(lo) AS klo, seckey(hi) AS khi
  FROM '/tmp/silent/usc_oracle_annual_rng.parquet';

CREATE OR REPLACE TABLE pairs AS SELECT * FROM '/tmp/silent/usc_corpus_pairs.parquet';

CREATE OR REPLACE TABLE verdict AS
SELECT
  p.*,
  e.status                                          AS cur_status,
  e.title IS NOT NULL                               AS in_current,
  EXISTS (SELECT 1 FROM ora_rng r
          WHERE r.title = p.title AND NOT p.appendix
            AND r.klo <= seckey(p.section) AND seckey(p.section) <= r.khi) AS in_current_range,
  COALESCE((SELECT list(DISTINCT a.year ORDER BY a.year) FROM ora_ann a
     WHERE a.title = p.title AND a.appendix = p.appendix AND a.section = p.section), []) AS annual_years,
  COALESCE((SELECT list(DISTINCT r.year ORDER BY r.year) FROM ora_ann_rng r
     WHERE r.title = p.title AND r.appendix = p.appendix
       AND r.klo <= seckey(p.section) AND seckey(p.section) <= r.khi), []) AS annual_rng_years
FROM pairs p
LEFT JOIN ora_exact e ON e.title = p.title AND e.section = p.section AND NOT p.appendix;

CREATE OR REPLACE TABLE verdict2 AS
SELECT *,
  COALESCE(in_current,false) OR COALESCE(in_current_range,false)
    OR len(annual_years) > 0 OR len(annual_rng_years) > 0 AS exists_anywhere,
  COALESCE(in_current,false) AND cur_status = 'current'   AS live_now
FROM verdict;
