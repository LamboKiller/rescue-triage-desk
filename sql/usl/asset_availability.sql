-- USL view: asset_availability
-- Sources: pumps_v4 (infrastructure asset register) + pump_status_daily_v4 (daily status feed).
-- Grain: one row per pump asset per observed day, with a derived is_down flag.
-- Mirrors app/data/usl.py:asset_availability() exactly. See docs/submission/ZETARIS_USL.md.
-- Persistence caveat: see the note in incident_context.sql; the same applies here.
CREATE VIEW asset_availability AS
SELECT p.source_fid, p.name AS asset_name, p.municipality, p.lat, p.lon,
       d.date AS status_date, d.status,
       CASE WHEN d.status = 'Inoperante' THEN 1 ELSE 0 END AS is_down
FROM OAH_S3.pumps_v4 p
JOIN OAH_S3.pump_status_daily_v4 d ON p.source_fid = d.source_fid;
