# Zetaris Unified Semantic Layer — use case, sources, construction, proof

All SQL below was executed live on 2026-10-27 against the local Zetaris stack (`zetaris-api-1`,
`zetaris-ndp-driver`, `zetaris-postgres-1`, `oah-s3` — all `docker ps healthy`) through the
repo's own client (`app/data/zetaris.py:Zetaris.query`), the only client this review used.
No credentials or raw provider bodies are reproduced; row excerpts below are real data,
truncated for length. Full captured JSON: `data/zetaris_usl_last_check.json`
(written by `tools/zetaris_usl.py --check`) and the exploratory-query dump kept with this
review's build artifacts.

## 1a. Use case and data sources

**Use case.** A dispatcher triaging flood rescue requests needs, for one place, one glance:
*is it flooded, is the nearest infrastructure asset up, is there shelter capacity nearby.*
Today that join happens by hand across five CSVs loaded independently into the running app
(`app/data/source.py`). The USL below expresses the same three joins once, in SQL, over the
same tables Zetaris already has loaded — so an analyst (or a future UI) can ask the question
directly instead of writing Python.

**Sources onboarded (5, ≥3 required), all in `OAH_S3` via `tools/load_zetaris.py --version v4`:**

| Source | Zetaris table | Rows | Kind |
|---|---|---:|---|
| Landmarks (gazetteer) | `landmarks_v4` | 4,201 | OSM Overpass |
| Streets + flood exposure | `streets_flood_v4` | 12,586 | OSM + UFRGS/Copernicus flood attribute |
| Shelters (capacity snapshots) | `shelters_v4` | 7,574 | UFRGS D1 crisis layers |
| Infrastructure assets (pumps + daily status) | `pumps_v4` (38) + `pump_status_daily_v4` (988) | 1,026 | UFRGS D1 crisis layers |
| Intake journal (citizen messages) | `messages_seed7_v4` | 15 | Synthetic (flagged) |

Evidence these are the real, already-onboarded v4 tables: `data/zetaris_tables.json` (row counts
written by the load), and `SHOW TABLES IN OAH_S3` (ran live, 23 tables incl. all of the above).

## 1b. Onboarding verification + exploratory queries (2–3 per source, real results)

**Landmarks.**
```sql
SELECT category, COUNT(*) AS n FROM OAH_S3.landmarks_v4 GROUP BY category ORDER BY n DESC LIMIT 8;
```
→ `leisure:park 934`, `amenity:school 694`, `amenity:place_of_worship 430`, `amenity:pharmacy 328`, …
```sql
SELECT municipality, COUNT(*) AS flooded_landmarks FROM OAH_S3.landmarks_v4
WHERE `in_water_2024-05-06`='1' GROUP BY municipality ORDER BY flooded_landmarks DESC LIMIT 8;
```
→ `Porto Alegre 611`, `Canoas 252`, `São Leopoldo 93`, `Eldorado do Sul 59`, `Guaíba 35`, `Novo Hamburgo 21`.
```sql
SELECT name, municipality, street, housenumber FROM OAH_S3.landmarks_v4
WHERE LOWER(name) LIKE '%rodoviaria%' OR LOWER(name) LIKE '%rodoviária%' LIMIT 5;
```
→ 5 bus stations/related records across 4 municipalities (Novo Hamburgo, Canoas, Porto Alegre ×2, São Leopoldo).

**Streets + flood exposure.**
```sql
SELECT COUNT(*) AS n, COUNT(DISTINCT municipality) AS municipios FROM OAH_S3.streets_flood_v4;
```
→ `12586, 6`.
```sql
SELECT municipality, SUM(CAST(segments AS INT)) AS total_segments,
       SUM(CAST(`segments_in_water_2024-05-06` AS INT)) AS flooded_segments
FROM OAH_S3.streets_flood_v4 GROUP BY municipality ORDER BY flooded_segments DESC LIMIT 8;
```
→ `Porto Alegre 19742/4514`, `Canoas 3632/1345`, `São Leopoldo 3171/1187`, `Eldorado do Sul 643/452`, …

**Shelters.**
```sql
SELECT municipality, COUNT(*) AS n, SUM(CAST(capacity AS DOUBLE)) AS total_capacity
FROM OAH_S3.shelters_v4 WHERE municipality IS NOT NULL GROUP BY municipality ORDER BY n DESC LIMIT 8;
```
→ `Porto Alegre 2047` (capacity blank for this snapshot batch), `São Leopoldo 709/4922`, `Canoas 559/28030`, …
```sql
SELECT COUNT(*) FROM OAH_S3.shelters_v4
WHERE capacity IS NOT NULL AND capacity<>'' AND sheltered_people IS NOT NULL AND sheltered_people<>''
  AND CAST(sheltered_people AS DOUBLE) > CAST(capacity AS DOUBLE);
```
→ `62` (this becomes the data-quality rule in §1c).

**Infrastructure assets (pumps).**
```sql
SELECT status, COUNT(*) AS n FROM OAH_S3.pump_status_daily_v4 GROUP BY status ORDER BY n DESC;
```
→ `APURAR 569`, `Inoperante 264`, `Operante 153`, `Parcial 2`.
```sql
SELECT p.name, p.municipality, d.status FROM OAH_S3.pumps_v4 p
JOIN OAH_S3.pump_status_daily_v4 d ON p.source_fid=d.source_fid
WHERE d.date='2024-05-06' AND d.status<>'APURAR' LIMIT 10;
```
→ 10 Porto Alegre pump stations, mixed `Operante`/`Inoperante` on the day of the event.

**Intake journal (messages).**
```sql
SELECT COUNT(*) AS n FROM OAH_S3.messages_seed7_v4;
```
→ `15`. Sample row: `synthetic-seed7-000, 2024-05-06T12:00:00-03:00, "oi gnt, somos 5 pesssoas na Beco Lami, número 676, Porto Alegre. 1 cachorros. água subindo!"`.

## 1c. The USL: construction, verification, showcase

**DDL:** `sql/usl/incident_context.sql`, `sql/usl/asset_availability.sql`, `sql/usl/shelter_capacity.sql`.

- `incident_context` — `landmarks_v4` LEFT JOIN a per-municipality aggregate of `streets_flood_v4`
  (flooded/total street segments). One row per landmark, is-it-flooded at both the point and the
  municipality level.
- `asset_availability` — `pumps_v4` JOIN `pump_status_daily_v4` on `source_fid`. One row per pump
  per observed day, with a derived `is_down` flag.
- `shelter_capacity` — `shelters_v4` alone, with derived `occupancy_rate` and `over_capacity_flag`.

**Persistence caveat (do not overclaim).** The only sanctioned client here is the SQL-editor REST
endpoint (`/sql-editor/sqls/run`). Each call runs in its own ephemeral session: a plain
`CREATE VIEW` parses and executes without error (verified), but a **second** call cannot see it —
confirmed by creating a view, then immediately running `SELECT * FROM it` in a separate call (HTTP
400, unknown relation) and `SHOW TABLES IN OAH_S3` (not listed). `SHOW VIEWS IN OAH_S3` does list
one object — `PIKACHU_ABILITIES_TABLE`, generator `query_builder` — confirming persisted "Schema
Store Views" exist in this Zetaris build, but only via the product UI's semantic-layer builder
(`zetaris-ui-1`, port 3000), not via arbitrary SQL text on this REST path. `CREATE SCHEMASTORE VIEW
... WITH CONTAINER ...` partially parsed (got past `AS` to a `CONTAINER` keyword) but we stopped
probing undocumented DDL rather than guess a destructive variant. **Fix / next step for whoever has
UI access:** build the same three views through the Zetaris UI's query builder so they persist as
Schema Store Views; `sql/usl/*.sql` is ready to paste in.

Given that constraint, `tools/zetaris_usl.py --check` proves each view is *active* the only way this
REST client allows: it inlines the view's body as a CTE in the same call as each proving query, so
every query below executes against live Zetaris, through the view's real join logic, in one request.

**Proving queries, real results (`tools/zetaris_usl.py --check`, 2026-10-27):**

| View | Query | Result |
|---|---|---|
| `incident_context` | rodoviária landmarks + their municipality's flood exposure | 5 rows, incl. `Rodoviária, Porto Alegre, in_water_0506=1, municipality_flooded_segments=4514` |
| `incident_context` | flooded landmarks in Canoas, 05-06 | 5 rows (of 252), e.g. `Agafarma (pharmacy), flooded_segments=1345` |
| `incident_context` | landmark count + flooded segments per municipality | `Porto Alegre 2776 landmarks/4514 segments`, `Canoas 590/1345`, `São Leopoldo 312/1187`, … |
| `asset_availability` | pumps down on 05-06 | 8 of 10 rows shown, e.g. `EBAP_PA_CB 04_Paque Nautico, Porto Alegre, Inoperante` |
| `asset_availability` | down-days per municipality | `Porto Alegre 264 down-days / 598 rows`; all other municipalities `0` |
| `shelter_capacity` | shelters over capacity, worst first | top row: `capacity=1.0, sheltered_people=75.0, occupancy_rate=75.0` |

**Data-quality rule that executes (`sql/usl/dq_rules.sql`):**

```sql
SELECT COUNT(*) AS checked, COUNT(*) FILTER (WHERE over_capacity_flag=1) AS violations
FROM (<shelter_capacity body>) v WHERE capacity IS NOT NULL AND capacity<>'';
```
→ **`checked=734, violations=62`** — 62 shelter snapshots report more sheltered people than stated
capacity. A second rule (coordinates inside the RS bounding box) runs clean: `checked=4201,
violations=0`. Both executed live; full rows for the 62 violations are in
`data/zetaris_usl_last_check.json`.

## Reproduce

```powershell
python tools/zetaris_usl.py --build   # submits each view's DDL; proves it parses/executes live
python tools/zetaris_usl.py --check   # runs the proving queries + DQ rules; writes data/zetaris_usl_last_check.json
python -m unittest discover -s tests -p "test_zetaris_usl.py" -v   # offline parity check (SAMPLE_MODE), no network
```
The offline test asserts the SAMPLE_MODE computation (`app/data/usl.py`, reading the same local
CSVs that were uploaded) returns the **exact same numbers** as the live Zetaris run above
(734/62, Canoas 252, Porto Alegre 4514 segments, 10 pumps down on 05-06) — proof the two paths
compute one semantic layer, not two.
