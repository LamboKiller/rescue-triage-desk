# Map API contract — V2-A

`GET /api/map?date=YYYY-MM-DD` returns `200 application/json; charset=utf-8`.
Exactly one valid ISO calendar date is required; missing, duplicate or invalid
dates return `400 {"error":"..."}`. Dates outside May 2024 are accepted with
the selection rules below. No request writes registry state. Headers include
`Cache-Control: no-store`, `Vary: Accept-Encoding` and `Content-Length`.
When gzip is accepted with a positive quality value, the body is gzip-compressed
and `Content-Encoding: gzip` is sent. `gzip;q=0` disables compression.
Coordinates are WGS84 `[longitude, latitude]`; distances are meters unless named
`distance_km`. The prepared May 8 response is below 6,000,000 uncompressed bytes
with the test case queue. Case arrays grow with registry history.

```json
{
  "date": "2024-05-08",
  "layers": {
    "flood": {"type":"FeatureCollection","features":[
      {"type":"Feature","id":"flood_observed.geojson:0",
       "geometry":{"type":"MultiPolygon","coordinates":[[[[-51.22,-30.02],[-51.21,-30.02],[-51.21,-30.01],[-51.22,-30.02]]]]},
       "properties":{"observation_date":"2024-05-08","source":"flood_observed.geojson","source_layer":"...","publication_available":false}}
    ]},
    "closures": {"type":"FeatureCollection","features":[]},
    "pumps": {"type":"FeatureCollection","features":[]},
    "events": {"type":"FeatureCollection","features":[]},
    "shelters": {"type":"FeatureCollection","features":[]},
    "levees": {"type":"FeatureCollection","features":[]}
  },
  "cases": [{
    "case_id":"example-id","decision":"REVIEW_REQUIRED","priority":8,
    "lat":-30.022194,"lon":-51.2198891,"position_kind":"landmark",
    "hazards":{"in_flood_extent":false,"flood_observed_date":"2024-05-08",
      "depth_m":null,"depth_source":"pending (depth research)",
      "closures_nearby":0,"pumps_nearby":10,"events_nearby":3,"nearest_shelters":0}
  }]
}
```

This example is trimmed and illustrative; the displayed polygon is not measured
source geometry. All six layer keys and `cases` are always present. Empty layers
use an empty `features` array. Every feature has `type`, a stable string `id`,
`geometry`, and `properties`. Source feature order is deterministic. JSON null
means unknown or unavailable, never zero. Strings are UTF-8.

| Layer | Geometry and property contract | Date selection | Suggested styling |
|---|---|---|---|
| flood | MultiPolygon; `observation_date`, `source` filename, `source_layer`, `publication_available:false` | Latest observation date <= requested date; both observed-water and Copernicus products for that date, no accumulation. Empty before May 6. | Blue `#2563eb`, 25% fill; product overlaps may exist. |
| closures | MultiLineString or null when unmatched; all source CSV fields: `record_id`, `road`, `segment`, `from_date`, `to_date`, `status`, `transport_mode`, `from_date_basis`, `to_date_basis`, `direction`, `vehicle_scope`, `source_published_at`, `source_id`, `source`, `source_locator`, `quality_notes`, `geometry_status`; also `closure_extent_verified:false`, `routing_safe:false` | Nonempty published date <= requested date AND from_date <= date AND (empty to_date OR date <= to_date), inclusive endpoints. An unknown end remains open-ended; this is not proof of continuing closure. | `closed`, `closed_at_observation`, `closed_direction_only`, `service_suspended`, `flights_suspended`: red `#dc2626`; `restricted_emergency_route`, `restricted_flooding`, `closed_then_emergency_only`, `scheduled_total_closure`: amber `#d97706`; `reported_alternative_open`, `reopened_direction_only`, `reopened`: green `#16a34a`; unknown values: gray `#64748b`. Dashed lines for unverified candidates. |
| pumps | Point; `source_fid`, `name`, `municipality`, `source`, `status`, `status_date`, `source_status`, `status_source` | Exact day's daily status. APURAR or no status -> `unknown`; no carry-forward. `source_status` is original APURAR or null if absent. Static station positions remain visible. | `Operante`: green; `Inoperante`: red; `Parcial`: amber; `unknown`: gray. |
| events | Point; `record_id`, `asset`, `asset_type`, `municipality`, `observed_at`, `published_at`, `status`, `capacity_percent`, `time_precision`, `quality_notes`, `source_id`, `source`, `source_locator`, `osm_id`, `osm_name`, `geometry_role`, `incident_extent_verified`, `osm_asof` | published_at and observed_at calendar dates <= requested date. Historical events retained; a stop event does not establish current outage. | `stopped`, `not_operating`, `flooded_power_disconnected`, `inundation_begins`: red; `operating_reduced`: amber; `operating`, `production_resumed`: green; unknown status: gray. |
| shelters | Point; `snapshot_local`, `snapshot_row_id`, `municipality`, `facility_type`, `sheltered_people`, `capacity`, `vacancies`, `source` | Latest single snapshot timestamp whose local calendar date <= requested date. Empty before May 8; full latest snapshot shown including unknown/zero vacancies. | Positive vacancies: green; zero: amber; null/unknown: gray. |
| levees | LineString or MultiLineString; original `source_fid`, `id`, `nm`, `NM_DIQUE`, plus `source` | Static reference geometry for all dates, no condition or performance inferred. | Brown `#92400e`, thin line. |

Date-only queries include the whole requested source calendar day, including
that day's evening publications/snapshots. They do not provide intraday replay.
Publication times for flood, pump and shelter layers are unknown: their observation
or snapshot dates provide retrospective context only. Levees, pump positions and
OSM street points are static reference data. Source OSM snapshots may postdate
May 2024. Missing geometry is never an invented location. Flood simplification
is approximately 15 m; small features/boundaries can shift. A point outside the
latest extent does not establish recession, safety, water depth or road access.

Case fields are `case_id` (registry identifier), `decision` and numeric `priority`
(the original triage result), `lat`/`lon` (representative position), `position_kind`
(`landmark` or `street_centroid — house number not geocoded`), and `hazards`
(summary object). Unpositioned cases have null coordinates, kind and hazards.
Landmark coordinates take precedence; otherwise an unambiguous normalized street
and municipality use a median source vertex. House number 120 does not alter that
vertex. Cases with no analysis/received date <= map date are excluded. The latest
eligible historical analysis is selected; later analyses and actions do not leak
into earlier maps. Hazards are recomputed for the map date, while decisions and
priority remain those of the selected analysis. Do not imply they were rescored.

In a case hazard summary, `in_flood_extent` is true/false for the latest dated
extent or null before the first observation; `flood_observed_date` is that date or
null. `depth_m` is always null and `depth_source` always `pending (depth research)`.
The four remaining numeric fields are counts: active corridor candidates within
1,000 m, pumps within 3,000 m, historical events within 3,000 m, and available
shelters returned (at most 3), respectively. Nearby closure distance is to the
nearest segment of an unverified corridor, not a verified obstruction.

Full pipeline cases (`POST /run`, `GET /api/cases`) also contain `position`,
`hazards_reason` (null on success, a reason string when hazards are null), and
`hazards` with the above flood/depth fields, `position_kind`, and these arrays:

| Full assessment field | Item fields / selection |
|---|---|
| closures_nearby | Source closure properties, `id`, `distance_m`; <= 1 km, ordered by distance then id. |
| pumps_nearby | Dated pump properties, `id`, `distance_m`; <= 3 km, ordered by distance then id. |
| events_nearby | Event properties, `id`, `distance_m`; <= 3 km, ordered by distance then id. |
| nearest_shelters | Latest snapshot shelter properties, `id`, `distance_km`, `distance_label:"straight-line, not a route"`; positive known vacancies only, top 3 by distance then id. Zero results before May 8. |
| facts | `{id,text_pt,source}` for flood/depth/position and each nearby result, plus absence statements. Stable SHA-256-derived ids for the same date/position/evidence key; Portuguese text and source filename/URL. Cite these facts in an agent/UI; do not invent implications. |

The map endpoint supplies summary counts only. Read the full case assessment for
citable detail; an assessment's replay date may differ from the current map date.
Hazards are informational in V2-A and never feed decision/priority logic. No layer
provides a safe route, rescue assignment or a real-time availability guarantee.
