# Map API contract — V2-B

The desk JSON endpoints are listed below. POST bodies require
`Content-Type: application/json` and at most 256,000 bytes. All errors have
the shape `{"error":"reason"}`. Browser POSTs must be same-origin.

| Endpoint | Successful response / request contract |
|---|---|
| `GET /api/cases` | `200 {"cases":[Case]}`; current registry projections, descending numeric priority. Empty queue: `{"cases":[]}`. |
| `GET /api/cases/<id>` | `200 Case` (same object as the list entry), or `404 {"error":"Caso não encontrado."}`. |
| `GET /api/map?date=YYYY-MM-DD` | `200 {"date":string,"layers":Layers,"cases":[MapCase]}`; exact layer and map-case fields below. |
| `GET /api/depth?date=YYYY-MM-DD&bbox=west,south,east,north` | `200` compact depth arrays; exact fields below. |
| `POST /run` | Request and response below; validation errors `400`. |
| `POST /api/cases/<id>/actions` | Request below; `200 Case`, `409` for conflicts/unsafe assets, `400` for invalid transitions/parameters, `404` for unknown case. |
| `GET /api/health` | `200 {"SAMPLE_MODE":true,"mode":"sample_offline","Nightshift":"unavailable (offline)","Zetaris":"unavailable (offline)"}` in sample mode. Live: `SAMPLE_MODE:false`, `mode:"live"`; service values are `"reachable (TCP only; credentials not checked)"` or `"unreachable"`. |

`Case` is the full registry object, including `case_id`, integer `version`,
`status`, `location_confirmed`, message/analysis fields, `result`, `hazards`
(object or null), `fleet` (all 20 entries), `fleet_summary`, `hazard_facts`,
`hazard_critic`, `hazard_review`, `hazard_unsupported`, `facts` (analysis history)
and `actions` (human event history). `hazard_critic` is the same validated
review object or `"indisponível"` as `hazard_review`; successful reviews also
appear in `agents.hazard_critic`. The review and fleet shapes are below.
Legacy stored analyses can lack newer fields; rerunning creates a full analysis.
`route`, if present in a stored case, is passed through unchanged by list/detail;
the backend does not generate a safe route. The exact `result` keys are
`decision`, numeric `priority`, `decision_reason`, `age_hours`,
`conflicting_counts`, `location_confidence`, `people_derived`, and `questions`; neither
fleet nor the advisory review changes it. Failed analyses retain the same fleet
and review contract with unknown hazards and an unavailable review.

`POST /run` request (optional message fields shown):

```json
{"replay_time":"2024-05-06T12:00:00-03:00","messages":[
 {"message_id":"demo-1","text":"3 pessoas na Rodoviária de Porto Alegre",
  "received_at":"2024-05-06T12:00:00-03:00","proposed_asset":"road_ambulance"}]}
```

There must be 1–15 messages; each text is 1–12,000 characters. Message IDs
must be unique within the request; omitted IDs are derived from redacted text.
`received_at` defaults to replay time; `proposed_asset` must be a catalogue ID.
The exact response envelope is
`{"run_id":string,"mode":string,"synthetic":true,"seconds":number,"partial":boolean,"cases":[Case]}`.
`mode` is `sample_offline` in offline mode, otherwise `full` for the web request.

Action request (the asset and acknowledgement apply to approval only):

```json
{"action":"approve_dispatch","asset":"irb","caution_acknowledged":true,
 "expected_version":2,"actor":"operador"}
```

Actions are `confirm_location`, `approve_dispatch`, `dispatch`, `field_confirm`,
`request_callback`, and `report_rescued`. Approval requires a proposed
`SEND_CANDIDATE`, a confirmed location and a screened asset. Unsafe assets return
`409 {"error":"Recurso inseguro: <matched Portuguese reasons>"}` without
changing state. Caution requires literal JSON `true`; otherwise `409`.
Successful approval sets `approved_asset` and records
`caution_acknowledgement:{asset,reasons_pt,rule_ids,source_ids,acknowledged:true,actor}`
for caution (null for suitable), in both the projection and action event.
Every accepted action increments `version`; stale versions return `409`.
Dispatch requires human approval; field confirmation requires dispatch.
New analysis resets approval and its acknowledgement.

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


## Deterministic case routes (A2 / A6)

Every newly analyzed case includes `route: {id, label_pt, reason_pt, steps}`.
Each step has `stage`, `status` (`ran`, `failed`, `skipped`), and `reason_pt`.
Steps describe regex/model extraction, critique/revision, street and landmark checks,
hazards, fleet, decision, and hazard critique. Sample mode has no model calls
(`calls: []`); it records skipped agents explicitly. Hazard critique is advisory;
a CALLBACK skips it in live full mode, with the decision in the step reason.

| Route id | Meaning / deterministic outcome |
| --- | --- |
| `street` | Valid street/number or crossing and count; SEND_CANDIDATE pending human checks. |
| `landmark` | Resolved local reference and count; SEND_CANDIDATE pending confirmation. |
| `ambiguous_place` | Ambiguous reference or multiple alternative places/requests; CALLBACK with a location question. |
| `already_rescued` | Reported rescue; REPORTED_RESCUED pending field confirmation. |
| `not_a_request_or_injection` | No usable request, or detected instructions; CALLBACK, or REVIEW_REQUIRED when a request accompanies instructions. Never SEND. |
| `out_of_area` | Municipality outside the six covered, or explicit external state/city; CALLBACK for human referral. Never SEND. |
| `agent_failure` | Incomplete/failed analysis, source failure, or degraded critic; REVIEW_REQUIRED. |
| `incomplete` | Count/address missing or conflicting; CALLBACK with questions. |

Failure takes precedence, then coverage, injection, rescued report, ambiguous place,
incomplete data, and resolved street/landmark. `routing_flags` records injection and
coverage flags with the deterministic rule source. This conservative injection guard
also holds a genuine request for review if it is mixed with instructions. Explicit
outside-city/state text is checked independently of extracted model fields. Offline
regex coverage and multilingual extraction remain limited; ambiguity is held for humans.
Empty/whitespace messages are accepted as CALLBACK cases; non-string or oversized
messages remain invalid. No route authorizes dispatch.

`python tools/check_traceability.py` audits offline examples and every stored
`ingest`/`analysis` case in `runtime/eval_*.jsonl`, including old versions. It prints
counts by violation kind and exits nonzero on any violation. `--sample-only` checks
only fresh offline examples. The checker verifies exact source quotes or derivation
metadata, hazard IDs/sources, call role/model/receipt metadata, and reason/route.
Failed provider attempts may record explicit null model/receipt because no receipt
was issued. Historical logs are audited unchanged; pre-route records are reported
as violations, never silently upgraded. New alias normalization and count arithmetic
carry their rule source; normalized model quotes are stored as the original substring.

`python eval/run_adversarial.py --offline` evaluates the 24 original synthetic cases
against separately stored truth, reporting decisions, routes, key fields, crash count,
unsafe SEND count and elapsed time. Omitting `--offline` uses live agents/providers.
The pipeline never reads these truth files. Offline scores measure the regex baseline,
not live-agent quality; the set is author-written and is not held-out human validation.

## Callback replies and dispatch cards (A3 / A5)

`POST /api/cases/<id>/reply` accepts `{text, received_at}`; text may be empty
(up to 12,000 characters), and the ISO timestamp must include a timezone and
must not precede the latest message. It returns the updated Case, or the usual
400/404/409 errors. Concurrent analysis/action changes are checked atomically
against the version read before processing. Replies reset human approval.

Intake sees only the new text. The code merge retains missing fields and updates
explicit new values; every merged field carries its original `quote` and a
zero-based `message_index` into `messages`. Explicit count corrections update
the count. Unresolved conflicting counts retain the prior count and both pieces
of evidence in `contradictions`; changed locations are recorded as open
contradictions requiring review. The live `critic` compares message history only
for contradictions. Sample mode uses regex extraction, including the previous
municipality as street lookup context. Location, hazards, fleet, routing, decision
and live hazard critique are recomputed. Failed replies retain the previous
analysis, append the received message, and require human review.

The append-only event has the same case ID, `parent_version`, structured `changes`
and `change_summary_pt` (field, old/new values, message index). `messages` contains
the original texts and timestamps; `facts` retains all analysis versions. An
invalid request or stale-version conflict does not append a version.

`GET /api/cases/<id>/card` returns `{text_pt, lines, facts_used}` or 404. No write
occurs. Code assembles place/confidence, people/vulnerabilities, estimated depth
band and observation date, chosen/top eligible asset and its cautions, equipment
supported by its matched fleet rules, arrival questions, case ID and version.
Each `facts_used` entry has a case `path` and exact `value`. Missing values are
shown as unknown; no capacity or equipment quantity is invented. A card is an
operator aid, not dispatch approval.

`python eval/run_dialogues.py --offline` evaluates ten original synthetic
two-message dialogues against separate truth: final decisions, field merges,
contradictions, version counts and crashes. Omitting `--offline` uses providers.
Offline results describe regex behavior, not live-provider validation.

B-137 backend additions:

* `GET /api/cases/<id>/duplicates` returns `{case_id,duplicates:[{case_id,
  score,token_overlap,reasons,review}]}` (404 for an unknown case). Candidate
  pairs must be within 12 hours inclusive. Independent blocks are a shared
  resolved OSM ID, normalized street/number in the same municipality, street
  reference points within 150 m with an overlapping known people/vulnerability
  value, or normalized word-set overlap >= 0.8 (intersection divided by the
  larger set). Explicit different house numbers suppress the proximity block.
  Reasons identify each matching block. Scores are advisory, not probabilities.
  Street centroids do not establish the location of a house.
* Live full runs review at most three candidates per case, within the existing
  deadline, using streaming Nemotron role `duplicate_reviewer`. Both messages
  and their summaries are supplied as untrusted data. Review is
  `{verdict:"same|different|unsure",evidence:[{case:"A|B",quote}],reason_pt}`;
  every quote must occur in its labelled message and `same` requires quotes
  from both. A is the requested case. Failed/offline/unreviewed candidates use
  `review:"indisponível"`. GET performs no model calls. Reviews whose message
  hashes changed are not reused. No candidate or model verdict merges cases.
* Human `POST /api/cases/<primary>/actions` accepts
  `{"action":"merge","expected_version":1,"actor":"operador",
  "target_case_id":"secondary","target_expected_version":1}`.
  Both versions must match (409 otherwise). One atomic append-only World Model
  event increments both versions. The primary retains both message histories
  and the union of analysis/hazard evidence (`messages`, `facts`,
  `evidence_union`, `hazard_facts`). Conflicting demographic counts become
  `open_items` with both supported values, are removed from resolved fields,
  and require review; they are never summed. The secondary status becomes
  `MERGED_INTO:<primary>`. Approval/location confirmation reset on the primary.
  Active approved/dispatched/field-confirmed cases and nested merges are
  rejected. Reanalysis/reply on either member requires unmerge first; ordinary
  actions on the secondary are rejected. `{"action":"unmerge",
  "expected_version":2,"actor":"operador"}` on the primary restores both
  pre-merge projections, preserves action audit histories, and increments both
  versions again. A changed secondary or an active dispatch on the primary
  causes 409. Merging recomputes fleet screening from both message histories
  and invalidates the earlier hazard review. Existing operator-only gates
  and error envelopes apply.
* `GET /api/stats?date=YYYY-MM-DD` requires exactly one valid date (400 otherwise).
  Returns `date`, `status_basis`, `open_cases`, count dictionaries `by_priority`,
  `by_decision`, `by_route`, `by_municipality`, `by_bairro`, `depth_bands`,
  `people_waiting`, `asset_demand`, `hazards`, and `agent_metrics`. Latest
  eligible analyses are bounded by received/replay day. Human status uses the
  current registry projection: legacy actions have no historical timestamp.
  Open excludes merged-away, field-confirmed and reported-rescued cases.
  People/vulnerability entries (`people`, `children`, `elderly`, `disabled`,
  `pets`) contain `{known_total,unknown_cases}`; conflicting/absent counts stay
  unknown. Vulnerabilities can overlap and must not be added to people totals.
  Geography missing from extracted fields is `unknown`.
  Demand `only_asset` counts cases whose only non-unsafe option is that asset;
  `only_group` counts cases whose options all belong to one catalogue group;
  `no_options` counts cases with none. Fleet/depth context is recomputed for
  the requested day. This counts cases needing review, not vehicles or seats.
  Hazards include `flooded_area_km2`, `area_method`, `pumps_out`,
  `pumps_unknown`, `active_closures`. Area is a 512-strip spherical scanline
  union estimate with holes subtracted and overlapping products counted once.
  Reopened/alternative-open records are excluded from active closure counts.
  Source closure temporal/geometry limitations above still apply.
  Metrics from stored eligible analysis calls include `calls_per_role`,
  `wins_per_model` (successful routed model calls), nearest-rank
  `p50_seconds`/`p90_seconds` (null with no timings), `failures`,
  `critic_objections`, `revisions`, `hazard_critic_blocks`,
  `validator_rejections`, `injections_detected`. Repeated analysis references
  are deduplicated; retries count as separate stored calls.
* `POST /run` with literal `"async":true` validates synchronously, then returns
  HTTP 202 `{run_id,status:"running"}` immediately. The same one-active-run
  gate applies; synchronous requests keep their existing response contract.
  `GET /api/runs/<id>` returns `{run_id,status,result}`; status is
  `running|complete|failed`, result is initially null, then the unchanged run
  envelope or `{error}`. Unknown/evicted run IDs return 404. The last 20 runs
  are retained in memory under a condition lock; restart clears them.
* `GET /api/runs/<id>/events` returns `text/event-stream; charset=utf-8`,
  `Cache-Control:no-cache`, `Connection:keep-alive`. It replays events from the
  beginning, flushes new events, sends `: keep-alive` comments while idle and
  closes after `event: done`. Each `data` JSON contains `stage`, `run_id`,
  `case_id`, `role`, `model`, `receipt`, `seconds`; unavailable values are null
  (seconds defaults to zero). Stages include `received`,
  `intake_started/done/error`, `critic_*`, `revision_*`, `location_*`,
  `checks_done`, `hazard_critic_*`, `duplicate_reviewer_*`, `decision`, `error`,
  and `done`. Only executed stages emit agent events; offline intake emits
  null model metadata. Decision events additionally include `decision`.
  Failures still terminate with `done`; client disconnects do not cancel work.

`python eval/run_duplicates.py --offline` evaluates 12 original synthetic
pairs against `duplicate_truth.json`: six same incidents (paraphrases,
forwarded/later messages, corrected counts) and six similar different incidents
(other floor, other house number, other day). It reports candidate recall,
crashes, automatic merges (always zero), and null reviewer accuracy/wrong-merge
suggestions offline. Without `--offline`, it measures reviewer accuracy and
wrong `same` suggestions using the streaming client. Truth never enters runtime.
