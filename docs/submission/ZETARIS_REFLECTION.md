# Zetaris reflection — honest, not a pitch

## 2a. Did the USL save time vs. hand-coding, and what did a hand-coded comparison show?

We built both, for the same join (`incident_context`: landmarks × per-municipality flood-segment
totals), so the comparison below is measured, not estimated:

| | `sql/usl/incident_context.sql` | `app/data/usl.py:incident_context()` (stdlib Python) |
|---|---|---|
| Lines | 14 (incl. the join) | 20 (incl. the aggregation loop) |
| Time to first working version | ~10 min, mostly spent discovering Zetaris's DDL dialect (see §1c persistence caveat) | ~8 min: `csv.DictReader`, a `dict` accumulator, one comprehension |
| Re-running with a changed filter (e.g. "only São Leopoldo") | append one `WHERE` clause, re-run | add a filter argument or a list comprehension over the already-returned rows |

**Honest conclusion:** for *this* join, over data this small (4,201 × 12,586 rows), hand-coding in
Python stdlib was not slower to write, and it is what we actually ship (`app/data/usl.py` is the
code path; the SQL view cannot persist through this REST client — §1c). The USL's measured time
win was somewhere else: the **2–3 exploratory queries per source** in `ZETARIS_USL.md` (§1b) each
took one `query()` call and a few seconds; the Python equivalent of each one-off question (e.g.
"which bus-station-named landmarks exist") would have been a disposable script every time. A
semantic layer's value is in ad hoc interrogation, not in replacing a join we already had to write
once for the app. We are not claiming more than that.

## 2b. Would the USL help (or not help) in our actual work?

**Would help:** ad hoc cross-referencing for someone without app code access — "which pumps are
down in Canoas right now" is one query instead of a deploy. It would also be the natural place to
add a fourth or fifth source (e.g. real fleet telemetry) without touching `app/data/source.py`.

**Would not help, today, for the triage hot path:** every dispatch decision in this app must point
to an exact line of deterministic code and an exact fact id (`CLAUDE.md`-equivalent project rule,
see `app/pipeline.py`, `app/decide.py`). A SQL semantic layer we cannot re-verify offline
(SAMPLE_MODE has no network) and cannot unit-test deterministically would weaken, not strengthen,
that guarantee — and the REST endpoint's statelessness (§1c: views don't survive a second call)
means it cannot be the durable source of truth without caching every result locally anyway, which
is exactly what `LocalSource`/`ZetarisSource` already do. So the USL's natural home in this
project is analyst tooling (`tools/zetaris_usl.py`) and a documented, testable Python mirror
(`app/data/usl.py`), not a dependency the pipeline calls at request time.

**Bonus — forecast for a concrete project:** if Zetaris's persisted Schema Store Views were
reachable from this SQL-text client (not just the UI query builder), a "best shelter for this
case" feature (shelter_capacity × haversine distance to the incident) would save an estimated
2–3 hours versus hand-coding the distance join and keeping it in sync with five CSV reloads by
hand — mostly because the distance/ranking logic would live in one place instead of being
re-derived in Python each time a new hazard source is added.

## 2c. As a PM: one requirement that would make the USL stronger

**Requirement:** *persisted views reachable from the SQL-text REST API*, not only from the UI's
query builder. Today, `CREATE VIEW` executes successfully (confirmed: HTTP 200, no error) but is
gone on the very next call — we proved this by creating a view and then immediately failing to
`SELECT` from it, qualified or not, and confirming it is absent from `SHOW TABLES IN OAH_S3`. For a
stateless backend client (which is what most production integrations are), a persisted,
nameable view is the difference between "a semantic layer" and "a query template library." Without
it, every consumer must either re-paste the view body into every query (what
`tools/zetaris_usl.py` does) or maintain its own cache (what this app already does with
`LocalSource`/`ZetarisSource`) — in both cases, the USL stops being the single source of truth.

**Bonus — example feature + mocked USL for it:** a dispatcher-facing "nearest open shelter for
this case" suggestion. Mocked (not executed — needs a distance function we have not confirmed
Zetaris supports, so this is deliberately a sketch, not a claim):

```sql
-- MOCK, NOT EXECUTED: sketch of what the PM requirement above would unlock.
CREATE SCHEMASTORE VIEW shelter_recommendation WITH CONTAINER usl AS
SELECT i.osm_id AS incident_landmark_id, i.municipality, s.id AS shelter_id,
       s.capacity, s.sheltered_people, s.vacancies,
       haversine_km(i.lat, i.lon, s.lat, s.lon) AS distance_km
FROM incident_context i
JOIN shelter_capacity s ON s.municipality = i.municipality
WHERE s.over_capacity_flag = 0
ORDER BY distance_km;
```
If the requirement above shipped, this view would let a dispatcher ask "where do I send these
people" as one persisted query instead of three Python calls plus a distance function maintained
in `app/geo/`.
