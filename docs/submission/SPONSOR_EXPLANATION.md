# Sponsor technology explanation — Arca (repo: rescue-triage-desk)

**In one paragraph each:**

- **Nemotron via Meterless Nightshift — every agent call.** Every model call made by every agent (intake, critic,
  revision, location, hazard critic, credibility reviewer, arbiter, needs, duplicate reviewer, contradiction
  phrasing, callback, fleet allocation, mission brief, field feedback, supervisor, shift handover, volunteer intake,
  red-team attacker) goes through one OpenAI-compatible Nightshift client
  (`app/llm/nightshift.py`). Each call is logged to `logs/*.jsonl` and stdout with the **requested model, the routed
  Nemotron model and the Nightshift receipt id**, and the desk shows model + receipt on the case card. No other provider
  is wired in at runtime.
- **Zetaris — location and flood data queried by the Location agent.** In connected mode the pipeline reads the
  `streets_flood_v*` (street segments with flood-extent and depth flags) and `landmarks_v*` tables from the local Zetaris
  REST API (`app/data/source.py` `ZetarisSource`, called from `app/pipeline.py`); those rows build the place index that
  the Location agent's five tools search, so every resolved address and its flood status comes from Zetaris. Shelters,
  pumps, closures and events are onboarded too, and three Unified Semantic Layer views join them (below).
- **Meterless World Model engine — the event log behind the dispatcher queue.** Every case is an append-only, versioned
  event journal (`app/engines/world_model/registry.py`): state is rebuilt by replay, duplicates are deduplicated,
  conflicting observations are retained, stale versions are rejected and only an explicit human action can move a case
  (e.g. approve dispatch). Test result: `python -m unittest discover -s tests -p test_engine_conformance.py -v` →
  **Ran 6 tests, OK** (27 Oct 2026), one test per declared property.

## Detail

**Zetaris — connected data layer.** Local REST at
`http://localhost:8888/api/v1.0` queries `OAH_S3` CSV tables backed by SeaweedFS
bucket `oah-s3` on the Docker host (`:8333`). REST gives the stdlib application a
SQL boundary; S3 supplies versioned objects. Loading uses `inferSchema=false`.
Verified live 27 October: v4 tables onboarded (`streets_flood_v4` 12,586 rows,
`landmarks_v4` 4,201, `shelters_v4` 7,574, `pumps_v4` 38, `pump_status_daily_v4` 988,
`events_v4` 20, `closures_v4` 31, `street_points_v4` 20,623, `messages_seed7_v4` 15;
exact counts: `data/zetaris_tables.json`). Runtime queries streets/landmarks; smoke
reads messages. Closures are loaded context, not routing input; runtime aliases come
from the local curated CSV. Evidence: `app/data/source.py:40`, `app/data/zetaris.py:35`,
`tools/load_zetaris.py:51`. This audit made read-only and DDL/view-creation SQL calls
against the live local Zetaris (no Nightshift calls).

**Zetaris — Unified Semantic Layer.** Three semantic views join the onboarded sources:
`incident_context` (landmarks × per-municipality flood-segment totals), `asset_availability`
(pumps × daily status), `shelter_capacity` (shelter snapshots with derived occupancy). DDL:
`sql/usl/*.sql`; built/verified by `tools/zetaris_usl.py --build/--check`. A data-quality rule
(shelter occupancy ≤ capacity) executed live: 734 checked, 62 violations. The SQL-editor REST
endpoint is stateless across calls — a `CREATE VIEW` executes but does not persist to a second
request (verified; only the Zetaris UI's query builder persists views) — so `--check` proves
each view is active by inlining its body as a CTE in the same call as each proving query. A
Python mirror, `app/data/usl.py`, computes the identical joins offline (SAMPLE_MODE) and matches
the live Zetaris numbers exactly (`tests/test_zetaris_usl.py`); the views themselves are not yet
called from the pipeline, agents or UI (the runtime reads the onboarded tables directly). Full detail: `docs/submission/ZETARIS_USL.md`,
`docs/submission/ZETARIS_REFLECTION.md`.

**Meterless World Model — user-facing engine feature.** Our behavioral Python
adaptation (`app/engines/world_model/registry.py:25`) appends events, rebuilds case
state, retains stale/conflicting evidence and requires versioned human commands
before dispatch. `app/pipeline.py:225` ingests cases; `run.py:57` exposes the queue
and `run.py:83` exposes actions. Proof: `tests/test_core.py:134`
`RegistryTests.test_human_transition_gate_and_versions`, `:126`
`test_stale_retained_and_rebuild`, `tests/test_pipeline.py:145`
`PipelineTests.test_http_run_queue_action_and_stale_version`, and the named conformance
suite `tests/test_engine_conformance.py` (6/6 pass, one test per
declared property: append-only, pure replay, dedup, conflict retention, version-gate,
human-only transitions). The full offline suite (`python -m unittest discover -s tests`) result is recorded in
`GATE2_CHECKLIST.md`. These tests prove application behavior,
not sponsor SDK certification; no Meterless SDK is imported.

**Nemotron through Nightshift — primary AI.** Intake extracts quoted fields;
Critic challenges unsupported claims; one conditional Revision responds to
objections; Location proposes place evidence. All use the same client, not fixed
per-agent models. Supplied live routing races
`nvidia/nemotron-3.5-lightning-30b-a3b` against
`nvidia/nemotron-3.5-super-vl-120b-a12b`; verify lane:
`llama-3.3-nemotron-super-49b`. A lane's existence does not prove it handled a call.
The OpenAI-compatible client uses `stream=true`, captures the routed winner and
receipt per attempt, and writes JSONL/stdout metadata shown on the page
(`app/llm/nightshift.py:80`, `:100`, `:129`; `app/web/index.html:36`). Failed calls
may have null metadata. No Claude/OpenAI fallback is implemented.

**Deterministic boundary.** Code validates evidence, joins public place context,
gates water data by date, derives eligible counts (flagged “Contagem derivada —
confirmar”), ranks cases and enforces transitions. The LLM never counts/joins/routes;
its suggestions enter deterministic validation. There is no safe-route solver or
automatic real dispatch. Evidence: `app/pipeline.py:148`, `app/decide.py:63`,
`DerivedCount.test_counts_sender_plus_listed` (`tests/test_derive_count.py:7`), and
`RealLandmarkTests.test_http_rodoviaria_and_page` (`tests/test_v12.py:169`).
