# Offline safety and quality gate

Run `python tools/gate.py` from the repo (or use the script's absolute path).
It runs unittest discovery, redteam `--n 42`, adversarial `--offline`, credibility
`--json`, hydro, callback, dialogues `--offline`, then realdev `--offline`.
Realdev runs with cwd `../open-agent-hackathon-2026` and `--dir review/realdev`.
No live mode or environment-file loading is requested.

`--fast` changes only the unit suite: it discovers test_gate.py,
test_derive_count.py, test_credibility.py, test_hydro.py, and test_hazards.py.
All seven evals still run. Use the default for full acceptance.

The full unit suite has a 1500-second (25-minute) timeout; the fast subset
uses the same suite budget. Each eval has a 300-second timeout. Checks continue after failures and
print a short table. Nonzero commands, timeouts, missing/malformed summaries,
unsafe-send counters anywhere in reported results, failed/empty unit suites,
redteam below 42/42, or adversarial below 24/24 decisions fail the gate.
Credibility, hydro, callback and dialogues also retain their runner acceptance
criteria; dialogue decisions must all match. Adversarial ROUTE/FIELD labels and
dialogue FIELD labels/phrases are warnings, printed with `WARNING:` and retained
in each check's `warnings` array in `gate_last.json`, alongside unchanged metrics
and failure rows. Only recognized mismatch rows qualify: unknown/malformed
failures remain hard failures. The dialogue runner's exit 1 is accepted only
for confirmed field-only mismatch rows with all hard checks passing; its actual
exit code remains recorded. Other nonzero exits fail. Crashes, unsafe sends,
contradiction/version regressions, and decision regressions remain hard failures.
Callback also uses its `--out` JSON
in an isolated scratch file to detect unsafe SEND_CANDIDATE decisions against
the runner's per-case expectations, both before and after replies; it removes
that scratch file afterwards. Safety detection otherwise covers reported
counters, not an independent audit of unreported application behavior.

The realdev floor measures **decision accuracy**, with an exact dataset size.
The first run creates `eval/gate_floor.json` as `{"correct":124,"total":150}`.
Subsequent runs read it without updating it. Invalid floors fail closed.
Only change the floor deliberately after reviewing results; the gate never
learns a lower floor from a bad run. Realdev errors/timeouts also fail.

`eval/gate_last.json` is atomically replaced with UTC date, current HEAD commit,
floor, fast/full mode, per-check values/reasons/warnings/exit codes, and overall `pass`.
Exit status is 0 for acceptance and 1 for failure. HEAD identifies the commit;
uncommitted concurrent edits are included in execution. Existing runners may
write their usual runtime/eval artifacts, including realdev holdout_results.json.

# Live-output replay limitation

Run `python tools/replay_live.py --dump ../open-agent-hackathon-2026/review/realdev_cases_live3`.
The 11 inspected JSON dumps contain decisions, derived fields, location results,
and call metadata. They lack `calls[i].raw_output` for every model attempt and
the original pipeline `request`. The holdout runner's `diagnostic_case` explicitly
whitelists call metadata and excludes responses. `intake_fields`, `fields`, and
`location.answer` are validated/derived values, not the exact model outputs.
Replaying those as raw replies would misrepresent the live failure.

The tool prints each case's original decision and `now=UNAVAILABLE`, identifies
missing fields, and exits 2. It does not run the pipeline or substitute baseline
answers. Malformed/empty dumps also exit 2. No application files were changed.

Minimal future dump change (requires a separate authorized capture change):

- Include `request: {replay_time, messages}` as actually supplied to the pipeline,
  preserving IDs, received_at and proposed_asset when present; record ablation.
- For every call attempt, store `role`, attempt order and `raw_output`: the exact
  response text before JSON parsing/quote validation; also preserve parse/provider
  failures and retry status. Keep the exact parsed provider return value separately
  if the client interface returns a dict rather than response text.
- Retain the original decision, and capture all stage calls, including revisions,
  hazard/credibility review and tool turns, when invoked. Do not store credentials.
- The future scripted client must consume attempts in order per role, return the
  captured provider value/error, reject missing/extra calls, and use LocalSource
  plus an isolated temporary registry with network disabled. Report a changed
  stage sequence as non-replayable rather than silently falling back. Cases from
  a shared registry need their preceding request sequence to reproduce state.

Once captures exist, implement that client against the actual saved schema.
Current captures cannot produce verified then-versus-now replay decisions.
After the capture change is authorized and implemented, the operator can collect
new live dumps from the planning folder with
`python tools/run_holdout.py --dir review/realdev --dump review/realdev_cases_live_next`.
This command defaults to live mode; it was not run for this task.

Fixture tests: `python -m unittest discover -s tests -p test_gate.py`.

# LIVEFIX latency policy (26 October 2026)

The 60-second budget starts when each message worker starts, excluding queue wait.
Calls receive remaining time minus a 2-second deterministic reserve, bounded by
the larger measured live2/holdout p90. The full median/p90 table and source are
in `StageBudget` in `app/pipeline.py`; unmeasured ID reviewers use critic proxies.
Optional calls skip visibly as `skipped: insufficient_budget` below their median.
Location tool turns donate unused time; retries retain their stage ceiling.
The critic and location agent defer to the central allocator's deadline.
Conservative intake + critic + revision + one location median totals 40.7s;
adding hazard gives 45.8s, versus the old live mean 46.7s / p95 107s. Keep 60s:
15 messages with `--jobs 2` need at most eight 60s worker waves (480s), plus
up to 60s source setup; 90s would need 720s for worker waves alone. Orbit must
verify actual wall time including deterministic work remains below 10 minutes.
Timeouts mean `stage_unavailable`: uncertain extraction remains human-reviewable,
hazard uses existing deterministic fleet checks, and an abstention is not a conflict.
The harness retains its worker with an isolated registry per evaluation batch, tolerates closed-pipe cleanup,
and reports only failure phase and exception class, never exception/provider text.
Run `python -m unittest discover -s tests -p test_livefix.py` for scaled latency
replay, optional skips, queued-message isolation and unavailable-stage safety.
