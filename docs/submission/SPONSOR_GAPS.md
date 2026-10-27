# Sponsor-tech gap table — Zetaris + Meterless + Nightshift/Nemotron vs. official criteria

Reviewed 2026-10-27. Evidence is file:line, a live query, or a test run in this session. Zetaris
and SeaweedFS were live and reachable (`docker ps`: `zetaris-api-1`, `zetaris-ndp-driver`,
`zetaris-ui-1`, `zetaris-postgres-1`, `oah-s3`, all healthy). No Nightshift calls were made (forbidden
by this review's brief); Nightshift-dependent rows are marked accordingly. Scope note: this review
could not edit `app/pipeline.py`, any `app/agents/*`, or `app/web/**` (owned by other active
builders, several mid-edit per `git status`) — rows that would require touching those say so.

## ZETARIS — "Build with Zetaris"

| # | Criterion | Status | Evidence | Fix |
|---|---|---|---|---|
| 1a | Document use case + ≥3 data sources | **Met** | `docs/submission/ZETARIS_USL.md` §1a: 5 sources (landmarks, streets+flood, shelters, pumps+status, messages), table with row counts | — |
| 1b | Onboard sources, verify operable, 2–3 exploratory queries/source | **Met** | Already onboarded by `tools/load_zetaris.py` before this review (`data/zetaris_tables.json`); verified live via `SHOW TABLES IN OAH_S3` (23 tables); 13 exploratory queries with real captured results across all 5 sources, `ZETARIS_USL.md` §1b | — |
| 1c | Construct/verify/showcase 1 USL (DDL, 2–3 proving queries, 1 executing DQ rule) | **Met, with a disclosed limitation** | DDL: `sql/usl/{incident_context,asset_availability,shelter_capacity}.sql`. Proving queries run live via `tools/zetaris_usl.py --check` (6 queries, real rows, `data/zetaris_usl_last_check.json`). DQ rule: shelter occupancy ≤ capacity, **734 checked / 62 violations**, live. Limitation: the SQL-editor REST endpoint is stateless across calls — a `CREATE VIEW` executes (HTTP 200) but is gone on the next call (tested: `SELECT` from it fails, `SHOW TABLES` omits it). Only the Zetaris UI's `query_builder` persists views (`SHOW VIEWS IN OAH_S3` lists one pre-existing example, `PIKACHU_ABILITIES_TABLE`). `--check` works around this by inlining each view's body as a CTE in the same call as the proving query — functionally equivalent, not a standing catalog object. | Whoever has Zetaris UI access: paste `sql/usl/*.sql` bodies into the UI's semantic-layer builder to get real persisted Schema Store Views; then `SHOW VIEWS IN OAH_S3` should list all three. |
| 2a | Doc: USL vs. hand-coded, bonus comparison | **Met** | `docs/submission/ZETARIS_REFLECTION.md` §2a: measured LOC/time for the same join written both ways (SQL view vs. `app/data/usl.py`) | — |
| 2b | Doc: USL help/not-help in our work | **Met** | `ZETARIS_REFLECTION.md` §2b | — |
| 2c | Doc: PM requirement + mocked USL feature | **Met** | `ZETARIS_REFLECTION.md` §2c: "persisted views reachable from the SQL-text API" + a mocked (clearly unexecuted) `shelter_recommendation` view | — |

## HACKATHON

| # | Criterion | Status | Evidence | Fix |
|---|---|---|---|---|
| H1 | Zetaris is THE data layer | **Partial** | `app/data/source.py:71` `ZetarisSource` is the only connected-mode data path (no other DB/API); used when `SAMPLE_MODE=false`. Not re-verified end-to-end against a live `/run` in this session (Nightshift calls forbidden by this brief, and `app/pipeline.py` is owned by another builder) | Orbit: one connected-mode `/run` smoke with `SAMPLE_MODE=false`, confirming `ZetarisSource` (not `LocalSource`) actually served the request — README cites one prior 4-case smoke on v3 tables, not yet repeated on v4 |
| H2 | ≥1 Meterless Engine, working feature + passing conformance test | **Met** | World Model (`app/engines/world_model/registry.py`) backs the case queue (`app/pipeline.py:225`, `run.py:57/83` per README). Added `tests/test_engine_conformance.py` naming the 6 declared properties (append-only, pure replay, dedup, conflict retention, version-gate/409-equivalent, human-only transitions) in one file; ran: **6/6 PASS**. Pre-existing `tests/test_core.py::RegistryTests` (9 tests) also PASS | — |
| H3 | Nightshift as primary (only) AI provider | **Met, structurally** | `app/llm/nightshift.py` is the sole LLM client; no OpenAI/Claude fallback path exists anywhere in `app/`. Not exercised live (forbidden) | — |
| H4 | Nemotron via Nightshift; SHOW which model handled each request | **Partial** | `app/llm/nightshift.py:479` logs `requested_model`; `:498` logs the routed `model`, `receipt`, `route_kind` per attempt, written to `logs/run_<id>.jsonl` and stdout (`:452-456`). UI rendering of these fields is claimed in `SPONSOR_EXPLANATION.md` (`app/web/index.html:36`) but **not independently re-verified here** — `app/web/**` is restricted to this review and several of its files are mid-edit (`git status`) | Orbit: confirm the routed-model/receipt fields still render in `/v2` after the in-flight UI edits land |
| H5 | Video: Zetaris query + Engine feature + 1 real Nightshift request | **Missing** | No video file found in the repo (`**/*.mp4` — none) | Yussef: record before submission |

## README

| # | Criterion | Status | Evidence |
|---|---|---|---|
| R1 | Setup from clean clone | **Met** | README "Setup" — copy `.env.example`, `pip`-free, PowerShell steps |
| R2 | Usage, ≥3 sample inputs/outputs | **Met** | `examples/input_0{1,2,3}.json` + matching `output_0{1,2,3}.json` |
| R3 | Deps incl. Zetaris + Nightshift | **Met** | README "Connected mode" table |
| R4 | Traces with model per request | **Met** | `app/llm/nightshift.py` writes `logs/run_<id>.jsonl`; `logs/` exists |
| R5 | Engine conformance test | **Met (this review)** | `tests/test_engine_conformance.py`, added — see H2 |
| R6 | `.env.example` placeholders only | **Met** | Read in full this session: every secret-shaped field is `replace_with_local_key`/`replace_with_local_secret`/`replace_with_local_org_id`; no real key present |
| R7 | `SAMPLE_MODE=true` fallback | **Met** | `.env.example` line 4 default; `app/config.sample_mode()`; exercised offline by every new test in this review |

## This review's additions (new files only; nothing restricted was touched)

`sql/usl/*.sql`, `app/data/usl.py` (new module, mirrors the SQL exactly, SAMPLE_MODE-safe —
see below), `tools/zetaris_usl.py`, `tests/test_engine_conformance.py`, `tests/test_zetaris_usl.py`,
this file, `ZETARIS_USL.md`, `ZETARIS_REFLECTION.md`, and the `SPONSOR_EXPLANATION.md` edit below.

## "Make the app read a USL view in a real feature" — why this review did not wire it in

`app/data/usl.py` exists, is tested, and mirrors `sql/usl/*.sql` exactly (its offline numbers match
the live Zetaris numbers bit-for-bit: 734/62 DQ check, Canoas 252 flooded landmarks, Porto Alegre
4,514 flooded segments, 10 pumps down on 2024-05-06 — see `tests/test_zetaris_usl.py`). It is
**not yet called from any pipeline/agent/UI code.** Every plausible call site is one of:
- safety-critical to a live dispatch decision (`app/fleet/__init__.py:screen()`, the only clean
  fleet-veto entry point — wiring new data into it is exactly the kind of triage-destabilizing
  change `BRIEF_COMMON.md` tells every build agent to avoid), or
- already mid-edit by another concurrent builder per `git status` (`app/fleet/allocation.py`,
  `app/landing/*`, `app/missions/*`, `app/handover/*`, all `app/web/**`) — touching them risks a
  collision with in-flight work this review cannot see.

Per the brief's own escape clause ("if feasible... else list it as a gap for Orbit"), this is
listed here instead of forced. **Concrete next step for Orbit:** once `app/fleet/allocation.py`
and `app/landing/planner.py` settle, `app/data/usl.py:shelter_capacity()` is a drop-in enrichment
for whatever picks a shelter in `app/landing/planner.py` ("shelter with room" per README's
architecture diagram) — same return shape as the `shelters()` rows it already reads, plus
`occupancy_rate`/`over_capacity_flag`, behind a new `ZETARIS_USL_ENABLED` setting with the existing
`shelters()` call as the fallback.
