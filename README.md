# Rescue Triage Desk

A Portuguese dispatcher desk for rescue-message replay from the May 2024 Rio
Grande do Sul floods. It produces evidence-linked cases, checks places and counts
with code, and requires human approval. This is a retrospective demonstration.

Message → Intake → Critic → at most one Revision → Location agent → deterministic
checks → World Model registry → dispatcher review. The LLM interprets language;
code validates evidence, joins context, counts and ranks. No automatic real dispatch
or safe-route solver exists.

## Setup

Python 3.12 is the Docker target; only the standard library is used. No pip install
is needed. Fresh local verification is in the [checklist](docs/submission/GATE2_CHECKLIST.md).
In PowerShell at the repository root:

```powershell
Copy-Item .env.example .env
python -m unittest discover -s tests
python run.py --sample --input examples/input_01.json
python run.py --sample serve
```

Open http://localhost:8080, paste a fictional message, keep the replay timestamp
with timezone and click **Analisar pedido**. Do not submit real personal data.
The server binds `0.0.0.0:8080`; use a trusted local network.

`SAMPLE_MODE=true` or `--sample` uses local CSVs and recomputes fields from input.
It needs no Nightshift, Zetaris or external network and never reads saved answers
or truth labels. Agent panels say unavailable offline: this demonstrates the regex
baseline and deterministic checks, not Nemotron. CLI/server writes registry state.

### Connected setup

After the active evaluation ends, configure `.env` locally with credentials,
the local Zetaris organization ID and `SAMPLE_MODE=false`. Never publish that file.

| Service | Local endpoint |
|---|---|
| Meterless Nightshift (OpenAI-compatible) | `http://127.0.0.1:8088/v1` |
| Zetaris REST | `http://localhost:8888/api/v1.0` |
| SeaweedFS S3 on Docker host | `127.0.0.1:8333`, bucket `oah-s3` |
| S3 as reached by Zetaris containers | `http://oah-s3:8333` |

Supplied verified live facts, 24 October 2026 (not remeasured by this audit):
Zetaris exposes `OAH_S3` tables loaded with `inferSchema=false`:

| Table | Rows | Role |
|---|---:|---|
| `streets_flood_v3` | 12586 | Runtime street/flood context |
| `landmarks_v3` | 4201 | Runtime named OSM landmarks |
| `messages_seed7_v3` | 15 | Synthetic live-smoke messages |
| `road_closures_v3` | 31 | Loaded context; no runtime routing |
| `landmark_aliases_v3` | 24 | Loaded aliases; runtime reads local curated CSV |

`python tools/smoke_live.py` checks each service and runs four cases end to end (including a
landmark message); it passed on 24 Oct 2026. With sponsor services ready, use
`python run.py serve`. TCP health proves reachability, not credentials.

### Docker

Build and run (sample mode):

```powershell
docker build -t rescue-triage-desk .
docker run --rm -p 8080:8080 -e SAMPLE_MODE=true rescue-triage-desk
```

For connected mode use `--env-file .env` and override endpoints to
`http://host.docker.internal:8088/v1`, `http://host.docker.internal:8888/api/v1.0`
and `host.docker.internal:8333` for Nightshift, Zetaris and host S3 respectively.
Keep the Zetaris-side S3 URL on its own Docker network. `.dockerignore` excludes
`.env`, runtime and logs. Container routing to host services is documented but not yet verified end to end.

## Running the engine test

The Meterless World Model adaptation is an append-only Python registry at
`app/engines/world_model/registry.py`: event replay, deduplication, retained stale
and conflicting observations, expected versions and human-gated transitions.
It is our behavioral adaptation, not an imported Meterless SDK.

```powershell
python -m unittest discover -s tests -p test_core.py -v
python -m unittest discover -s tests -p test_pipeline.py -v
```

`RegistryTests.test_human_transition_gate_and_versions` proves human/version gates;
`test_stale_retained_and_rebuild` checks event replay;
`test_ten_concurrent_writers_zero_lost` checks concurrent append behavior.
`PipelineTests.test_http_run_queue_action_and_stale_version` links the engine to
the user-facing queue/actions. These are offline tests, not sponsor certification.

## API, traces and examples

`POST /run` accepts `application/json` with `replay_time` and 1–15 `messages`.
Each message has a unique `message_id`, `text` and optional `received_at`.
See `examples/input_01.json`. `GET /api/cases` reads registry state;
`POST /api/cases/{case_id}/actions` takes action, actor and `expected_version`.
Stale commands return 409.

Three request files and three pipeline-produced connected output files are in
`examples/`; see [provenance](examples/README.md). They are saved artifacts, not
new live measurements or canned runtime answers.

Nightshift attempts write JSONL to `logs/run_<id>.jsonl` and stdout: role, message
ID, requested model, routed model, receipt, status and duration. Missing provider
metadata remains null; a failed call does not invent a winner. The page shows
**Modelo, comprovante e duração**. Inputs, credentials and hidden reasoning are
not intentionally logged; review artifacts before sharing.

The response budget is capped at 480 seconds (8 minutes), returning partial
results on deadline. Calls default to 75 seconds, at most three attempts; invalid
JSON gets at most one corrective retry within that cap. At most three messages
run concurrently; one run per desk. An already-running worker may finish afterward.

## Sponsor technology

**Zetaris is the connected data layer:** REST SQL queries over versioned SeaweedFS
CSV tables supply streets and landmarks. Offline mode deliberately uses local files.

**Meterless Nightshift is the primary and only implemented AI provider.** No
Claude/OpenAI fallback exists. Its OpenAI-compatible request uses `stream=true`
and defaults to `nvidia/nemotron-3.5-lightning-30b-a3b`. The supplied live deployment
races that lane against `nvidia/nemotron-3.5-super-vl-120b-a12b`; each receipt
identifies the actual winner. The verify lane is `llama-3.3-nemotron-super-49b`;
its existence does not prove it ran. Intake extracts quoted fields, Critic checks
claims, conditional Revision repairs objections once, and Location proposes place
evidence. Code verifies results; the LLM never counts/joins/routes.

**World Model** provides case memory and human approval gates. See the
[sponsor explanation](docs/submission/SPONSOR_EXPLANATION.md) for evidence.

## Data, evaluation and limitations

Public geographic data grounds fictional messages; see [attribution](data/ATTRIBUTION.md).
The supplied backup lacks the promised full D1–D3 manifest/license lineage: this
remains a packaging gap. Street ODbL obligations are separate from MIT code.

Only water layers at/before replay date are selected. Publication times are unknown,
so mapped water is retrospective context, excluded from contemporaneous priority
(`in_water_by_date=null`). Later OSM snapshots and aliases are also retrospective,
not proof of May 2024 availability. Sampling can miss narrow crossings. Absence of a water
match does not imply safety; no depth, safe route, shelter status or responder availability
is established. Street matches cannot prove a house number or intersection.

Resolved landmarks can supply candidates; ambiguous places require review/callback.
One explicit total wins; eligible sender-plus-listed counts are marked
**Contagem derivada — confirmar**. Vulnerable categories overlap and are not summed.
A valid quote does not prove semantic truth. Priority weights are a demo policy.

Synthetic labels do not prove real-message accuracy or responder benefit. Offline
evaluation measures the regex baseline only.

### Live evaluation (24 Oct 2026, Nightshift + Zetaris, `eval/results_live.json`)

| Set | Method | Decision accuracy | Mean s / msg | p90 s | Calls / msg |
|---|---|---:|---:|---:|---:|
| Generated (30, seeds 101/202) | rules baseline | 1.00 | 0.8 | 1.1 | 0 |
| | intake agent | 0.97 | 11.7 | 23.2 | 1.0 |
| | full loop | 1.00 | 19.6 | 31.0 | 2.4 |
| Challenge (40, hand-written, native-rewritten) | rules baseline | 0.60 | 0.5 | 1.0 | 0 |
| | intake agent | 0.975 | 15.5 | 27.8 | 1.0 |
| | full loop | 0.975 | 53.5 | 98.9 | 3.2 |

Field F1 on the challenge set, rules → full loop: children 0.25 → 0.96, elderly 0 → 0.89, disabled 0 → 0.86,
pets 0.29 → 0.91, street 0.32 → 0.95, house number 0.36 → 1.00, municipality 0.58 → 0.97. Critic: 18 of 40
messages got objections → 18 revisions → 22 field changes: 18 correct, 3 wrong, 1 neutral. No partial runs;
4 location-agent calls returned an unusable quote and fell back to the code matcher.

**Read with care.** Generated messages come from templates, so rules already score perfectly there. The challenge
set is small (40), and after the first live run the text rules (POA → Porto Alegre, written totals, count
conflicts, correction words) were adjusted while looking at these same messages. The challenge numbers are
therefore optimistic; a fresh held-out set is the honest next measure. Agents and critic do not change the
decision more than the intake agent alone here; their measured value is field accuracy (critic changes were
right 18 of 22 times) at about 3.5× the latency. Remaining misses: a partial rescue read as "already rescued"
(full loop) and a landmark message asked for a house number (intake only).

This is a trusted-operator demo. Actor labels are not authentication; same-origin
checks do not replace authenticated roles, TLS, retention controls and audit backups.
Anyone with API access can assert a human action. No real dispatch is automated.

## Pre-existing components/declaration

Inventory carried forward: public D1/D2/D3 packs, R3 red-team findings,
`gen_proto.py` / `engine_proto.py` ideas (seeded templates and registry invariants),
Gate 0 Nightshift/Zetaris/S3 contracts and stdlib S3 signing. The registry adapts
prototype invariants to JSONL/human gates rather than porting SQLite.

The dated declaration of work done before **21 October 2026, 21:00** is in
[docs/submission/PRE_EXISTING_DECLARATION.md](docs/submission/PRE_EXISTING_DECLARATION.md).

Submission drafts: [checklist](docs/submission/GATE2_CHECKLIST.md),
[demo script](docs/submission/DEMO_SCRIPT.md), [deck outline](docs/submission/DECK_OUTLINE.md),
[sponsor explanation](docs/submission/SPONSOR_EXPLANATION.md).

## V2-A hazard context and map data

Prepare local data without network access (backup remains read-only):

```powershell
python tools/prepare_hazards.py --backup C:/path/to/data-backup
# Or set RTD_BACKUP_DIR; default is ./data-backup.
```

The hazard engine attaches information after location resolution without changing
triage decisions. Shared bbox grids are built once. Street positions use median
OSM vertices; a house number is not geocoded. Flood polygons use the latest
observation on or before the replay date; publication time is unknown. Pumps use
that day's status (APURAR = unknown). Shelters use the latest snapshot that day
or earlier; there are none before 8 May. Distances are straight-line, not routes.

`GET /api/map?date=2024-05-08` returns local GeoJSON plus positioned cases; see
[the exact map contract](docs/MAP_API.md). Gzip is negotiated with Accept-Encoding.
The UI is unchanged. Depth remains pending. Static levees imply no operational
condition; closure geometries are unverified corridor candidates.

For a user-run connected upgrade, `python tools/load_zetaris.py --version v4`
registers existing CSVs plus closures, pump_status_daily, pumps, events, shelters
and street_points from data/hazards. Set the v4 table names in .env.example and
run tools/smoke_live.py yourself. LocalSource and ZetarisSource expose these six
tabular methods with the same string/empty-cell contract. The deterministic
hazard engine and map use the prepared local snapshot in both modes, so polygons
and levees remain local files; connected hazard tables are queryable context.
No live loader or smoke test was run for V2-A.
