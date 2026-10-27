-- USL data-quality rules, executed by tools/zetaris_usl.py --check.
--
-- Rule 1 (primary; finds real violations): shelter occupancy must not exceed stated capacity.
-- Live run 2026-10-27 against shelters_v4 via shelter_capacity: 734 rows had a non-blank capacity;
-- 62 of them report sheltered_people > capacity. See docs/submission/ZETARIS_USL.md for the
-- full captured output (ids, municipality, capacity, sheltered_people, occupancy_rate).
SELECT COUNT(*) AS checked,
       COUNT(*) FILTER (WHERE over_capacity_flag = 1) AS violations
FROM (SELECT * FROM shelter_capacity) v
WHERE capacity IS NOT NULL AND capacity <> '';

-- Rule 2 (bonus; passes clean at last run, 0/4201 violations): every landmark's coordinates
-- fall inside the Rio Grande do Sul bounding box (lat -34..-27, lon -58..-49).
SELECT COUNT(*) AS checked,
       COUNT(*) FILTER (WHERE CAST(lat AS DOUBLE) NOT BETWEEN -34 AND -27
                           OR CAST(lon AS DOUBLE) NOT BETWEEN -58 AND -49) AS violations
FROM OAH_S3.landmarks_v4;
