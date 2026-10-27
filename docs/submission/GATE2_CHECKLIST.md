# Gate 2 hard-requirement checklist

Refreshed 25 October 2026 by the docs/config agent (G3). No `.env` was read, no live model or Zetaris call was made.
PASS = the cited scope is evidenced here; NEEDS-YUSSEF = a human step or a live measurement is still open.
Offline results were re-run on the working tree of 25 Oct (other agents were editing `app/**` and `tests/**` at the time).

| # | Requirement | Status | Evidence (paths / commands) | Open |
|---|---|---|---|---|
| 1 | Zetaris is the local data layer (REST :8888, S3 :8333, bucket oah-s3) | PASS (v3 live 24 Oct); v4 NEEDS-YUSSEF | `app/data/zetaris.py`, `app/data/source.py` (`ZetarisSource`), `tools/load_zetaris.py --version v4`, `.env.example` (`ZETARIS_*_TABLE` v4 names); live v3 row counts in README "Setup" | Run `python tools/load_zetaris.py --version v4` then `python tools/smoke_live.py`; record result [TBD-live-number] |
| 2 | Nightshift is the primary AI provider; others only secondary | PASS | `app/llm/nightshift.py` (stream, thinking on, bounded retries); `tests/test_providers.py`; no other provider implemented | — |
| 3 | At least one Meterless Engine in a user feature, with test evidence | PASS | World Model: `app/engines/world_model/registry.py`; tests `python -m unittest discover -s tests -p test_core.py -v` (RegistryTests) and `-p test_pipeline.py -v` (`test_http_run_queue_action_and_stale_version`); user feature = queue, human actions, merges, missions, feedback | Attach final test log to submission |
| 4 | SAMPLE_MODE runs with no Zetaris/Nightshift/network from real sample inputs | PASS | `python run.py serve --sample`; `app/pipeline.py` (`LocalSource`); clean-copy run below returned 3 cases from `examples/input_01.json` in 8.5 s (`mode: sample_offline`) | — |
| 5 | `run.py` + `POST /run` bound to 0.0.0.0 | PASS | `run.py`, `app/web/server.py`; same clean-copy run (`POST /run` 200, `GET /` 200) | — |
| 6 | JSONL traces in `logs/` + stdout with the model per call | PASS (offline); live receipt NEEDS-YUSSEF | `app/llm/nightshift.py` trace fields (requested/routed model, receipt, status, seconds); `logs/sample_trace.jsonl`; `python tools/check_traceability.py` | Video must show a successful live receipt |
| 7 | ≥3 input and ≥3 real output examples | PASS | `examples/input_01..03.json`, `output_01..03.json`, `examples/README.md`; `tools/make_examples.py` | Regenerate from the final pipeline if outputs should show new agents (live run) |
| 8 | Dockerfile + placeholder-only `.env.example` | PASS (build + run verified 27 Oct, see README "Docker") | `Dockerfile`, `.dockerignore`, `.env.example` (28 settings; every `setting(...)`/`os.environ` name in app/tools/eval/run.py is present, checked by script; secrets are `replace_with_*`). `git check-ignore .env` → ignored; `git ls-files --error-unmatch .env` → untracked | — (container `POST /run` needs `RESCUE_OPERATOR_TOKEN`; see README) |
| 9 | README: setup, engine test, limitations | PASS | `README.md` sections Setup, Engine test, Evaluations, Data provenance, Honest limitations | Fill the `[TBD-live-number]` markers after live runs |
| 10 | Timeouts + bounded retries; total run ≤ 10 min | PASS (offline) | 480 s response budget (`app/pipeline.py`), 75 s call timeout, ≤3 attempts, one JSON retry; `ContractTests.test_nightshift_502_three_attempts`, `RetryTests` | Live ≤10-minute 15-message batch: [TBD-live-number] |
| 11 | No real personal data; public-repo safety | PASS (Orbit review 24 Oct) | Messages synthetic and flagged `synthetic`; masked-hit safety scan kept privately (not in repo; values never reproduced); `.gitignore` excludes `.env`, `runtime/`, `logs/*` except `logs/sample_trace.jsonl` | Yussef final look before `git push` |
| 12 | Work before 21/10/2026 21:00 declared | NEEDS-YUSSEF | `docs/submission/PRE_EXISTING_DECLARATION.md` (inventory filled, dates/attestation pending); git history starts 2026-10-24 01:44 -0300 (`git log --reverse`), so everything earlier is external inventory | Confirm timezone, dates and authorship; sign |
| 13 | Data lineage D1–D3 | GAP | `data/ATTRIBUTION.md`; README provenance table | Supply missing manifests/licences (flood/pump/levee/shelter layers, EMSN194 terms) |
| 14 | Sponsor explanation (Zetaris, engine+feature+test, Nemotron role) | PASS (draft) | `docs/submission/SPONSOR_EXPLANATION.md` | Update with final agents list and live receipts |
| 15 | 1–4 min demo video with one real Nightshift request | NEEDS-YUSSEF | README "Submission" (`VIDEO_LINK`) | Upload; replace `VIDEO_LINK` |
| 16 | Deck | PASS (file) | `docs/submission/deck_final/deck.pdf` | Upload to portal |
| 17 | Public repo URL, video URL, deck URL submitted | NEEDS-YUSSEF | — | Portal submission |
| 18 | Live evaluation of the current system | NEEDS-YUSSEF | Last live numbers (24 Oct, first pipeline) in README / `eval/results_live.json`; `eval/run_adversarial.py --live` now loads `.env` (fix below) | Run live evals listed below [TBD-live-number] |

## Evidence produced by this refresh

- **Live-runner fix.** `eval/run_adversarial.py` never called `load_env()`, so a live run had no `NIGHTSHIFT_*`/`ZETARIS_*` settings and every message failed at once (~7 s for all 24).
  Now `main` calls `load_env()` unless `--offline`, and `--live` is accepted (mutually exclusive with `--offline`). Dry check: key present after `load_env()` (value not printed), argparse rejects `--live --offline`,
  `python eval/run_adversarial.py --offline` still returns 24/24 decisions, 0 crashes, 0 unsafe sends. No live call was made.
  Note: `eval/run_dialogues.py` and `eval/run_duplicates.py` also lack `load_env()` (not changed here; outside this task's file scope).
- **Docker context check (no Docker available).** A script applied `.dockerignore` to the repo: 999 files, ~66 MB, top level `app` 106, `data` 781, `docs` 9, `eval` 40, `examples` 7, `tests` 33, `tools` 18; `.env`, `.git`, `runtime/`, `logs/`, `*_REPORT.md`, `*.log` absent; `.env.example` present.
  A clean copy of that context (no `.env`, provider env vars removed) imported `run`, `app.pipeline`, `app.web.server`, `app.missions`, `app.callback.service`; `python run.py serve --sample` then served `GET /` 200 and `POST /run` with `examples/input_01.json` → 3 cases (`SEND_CANDIDATE`, `REPORTED_RESCUED`, `CALLBACK`), `mode: sample_offline`.
- **Offline evals re-run (25 Oct)**: adversarial 24/24 decisions, routes 23/24, 0 unsafe, 0 crashes; missions 12/12; supervisor TP 8 / FP 0 / FN 0; callback 11/16 items; feedback 15/15; location 20/30 resolved (scripted). Dialogues read 7/10 (earlier reports 10/10) — unreconciled. See README table for report names.

## Exact owner commands

```powershell
# 1. Tests and engine evidence (offline)
python -m unittest discover -s tests
# 2. Docker (offline image)
docker build -t rescue-triage-desk .
docker run --rm -p 8080:8080 rescue-triage-desk
# 3. Zetaris v4 + smoke (needs services)
python tools/load_zetaris.py --version v4
python tools/smoke_live.py
# 4. Live evals (Nightshift + Zetaris; one at a time, Nightshift stalls under bursts)
python eval/run_adversarial.py --live
python eval/run_location.py --live
python eval/run_missions.py --live
python eval/run_supervisor.py --live
python eval/run_callback.py --live
python eval/run_feedback.py --live
python eval/run_redteam.py --n 24 --seed 1 --live
# 5. Demo: SAMPLE_MODE=false in .env, then
python run.py serve
Start-Process 'http://localhost:8080/v2'
```

Connected container check: `docker run --rm -p 8080:8080 --env-file .env -e SAMPLE_MODE=false -e NIGHTSHIFT_BASE_URL=http://host.docker.internal:8088/v1 -e ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0 -e S3_ENDPOINT_HOST=host.docker.internal:8333 rescue-triage-desk`.
Upload deck (`docs/submission/deck_final/deck.pdf`) and video to the organizer portal (URL not in the repo).

## Refresh 27 October 2026 (SUBMIT agent; docs/tooling only)

- README rewritten: 60-second offline quickstart (verified on port 8097: `GET /` and `/v2` 200, three example inputs return cases), sample inputs with real outputs, trace excerpt with model + receipt, eval table with commit/date, engine conformance test (`tests/test_engine_conformance.py`, 6 tests OK), Zetaris USL commands, limitations, attribution.
- `.env.example` now lists every setting name used in code (added `RESCUE_OPERATOR_TOKEN`, `RESCUE_DEVICE_TOKEN`, `RTD_VERIFIER`, `RTD_CONTRIBUTION_PATH`); `.gitignore` additionally covers `review/`, `data-backup/`, `.env.*`, `*_REPORT.md`, `.claude/`, `.codex/`.
- Safety scan: `python tools/gate2_scan.py` (optional report: `--md out/GATE2_SCAN.md`, kept out of the repo). Re-run it right before `git push`.
- Deck: final files in `docs/submission/deck_final/` (`deck.pdf`, `deck.pptx`, `deck.html`, speaker notes).
- Still open for Yussef: record/upload video, retake screenshots from the connected build, fill `[TBD-sealed50]` / `[TBD-holdout2]`, docker build, sign the pre-existing declaration, submit URLs.
