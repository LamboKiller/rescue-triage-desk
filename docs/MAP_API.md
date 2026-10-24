# Map API contract — V2-B

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
    "hazards":{"flood_by_date":{"2024-05-06":true,"2024-05-08":false},"in_flood_any":true,
      "depth_m":0.62,"depth_status":"estimada","depth_band":"d_0_6_to_1_2",
      "depth_source":"Copernicus Emergency Management Service (© 2024 European Union), EMSN194",
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

In a case hazard summary, `flood_by_date` contains each available observation
whose date is <= replay date; each value is true/false for that dated coverage
(null is reserved for unavailable coverage). Before the first observation it is
`{}`. `in_flood_any` is true if any eligible observation contains the point,
false if all eligible observations exclude it, null if none exist. A false value
on a later date can reflect different coverage, not recession. The former
`in_flood_extent`/`flood_observed_date` single-date flags have been replaced.
The visual flood layer still shows the latest eligible observation only.

`depth_m` is the nearest valid native 20 m cell centre within 60 m in the latest
observation <= replay, or null. `depth_distance_m` is its centre distance (null
when absent), `depth_observed_date` is the selected grid date (null before May 6),
`depth_status` is `estimada|desconhecida`, and `depth_by_date` contains eligible
observations as `{"2024-05-06":{"depth_m":0.5,"distance_m":12.3}}`.
No older observation fills a gap in the latest observation. No data is never dry.
`depth_band` is the numeric fleet band ID or `unknown`; this is an estimate,
not the fleet evaluator's permission to clear a vehicle. `depth_confidence` is
`"baixa — estimativa HAND ±1 m, retrospectiva"`; `depth_confidence_reason`
explains the 20 m HAND method, creation after the event and possible
underestimation. `depth_source` is the Copernicus attribution and
`depth_retrospective` is true. These fields appear in full assessments and map
summaries. Observed May 6/8 grids were created June 12, 2024; observation-bounded
replay does not claim they were available during rescue operations.

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
Hazards and fleet screening never feed triage decision/priority logic; the human dispatch gate rejects unsafe assets. No layer
provides a safe route, rescue assignment or a real-time availability guarantee.


`GET /api/depth?date=2024-05-08&bbox=-51.18,-30.00,-51.16,-29.99`
requires exactly one ISO date and one WGS84 bbox (`west,south,east,north`). Missing,
duplicate, empty, nonfinite or reversed parameters return HTTP 400. Cells are
5×5 native pixels (100 m), aligned with the source UTM22S origin, using the
maximum of valid pixels. Coordinates are their centres converted to WGS84;
centres inside the bbox are returned. Missing pixels never contribute zero.
Only the latest observation <= date is selected; before May 6 cells are empty.
The response is bounded to 50,000 cells; larger queries return HTTP 400 asking
for a narrower bbox. Current whole-grid responses are below 3 MB uncompressed.
The maximum can include valid pixels elsewhere in a partly unknown cell; it is
not full coverage or a surveyed route. A missing array entry means unknown.
The JSON structure is exactly (cell below is illustrative):

```json
{"date":"2024-05-08","observation_date":"2024-05-08","cell_m":100,"crs":"EPSG:4326",
 "columns":["lon","lat","band","max_depth_m"],
 "cells":[[-51.171,-29.994,"d_gt_2_5",2.72]],"missing":"desconhecida",
 "retrospective":true,"confidence":"baixa — estimativa HAND ±1 m, retrospectiva",
 "source":"Copernicus Emergency Management Service (© 2024 European Union), EMSN194"}
```

Suggested depth colours: `d_lt_0_15` pale blue `#dbeafe`, `d_0_15_to_0_3`
`#93c5fd`, `d_0_3_to_0_6` `#60a5fa`, `d_0_6_to_1_2` `#2563eb`,
`d_1_2_to_2_5` `#7c3aed`, `d_gt_2_5` `#581c87`; unknown gray `#64748b`.
Use hatching/low opacity for retrospective low confidence. Zero estimated depth
is not a verified dry route. Numeric band boundaries are [0,.15), [.15,.3),
[.3,.6), [.6,1.2), [1.2,2.5], and (2.5,infinity).

Full pipeline cases include the following fields (arrays below illustrate the
shape; all 20 assets and every matched rule/reason are returned):

```json
{"fleet":[{"asset":"road_ambulance","label_pt":"Ambulância rodoviária","verdict":"unsafe",
 "reasons_pt":["Veículo rodoviário genérico não pode entrar em água de inundação; use apoio e transferência em local seco verificado."],
 "rule_ids":["R035"],"source_ids":["NWS"]}],
 "fleet_summary":{"options":[{"asset":"irb","label_pt":"Bote inflável de resgate","verdict":"caution"}],
 "unsafe_assets":["road_ambulance"],"human_approval_required":true,"depth_band":"unknown",
 "brief_pt":"Opções para revisão humana; disponibilidade, equipe, rota e transferência exigem verificação."},
 "hazard_facts":[{"id":"fleet:road_ambulance","text_pt":"Ambulância rodoviária (road_ambulance): unsafe. ...",
 "source":"data/fleet/dispatch_rules.json#R035"}],
 "hazard_review":{"objections":[{"fact_ids":["fleet:road_ambulance"],
 "text_pt":"Recurso inseguro conforme as regras citadas.","severity":"block"}],
 "brief_pt":"Requer revisão humana e verificações locais."},"hazard_unsupported":0}
```

`fleet` is ordered by severity, then number of constraints, with source order as
a stable tie breaker. `fleet_summary.options` contains only suitable/caution
options, best first. Neither verdict authorizes deployment. All matching rules
combine by maximum severity; no later rule erases a veto. Portuguese reasons,
rule IDs and source IDs retain traceability to `data/fleet/dispatch_rules.json`
(version 1.0.0-research). Unknown observations/attestations stay unknown. HAND
confidence maps to low, so fleet depth clearance stays unknown regardless of the
estimated numeric band. Wheelchair or extracted disabled/bedridden people require
a secured-litter package; unknown demographics are never filled with zero.

`hazard_facts` combines assessment facts with per-asset screening facts. The
critic receives message text, case fields/result, those positional/flood/depth
facts and nearby evidence (up to 16), the proposed asset's rule fact, fleet
summary and `proposed_asset`. `/run` messages may supply a catalogue
`proposed_asset`; otherwise the first non-unsafe option is reviewed. It runs only
in live full mode after location for SEND_CANDIDATE/REVIEW_REQUIRED, through the
existing streaming Nightshift client with the global deadline. The advisory
review never changes triage decisions. Citation/number validation drops
unsupported objections and counts them in `hazard_unsupported`; unsupported
briefs are cleared and counted. Every objection needs existing fact IDs and
numbers from its cited facts or case fields; brief numbers must appear in those
accepted citations or case fields. Failure, timeout, skipped or offline review
is `"hazard_review":"indisponível"`. Successful validated output is also in
`agents.hazard_critic`; calls include role `hazard_critic`.

Map cases include `fleet`, `fleet_summary`, `fleet_replay_date` (screening
recomputed with map-date hazards), `hazard_review`, `hazard_unsupported` and
`hazard_review_replay_time` (original eligible analysis). The review is not
rerun or upgraded on map GET. Retrospective observations do not attest present
conditions. Suggested verdict colours: suitable green, caution amber, unsafe
red. Review block red; warn amber; unavailable gray.

`POST /api/cases/{case_id}/actions` approval body:

```json
{"action":"approve_dispatch","expected_version":2,"actor":"operador",
 "asset":"irb","caution_acknowledged":true}
```

Existing human/location/SEND_CANDIDATE/version gates still apply. Missing asset
returns 400; unknown/unevaluated asset or an unsafe verdict returns 409 with
`{"error":"..."}` explaining the rejection. A caution verdict requires explicit
`caution_acknowledged:true`, otherwise 409. Successful approval records
`approved_asset` and `caution_acknowledgement` containing asset, reasons_pt,
rule_ids, source_ids, acknowledged:true and actor in the event log/projection.
Suitable approval has null acknowledgement. New analysis/text invalidates
approval and its acknowledgement. Dispatch and field confirmation transitions
remain human-only and versioned. The proposed asset is advisory; the selected
approval asset is checked independently.
