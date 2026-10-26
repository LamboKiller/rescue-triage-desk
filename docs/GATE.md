# Offline safety and quality gate

Run `python tools/gate.py` from the repo (or use the script's absolute path).
It runs unittest discovery, redteam `--n 42`, adversarial `--offline`, credibility
`--json`, hydro, callback, dialogues `--offline`, then realdev `--offline`.
Realdev runs with cwd `../open-agent-hackathon-2026` and `--dir review/realdev`.
No live mode or environment-file loading is requested.

`--fast` changes only the unit suite: it discovers test_gate.py,
test_derive_count.py, test_credibility.py, test_hydro.py, and test_hazards.py.
All seven evals still run. Use the default for full acceptance.

Each subprocess has a 300-second timeout. Checks continue after failures and
print a short table. Nonzero commands, timeouts, missing/malformed summaries,
unsafe-send counters anywhere in reported results, failed/empty unit suites,
redteam below 42/42, or adversarial below 24/24 decisions/routes fail the gate.
Credibility, hydro, callback and dialogues also retain their runner acceptance
criteria; dialogue decisions must all match. Callback also uses its `--out` JSON
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
floor, fast/full mode, per-check values/reasons/exit codes, and overall `pass`.
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
