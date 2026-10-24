# Gate 2 hard-requirement checklist

Audit date: 24 October 2026. Single agent; stdlib-only, offline inspection.
Starting worktree was clean. No `.env` was read; no sponsor/evaluation/load/serve
command was executed. Supplied live facts below are accepted, not remeasured.
PASS means the cited scope is evidenced, not that all submission steps are done.

| Requirement | Status | Evidence | Fix / owner |
|---|---|---|---|
| Zetaris is local connected data layer; REST + host S3 | PASS | `app/data/zetaris.py:21`, `:35`; `app/data/source.py:40`; `.env.example`; supplied verified local REST :8888, SeaweedFS :8333, bucket oah-s3 | Config now names bucket oah-s3 and v3 tables. |
| Zetaris versioned inventory and inference contract | PASS | `tools/load_zetaris.py:51`, `:56`; supplied OAH_S3 rows: streets_flood_v3 12586, landmarks_v3 4201, messages_seed7_v3 15, road_closures_v3 31, landmark_aliases_v3 24 | Runtime reads streets/landmarks; closures are not routing input; runtime aliases remain local. |
| Nightshift primary AI; others only secondary | PASS | `app/llm/nightshift.py:80`, `:94`; `ContractTests.test_nightshift_request_and_trace`; pipeline client at `app/pipeline.py:80` | Sole implemented AI provider; OpenAI-compatible is a protocol, not an OpenAI provider fallback. |
| At least one Meterless Engine in a user feature | PASS | World Model adaptation `app/engines/world_model/registry.py:25`; ingestion `app/pipeline.py:225`; queue/actions `run.py:57`, `:83` | Behavioral implementation, not an SDK import. |
| World Model feature test evidence | PASS | `RegistryTests.test_human_transition_gate_and_versions`, `test_stale_retained_and_rebuild`, `test_ten_concurrent_writers_zero_lost`; `PipelineTests.test_http_run_queue_action_and_stale_version` | Fresh suite result below; no sponsor certification claim. |
| SAMPLE_MODE needs no sponsor/external network and recomputes real input | PASS | `app/pipeline.py:60`, `:108`; `app/data/source.py:22`; `PipelineTests.test_offline_no_network_and_not_precomputed` changes count 3–6 under patched network | Uses submitted sample text and local geographic CSVs, not prewritten answers. |
| run.py + POST /run + bind 0.0.0.0 | PASS | `run.py:24`, `:81`, `:117`; HTTP queue/action test | Trusted-operator demo only. |
| JSONL logs + stdout, actual model per call | PASS | `app/pipeline.py:79`; `app/llm/nightshift.py:89`, `:100`, `:129`; provider trace test | Logs requested/routed model and receipt per attempt. Unavailable provider metadata remains null; video must show a successful actual receipt. |
| At least 3 inputs + 3 real pipeline outputs | PASS | `examples/input_01.json` through `input_03.json`, matching output files; `tools/make_examples.py:19–23`; `examples/README.md` | JSON parsed: full mode, 6 completed cases, 14/14 calls have model and receipt. Provenance is structural, not fresh live receipt validation. |
| Dockerfile and placeholder-only .env.example | PASS | `Dockerfile:1–6`; `.dockerignore` excludes .env/logs/runtime; `.env.example` placeholder check below | Docker execution is separately pending. |
| README setup, engine test, limitations, sponsors and declaration | PASS | `README.md` named sections; 177 lines at audit; eval comment preserved | Owner attestation remains pending, not falsely declared complete. |
| Bounded retries and timeouts; total 5–10 min maximum | PASS | `app/pipeline.py:58`, `:62` (480 seconds); `app/llm/nightshift.py:84`, `:97`, `:123`; `ContractTests.test_nightshift_502_three_attempts`; `RetryTests.test_invalid_then_valid_and_cap`; deadline tests in PipelineTests | 8-minute response cap; already-running worker may finish after response. |
| No real personal data / public-repo safety | NEEDS-YUSSEF | `PUBLIC_REPO_SAFETY_SCAN.md`; `PrivacyTests.test_identifiers`; synthetic generator tests; .env ignored/untracked | Review masked pattern candidates privately, confirm source provenance and publication safety. Regex cannot certify absence of personal data. Use owner commands below. |
| Declare work before 21/10/2026 21:00 | NEEDS-YUSSEF | README inventory; `PRE_EXISTING_DECLARATION.md` owner draft | Confirm timezone, dates, authorship and every prior component; sign and disclose. |
| Complete D1–D3 manifest/license lineage | GAP | `data/ATTRIBUTION.md`; README Data/limitations records missing backup manifests | Yussef supplies missing source/license evidence; no data file edited. |
| Verified live smoke | PASS | Supplied 24 October four-case pass including landmark request | Accepted from brief, not repeated. |
| Expected 64-test baseline vs actual 62 | GAP | HEAD `157a0a0`: AST counts 62 methods in seven test modules; fresh discovery runs 62 and passes | Orbit reconciles the brief count; no tests added or changed. |
| Fresh live evaluation numbers | PASS (24/10 live run, README) | README/deck/demo retain exact EVAL_RESULTS comment | Orbit finishes active run and supplies verified numbers/methodology; do not rerun it for this audit. |
| Docker build and connected container routing validated | NEEDS-YUSSEF | Dockerfile exists; execution deliberately deferred | Yussef runs Docker commands below after current evaluation. |
| 1–4 minute video: at least one real Nightshift request | NEEDS-YUSSEF | `DEMO_SCRIPT.md` is a 3-minute recording script | Yussef records the page, model/receipt, landmark/count checks, critic/conditional revision, human gate and registry. Commands below. |
| Final deck rendered and uploaded | NEEDS-YUSSEF | `DECK_OUTLINE.md`, 10 slides, all rubric weights mapped | Yussef creates deck and uploads with final results/declaration. |
| Repo URL, video URL, deck URL submitted | NEEDS-YUSSEF | Drafts exist; no publication/upload performed | Yussef verifies public repo and completes official portal. No commit/push in this task. |
| Sponsor explanation: Zetaris, engine+feature+test, Nemotron role | PASS | `SPONSOR_EXPLANATION.md` (one-page draft); real tests cited | Attach final suite result and real demo receipt to submission. |

## Safe checks and fresh results

- AST: parsed 46 Python files without importing application code (stdlib ast).
- Examples: six JSON files parsed; three connected outputs; 14 model/receipt records.
- `.env.example`: all credential and organization fields are replacement placeholders;
  URLs/table names/model/default timeouts are public config, not credentials.
- `git check-ignore .env`: exit 0; `git ls-files --error-unmatch .env`: untracked.
- Safety scan: 80 tracked UTF-8 files, 0 skipped, 1770 masked file/line/type hits across 13 files.
  Types: 14 key/token-like, 1534 phone-like, 219 CPF-like, 3 absolute Windows user
  paths; zero email/non-loopback IPv4 matches. Candidates are not confirmed leaks.
- Unit suite: `python -B -m unittest discover -s tests` with bytecode writes disabled:
  **62 tests passed in 23.398 seconds**, exit 0, no failures/errors; Python 3.11.16.
  Python 3.12/Docker execution was not established by this run.
- Baseline discrepancy: the brief said 64 tests; HEAD `157a0a0` contains 62
  test methods across seven test modules, matching discovery. No tests were changed.
- Forbidden paths: final `git status --porcelain -uall` found zero changes under
  app/, eval/, runtime/, logs/, data/, tests/ or run.py; all nine changed/new files
  are inside the allowed doc/config paths. Starting worktree was clean.

## Exact owner commands (after the active evaluation ends)

These are handoff commands, not actions performed by this audit. Do not run a
second evaluation or reload sponsor data while Orbit's run is active.

Docker build and offline page (two commands; stop container with Ctrl+C):

```powershell
docker build -t rescue-triage-desk .
docker run --rm -p 8080:8080 -e SAMPLE_MODE=true rescue-triage-desk
```

Connected container routing check, using local credentials without displaying them:

```powershell
docker run --rm -p 8080:8080 --env-file .env -e SAMPLE_MODE=false -e NIGHTSHIFT_BASE_URL=http://host.docker.internal:8088/v1 -e ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0 -e S3_ENDPOINT_HOST=host.docker.internal:8333 rescue-triage-desk
```

Video/live-demo preparation: stop any demo server using port 8080 first, configure
`.env` locally with `SAMPLE_MODE=false`, then use separate PowerShell windows:

```powershell
python run.py serve
```

```powershell
Start-Process 'http://localhost:8080'
Start-Process '.\docs\submission\DEMO_SCRIPT.md'
```

Record the exact clicks in the script with the owner's recording tool, including
a new successful Nightshift request. No installed recording CLI is assumed.

Deck, declaration and private review:

```powershell
Start-Process '.\docs\submission\DECK_OUTLINE.md'
notepad .\docs\submission\PRE_EXISTING_DECLARATION.md
Start-Process '.\docs\submission\PUBLIC_REPO_SAFETY_SCAN.md'
git status --short
```

Create/export the deck in the owner's presentation tool, review masked hits
without exposing values, and confirm provenance and license evidence. For uploads,
the official portal URL is not provided; paste the actual organizer URL:

```powershell
$submissionPortal = Read-Host 'Paste the official organizer submission portal URL'
Start-Process $submissionPortal
```

Upload the final video and deck there and supply the public repo URL, sponsor
explanation and completed declaration. Verify link visibility as a judge. There is
no honest service-specific upload CLI command without the portal/service details.
