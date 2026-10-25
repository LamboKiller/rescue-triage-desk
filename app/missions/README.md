# Mission desk

Run the mission-enabled server from the repository root:

```text
python -m app.web.server --sample --port 8080 --inventory path/to/inventory.json
```

Open `/v2`, select an incident and open **Missões**. Omit `--sample` for live
`needs_extractor` and `mission_brief` calls using the existing Nightshift settings.
The original `python run.py serve` remains available; its POST router has no
extension hook and does not expose mission endpoints. No existing launcher file
was changed because M1 owns `app/web/**`.

The repository has no verified boat passenger capacities or available-unit
inventory. With no inventory file, proposals explicitly ask for those data and
cannot be approved. An operator inventory is a JSON array of actual units:

```json
[
  {
    "id": "operator-unit-id",
    "asset": "irb",
    "capacity": null,
    "capacity_basis": "rescue_passengers_after_crew_and_equipment",
    "source": "operator manifest / equipment document reference",
    "observed_date": "2024-05-08",
    "available": null,
    "synthetic": false,
    "attestations": {"stretcher_capable": null}
  }
]
```

Replace unknowns with documented positive passenger capacity and explicit
availability. Capacity is for rescued passengers *after* crew, equipment and
patient configuration; no seats are inferred from boat class. Dates after the
replay day are excluded. Fleet verification field names are in
`data/fleet/dispatch_rules.json`. Unknown attestations stay unknown. An existing
fleet veto is retained even if inventory supplies additional flags: re-evaluate
the case/resource package before proposing it again. Wheelchair/bedridden needs
also require an explicitly litter-capable unit. Inventory is read at startup;
restart after updating it. Active reservations survive restart in the registry.

`GET /api/missions/proposals?date=YYYY-MM-DD` produces plans from current
available SEND candidates whose messages/analyses are already available on the
replay day. Hazard context is re-screened for that date. Current human status is
used; historical analyses superseded by later messages are excluded. Each stop
includes exact needs quotes, access context, fleet rule citations, people and
case version. Point distances are haversine straight lines between stops;
launch, return, handoff locations and navigability are not inferred.

`POST /api/missions` accepts `proposal_id`, `actor`, `expected_versions` (a map
from every case ID to its reviewed version), and `caution_acknowledged:true`.
Only a server-cached proposal can be approved. Registry actions re-check all
versions, math, fleet vetoes, location, depth, and inventory reservations under
the existing process/OS lock. All members change in one durable append-only
event to `ASSIGNED:<mission_id>`. Replies, reanalysis, merge and unrelated
actions require cancellation first.

`GET /api/missions/<id>` returns a durable approved/cancelled mission, its brief
and current versions. `POST /api/missions/<id>/cancel` takes `actor` and the
complete `expected_versions` map; it restores prior statuses atomically.
Both commands are also available through `/api/cases/<id>/actions` with
`action:approve_mission|cancel_mission`, `expected_version`, the same group
versions, and `proposal_id` or `mission_id` respectively. Cross-origin POSTs
are rejected with the existing trusted-operator demo contract.

```text
python -m unittest tests.test_missions -q
python eval/run_missions.py --offline
python eval/run_missions.py --live
node --check app/web/v2/app.js
node --check app/web/v2/missions.js
node --check app/web/v2/map.js
```

The eval's 12 scenarios and 15 needs messages are author-written synthetic
truth, with real points from `data/hazards/street_points.csv`. Its capacities and
attestations are explicitly synthetic, including full fleet verification flags
to exercise positive configurations; they are not operational inventory.

Orbit browser acceptance: select Missões using mouse and keyboard arrows;
verify requirements/quotes, fallback labels, trip loads, grouping explanations
and visible blockers. Missing inventory/depth must disable approval. With a
documented test inventory and eligible confirmed cases, acknowledge cautions,
approve and cancel; refresh/restart and verify all member statuses. Check
numbered stops and a dashed straight line with “ordem sugerida — não é rota
navegável” in MapLibre and canvas fallback. Change replay date while loading:
old mission overlays must disappear. Repeat approval with stale versions and
try assigning the same boat from another browser tab: expect HTTP 409.
