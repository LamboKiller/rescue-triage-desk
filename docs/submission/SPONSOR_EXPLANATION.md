# Sponsor technology explanation

**Zetaris — connected data layer.** Local REST at
`http://localhost:8888/api/v1.0` queries `OAH_S3` CSV tables backed by SeaweedFS
bucket `oah-s3` on the Docker host (`:8333`). REST gives the stdlib application a
SQL boundary; S3 supplies versioned objects. Loading uses `inferSchema=false`.
Supplied verified 24 October facts: `streets_flood_v3` 12586 rows, `landmarks_v3`
4201, `messages_seed7_v3` 15, `road_closures_v3` 31, `landmark_aliases_v3` 24.
Runtime queries streets/landmarks; smoke reads messages. Closures are loaded
context, not routing input; runtime aliases come from the local curated CSV.
Evidence: `app/data/source.py:40`, `app/data/zetaris.py:35`,
`tools/load_zetaris.py:51`. The supplied four-case live smoke passed; this audit
made no sponsor calls.

**Meterless World Model — user-facing engine feature.** Our behavioral Python
adaptation (`app/engines/world_model/registry.py:25`) appends events, rebuilds case
state, retains stale/conflicting evidence and requires versioned human commands
before dispatch. `app/pipeline.py:225` ingests cases; `run.py:57` exposes the queue
and `run.py:83` exposes actions. Proof: `tests/test_core.py:134`
`RegistryTests.test_human_transition_gate_and_versions`, `:126`
`test_stale_retained_and_rebuild`, and `tests/test_pipeline.py:145`
`PipelineTests.test_http_run_queue_action_and_stale_version`. The fresh offline
suite passed 62 tests (Python 3.11.16); see `GATE2_CHECKLIST.md` for the
brief's 64-versus-62 baseline discrepancy. These tests prove application behavior,
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
