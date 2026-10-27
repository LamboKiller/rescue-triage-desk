-- USL view: incident_context
-- Sources: landmarks_v4 (gazetteer, OSM) + streets_flood_v4 (streets + flood exposure attribute).
-- Grain: one row per landmark, enriched with its municipality's flooded-street-segment totals.
-- Mirrors app/data/usl.py:incident_context() exactly, so SAMPLE_MODE and connected mode return
-- the same shape. See docs/submission/ZETARIS_USL.md for the live proof queries and captured output.
--
-- NOTE ON PERSISTENCE: the Zetaris SQL-editor REST endpoint (/sql-editor/sqls/run, the only
-- client this repo is allowed to use) runs each call in its own ephemeral session. This DDL
-- parses and executes against the live engine (verified), but a plain CREATE VIEW does not
-- survive to the next call -- SHOW VIEWS IN OAH_S3 confirms only Schema Store Views created via
-- the Zetaris UI's query_builder persist. tools/zetaris_usl.py --check therefore inlines this
-- view's body as a CTE in the same call as each proving query, which is the only way to exercise
-- it through this REST client. See SPONSOR_GAPS.md for the full explanation.
CREATE VIEW incident_context AS
SELECT l.osm_type, l.osm_id, l.name AS landmark_name, l.category, l.municipality,
       l.street, l.housenumber, l.lat, l.lon,
       l.`in_water_2024-05-06` AS landmark_in_water_0506,
       l.`in_water_2024-05-08` AS landmark_in_water_0508,
       s.flooded_segments AS municipality_flooded_segments_0506,
       s.total_segments AS municipality_total_segments
FROM OAH_S3.landmarks_v4 l
LEFT JOIN (
  SELECT municipality,
         SUM(CAST(segments AS INT)) AS total_segments,
         SUM(CAST(`segments_in_water_2024-05-06` AS INT)) AS flooded_segments
  FROM OAH_S3.streets_flood_v4
  GROUP BY municipality
) s ON l.municipality = s.municipality;
