PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS source_batches (
 season TEXT PRIMARY KEY, url TEXT NOT NULL, fetched_utc TEXT, source_sha256 TEXT,
 raw_rows INTEGER NOT NULL DEFAULT 0, retained_observations INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK (status IN ('loaded','failed')), message TEXT
);
CREATE TABLE IF NOT EXISTS weekly_surveillance (
 season TEXT NOT NULL, week_date TEXT NOT NULL, epiweek INTEGER,
 geography TEXT NOT NULL, geography_source TEXT NOT NULL,
 indicator TEXT NOT NULL, positive_tests REAL, tests_performed REAL,
 source_issue TEXT, source_url TEXT NOT NULL,
 PRIMARY KEY (season, week_date, geography, indicator),
 FOREIGN KEY (season) REFERENCES source_batches(season),
 CHECK (positive_tests IS NULL OR positive_tests >= 0),
 CHECK (tests_performed IS NULL OR tests_performed >= 0)
);
CREATE INDEX IF NOT EXISTS idx_weekly_geo_indicator ON weekly_surveillance(geography,indicator,season,week_date);
CREATE TABLE IF NOT EXISTS validation_issues (
 id INTEGER PRIMARY KEY, season TEXT, week_date TEXT, geography TEXT,
 indicator TEXT, issue_code TEXT NOT NULL, detail TEXT
);
CREATE VIEW IF NOT EXISTS v_weekly_reporting AS
SELECT season,week_date,epiweek,geography,geography_source,indicator,
 positive_tests,tests_performed,
 CASE WHEN tests_performed > 0 AND positive_tests IS NOT NULL
 THEN ROUND(100.0 * positive_tests/tests_performed,3) END AS positivity_pct
FROM weekly_surveillance;
CREATE VIEW IF NOT EXISTS v_season_reporting AS
SELECT season,geography,geography_source,indicator,
 SUM(positive_tests) AS positive_tests,
 SUM(CASE WHEN positive_tests IS NOT NULL AND tests_performed > 0 THEN tests_performed END) AS tests_performed,
 COUNT(CASE WHEN positive_tests IS NOT NULL AND tests_performed > 0 THEN 1 END) AS reported_weeks,
 CASE WHEN SUM(CASE WHEN positive_tests IS NOT NULL AND tests_performed > 0 THEN tests_performed END) > 0
 THEN ROUND(100.0 * SUM(CASE WHEN tests_performed > 0 THEN positive_tests END) /
 SUM(CASE WHEN positive_tests IS NOT NULL AND tests_performed > 0 THEN tests_performed END),3) END AS positivity_pct
FROM weekly_surveillance
WHERE positive_tests IS NOT NULL AND tests_performed > 0
GROUP BY season,geography,geography_source,indicator;
