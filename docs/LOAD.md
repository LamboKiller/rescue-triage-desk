# Desk surge harness

Run from the repository root using Python's standard library. No dependencies,
credentials, `.env`, evaluation answers, or provider services are used offline.
All generated requests are synthetic. Only street names from
`data/streets_flood.csv` for Porto Alegre and Canoas enter the authored PT-BR
templates. The seeded mix is approximately 10% exact reposts, 5% injection,
5% volunteer offers, 5% donation notices, and 75% rescue requests. Counts are
rounded down for small runs. Reposts have distinct delivery IDs and retain
their original text. The public `eval/realistic_dev.jsonl` is read only by the
overlap test; generation never reads evaluation messages.

## Offline commands

```powershell
python -m unittest discover -s tests -p test_load.py
python tools/load_test.py --offline --burst 20 --max-minutes 5
python tools/load_test.py --offline --burst 300 --rate 30 --minutes 10 --max-minutes 120 --seed 7
```

The last command exercises an initial 300-message burst followed by a Poisson
arrival process with mean 30/min for ten minutes. Its total is random, not
necessarily 600. `--max-minutes` is a hard wall-time measurement guard, including
drain time (startup has a separate 90-second cap). Pending and not-yet-arrived
messages remain in the report; reaching the guard never counts as successful
completion. The offline server is a separate process; terminating it at the
guard leaves its append-only registry and manifest available for inspection.

For a shorter functional stress run with the same logical workload:

```powershell
python tools/load_test.py --offline --burst 300 --rate 30 --minutes 10 --seed 7 --latency-scale 0.01 --arrival-scale 0.02 --max-minutes 12
```

Both scales must be positive. They separately multiply provider sleep and
arrival offsets. Real pipeline computation, filesystem work, HTTP, SSE,
priority calculation, and UI response measurements remain unscaled. These
numbers describe a functional stress exercise, not production capacity or
real-time acceptance. Default scales are 1. The copied latency artifact
`data/load/LIVEFIX6_LATENCY.json` comes from Orbit's retained role summaries.
Fake sleeps use a seeded piecewise uniform distribution whose min, median and
max match each role's summary; raw observations were unavailable. Unmeasured
roles borrow the critic distribution and are not claimed as measured.

The fake proposes exact baseline quotes, uses two FIFO `FairSlots`, and passes
through the real non-sample pipeline and `StageBudget`. It never contacts
Nightshift or Zetaris. Hazard and other reviews are explicitly synthetic,
so this run measures mechanics and pressure, not model quality. Every store
and trace for the embedded desk lives under a unique `out/load/desk-*` folder.

## Running desk / live commands for Orbit

Orbit starts the server separately. This harness never starts a live provider
or approves a dispatch. Use a dedicated desk with empty disposable runtime
state: the load tool intentionally posts real synthetic intake records.

```powershell
# Terminal 1, Orbit only; this normal live server entrypoint loads credentials.
python -m app.web.server --port 8080
# Terminal 2: resolve the listening desk's PID for local RSS.
$loadServerPid = Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess
python tools/load_test.py --live --url http://127.0.0.1:8080 --pid $loadServerPid --burst 20 --rate 6 --minutes 5 --max-minutes 15 --seed 7
```

The explicit live workload above is also the default for `--live`. A pure burst
is `--burst 20`; a rate-only run is `--rate 6 --minutes 5`. Live scales must be 1.
`--offline --url URL` measures an already running sample desk, whose fake
latency must be configured by its owner. Omitting `--url` creates the isolated
fake-client desk. RSS requires `--pid` for an external local server; remote or
unavailable memory is reported as null, never as zero. Do not point this tool
at a desk carrying real incidents.

## What is measured

Each run writes `out/load/<UTC-stamp>-<suffix>.json` and `.md`, even when
acceptance fails. JSON retains every generated delivery, original/repost IDs,
arrival offset, attempts, acceptance time, first-decision time, persistence,
guard state, and all sampled observations. Exit 0 means every acceptance check
passed; exit 1 means a report was written with failing checks.

The two UI endpoints have independent sampler threads, so slow probes do not
serialize intake arrivals. First-attempt lag relative to the intended arrival
profile is reported separately from intake acceptance wait. The HTTP sender
prioritizes initial delivery attempts before retrying busy rejections. Each
endpoint targets a five-second cadence; an in-flight request is never stacked
with another probe to the same endpoint. Timeouts and cadence drift are
visible in the timestamped samples.

- First decision: arrival to the SSE `decision` event; case/run polling is the
  fallback for failed workers or missed events. Percentiles use linear
  interpolation. Throughput counts persisted deliveries, including reposts,
  per wall minute. Deliveries without an observed decision are excluded from
  latency percentiles. `pending` means persistence has not yet been observed;
  a decision event can precede registry persistence at a guard cutoff.
- Provider queue wait: sum terminal `ran`/`code_fallback` stage queue seconds,
  avoiding duplicate `provider_queue` observations. Intake waiting in this
  harness is reported separately. Case failures use `eval/failures.py`;
  stage failures retain TIMEOUT/provider_refused/agent_failure categories.
- Decision mix; SEND-prefixed decisions without a resolved street, validated
  location, or resolved non-context landmark; minimal/degraded path counts.
  This location proxy does not validate an actual dispatch or asset safety.
- Backlog samples distinguish client waiting, arrived-minus-decided, and
  server-visible pending. Every five seconds, `/api/cases` and `/v2` HTTP
  latency, status and server RSS are recorded. UI p95 combines both routes;
  samples retain per-route values. Timed-out probes retain elapsed seconds
  and an `incomplete` flag: this is a lower bound, never a fast success.
  Any 5xx, failed probe, or response over 1 s is visible. This checks HTTP
  responsiveness, not browser rendering.
- SSE content type, event/heartbeat/decision counts, stream errors, completion
  markers and observed event gaps. Missing completion fails health even if
  polling recovers results.
- Exact reposts must be attached to the same registry case and retain both
  delivery IDs. Non-reposts sharing an incident are counted as incorrect
  merges. Unevaluated reposts stay visible in the expected/evaluated counts.
- Priority checks verify descending live priority scores returned by
  `/api/cases`, the desk's actual urgency ordering. This does not claim that
  an untriaged pending message has already received a P1 classification.

Current server limitation: one asynchronous run can execute at a time; the
intake accepts at most 15 messages per run. Busy 400s are counted and retried
from a retained client queue. Other rejections, failed runs and ambiguous
POST transport failures count as dropped/unknown; unknown POSTs are not
blindly retried. Retained messages still waiting at the guard are pending,
not successful. Client retention is not operator visibility: every attempted
pending message absent from `/api/cases` fails the visibility check. A visible
pending row must contain “em fila” and an age field. The harness does not
add fake pending rows or change the production intake/UI. No server hooks
were added. The harness tracks all accepted run IDs, including queued runs
if the desk's intake gains queue support.

## Restricted quality gate

The brief asks for `python tools/gate.py --fast` while forbidding reads of
`review/realdev`. The gate includes that dataset even with `--fast`. Preserve
that restriction with the verification-only filesystem audit guard:

```powershell
$previousLoadPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Resolve-Path data/load/guard).Path
python tools/gate.py --fast
$env:PYTHONPATH = $previousLoadPythonPath
```

The guard propagates to gate subprocesses and denies `.env` and protected
review directories before opening them. It does not skip checks or fabricate
PASS results: the realdev check must fail with PermissionError. A full gate
PASS therefore requires Orbit to run the ordinary command in a context
authorized to open that dataset. Do not remove this restriction inside this
task. Poll long-running verification in intervals shorter than six minutes.

## Verification findings (2026-10-26)

The load test module passed all six tests; byte compilation passed. The
guarded fast gate passed suite (71 tests), redteam (42/42), adversarial
(24/24), credibility (20/20), hydro (15/15), callback, and dialogues. Its
realdev check failed because the required filesystem guard denied access.
No full gate PASS is claimed.

Guarded full unittest discovery ran 959 tests in 963.995 seconds and finished
with one failure and ten errors. Its complete output is retained at
`out/load/full-suite.log`. Nine errors were temporary-directory permission
failures (WinError 5 / Errno 13), including temporary directories already
inside the repository:

- `test_demo.ResetSafety.test_dry_run_moves_nothing_and_outside_repo_refused`
- `test_demo.ResetSafety.test_only_runtime_artifacts_moved_and_nothing_deleted`
- `test_i18n.I18NTests.test_default_pt_url_param_and_persistence`
- `test_i18n.I18NTests.test_every_fleet_reason_sentence_is_translated`
- `test_i18n.I18NTests.test_every_static_chrome_string_has_an_english_equivalent`
- `test_i18n.I18NTests.test_evidence_is_never_translated`
- `test_i18n.I18NTests.test_safety_labels_have_exact_english_equivalents`
- `test_i18n.I18NTests.test_templates_capture_numbers_and_places`
- `test_i18n.I18NTests.test_unknown_strings_stay_portuguese_without_error`

The other two results were:

- `test_landing.Http.test_get_report_choice_roundtrip`: HTTP read timeout.
- `test_replay.HttpTests.test_state_start_pause_speed_and_errors`: one late
  `finished` event where the pause assertion expected no events.

These modules were not edited by this task. The suite ran on a shared host
with concurrent work, including the load exercise. An isolated guarded rerun
of the two timing cases passed the replay assertion and reproduced the
landing HTTP timeout (2 tests, 1 error, 31.844 seconds).
