-- USL view: shelter_capacity
-- Source: shelters_v4 (shelter occupancy snapshots, UFRGS D1 crisis layers).
-- Grain: one row per shelter snapshot, with derived occupancy_rate / over_capacity_flag.
-- Mirrors app/data/usl.py:shelter_capacity() exactly. See docs/submission/ZETARIS_USL.md.
-- Persistence caveat: see the note in incident_context.sql; the same applies here.
CREATE VIEW shelter_capacity AS
SELECT id, municipality, facility_type, lat, lon, capacity, sheltered_people, vacancies, snapshot_local,
       CASE WHEN capacity IS NOT NULL AND capacity <> '' AND sheltered_people IS NOT NULL AND sheltered_people <> ''
            THEN CAST(sheltered_people AS DOUBLE) / CAST(capacity AS DOUBLE) END AS occupancy_rate,
       CASE WHEN capacity IS NOT NULL AND capacity <> '' AND sheltered_people IS NOT NULL AND sheltered_people <> ''
                 AND CAST(sheltered_people AS DOUBLE) > CAST(capacity AS DOUBLE)
            THEN 1 ELSE 0 END AS over_capacity_flag
FROM OAH_S3.shelters_v4;
