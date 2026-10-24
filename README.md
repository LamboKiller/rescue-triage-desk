# Rescue Triage Desk — V1

An explainable rescue-request queue for a dispatcher replaying the May 2024
floods in Porto Alegre and five nearby municipalities. Messy Brazilian Portuguese
messages become quoted facts, a visible critique, deterministic checks and a
proposal for a human to review. **Every dispatch approval requires a human and a
human-confirmed location.** The application records decisions; it sends no orders
to external rescue teams.

All request texts are **synthetic**, including pasted demo inputs. No real rescue
requests are included. The UI is Portuguese; code and documentation are English.
V1 includes no deduplication, map routing, outage inference or shelter hand-off.

```text
POST /run or CLI JSON (at most 15 synthetic messages)
  → identifier redaction
  → Intake: one message → quoted extraction
  → code: schema, quote and literal value checks
  → Critic: objections against extraction and text
  → if objections: exactly one Intake revision → span checks again
  → tools: Zetaris street lookup + as-of date gate + count checks
  → deterministic priority and SEND_CANDIDATE / CALLBACK / REPORTED_RESCUED
  → World Model append-only registry → Portuguese queue → human actions
```

Models extract and critique. They never calculate totals, perform geometry or
joins, score priority, mutate state, or make final dispatch decisions. Untrusted
message data is delimited in each prompt. Span checks and human gates remain
necessary: delimiters alone do not guarantee model resistance to injection.

## Windows setup (no packages to install)

1. Install Python **3.12**, then open PowerShell in this repository. Check it:
   `python --version`. No `pip install` is needed. The build sandbox only provided
   Python 3.11.16; its test results do not establish Python 3.12 or Docker execution.
2. Copy settings: `Copy-Item .env.example .env`. Keep `SAMPLE_MODE=true` initially.
3. Run `python -m unittest discover -s tests -v`.
4. Run `python run.py --sample --input examples/input_01.json`.
5. Run `python run.py serve` and open http://localhost:8080. Paste a fictional
   message, inspect its evidence, confirm its location and approve a candidate.
   To use a different port: `$env:PORT='8090'` before starting the server.

The optional `.env` parser supports `KEY=value`, surrounding quotes and comment
lines; existing environment variables take precedence. Do not put secrets in
commands, screenshots, tracked files or chat. `runtime/` holds registry events;
`logs/` holds per-run JSONL. Both are gitignored. Restarting rebuilds the queue
from `runtime/events.jsonl`; back up this file before resetting a demo.

**SAMPLE_MODE** never contacts Nightshift, Zetaris or S3. It recomputes fields
using the explicitly limited regex baseline over current input, and tools over
the real derived CSV. Every agent role is `unavailable (offline)`; no LLM answers
are cached or invented. Negations, word counts and indirect speech often exceed
the baseline. Offline output demonstrates tooling, not working agents.

## Connected mode and sponsor use

Edit `.env` locally with your keys and set `SAMPLE_MODE=false` (also remove any
conflicting `$env:SAMPLE_MODE`). Gate 0 supplied these service contracts; no live
call was possible in the build sandbox.

* **Nightshift** is the primary and only AI provider. The requested model is
  `nvidia/nemotron-3.5-lightning-30b-a3b`, thinking ON, `max_tokens=6000`, one
  message per call, three concurrent workers, `meterless-app: rescue-triage-desk`
  and `meterless-scope: user`. Do not use `meterless/auto` or `/no_think`.
  Every attempt logs requested model, actual `meterless.routed_model`, receipt,
  route kind, seconds and status to JSONL and stdout. Hidden reasoning, input
  texts, provider response bodies and credentials are not traced. The UI shows
  successful stage metadata; failed attempt details are in the JSONL.
* **Zetaris** is the normal-mode data layer. `ZetarisSource` queries the versioned
  streets table through `/sql-editor/sqls/run`; it never silently falls back to
  local CSV in normal mode. A failed source yields honest partial CALLBACK cases.
  Seeded message tables and road closures are also registered and verified by SQL.
  Road closures are context data, never evidence that a rescue route is passable.
* **World Model** is our own Python behavioral implementation adapted from the
  preparation prototype. The queue and human action API read it directly. It
  serializes JSONL appends with thread and OS advisory locks, flushes/fsyncs,
  enforces optimistic versions, retains conflicting/stale observations, and
  rebuilds from its log. Idempotent delivery uses message ID + redacted text hash.
  A changed replay or extraction is a separate analysis event; new text invalidates
  prior location confirmation/approval. Human transitions are proposed →
  human_approved → dispatched → field_confirmed; reported rescue stays unconfirmed.
  Run `python -m unittest discover -s tests -p test_core.py -v` for engine evidence,
  including ten concurrent writers, duplicate deliveries and zero lost updates.
  This is behavioral evidence, not certified upstream conformance or crash recovery.

Run these after filling `.env` (the loader writes local S3 objects and tables):

```powershell
python tools/load_zetaris.py --version v3 --seed 7
python tools/smoke_live.py
python tools/make_examples.py
python eval/run_eval.py
python run.py serve
```

The loader uploads signed path-style S3 objects, reads the bytes back, registers
`OAH_S3.streets_flood_v3`, `OAH_S3.road_closures_v3`,
`OAH_S3.messages_seed7_v3`, and `OAH_S3.landmarks_v3`, then checks row counts. Use a **new version** after
changing data; update `ZETARIS_STREETS_TABLE` accordingly. Existing-table errors
are tolerated, but reusing a name does not update its stored S3 path. Table counts
are recorded in `data/zetaris_tables.json` for smoke checks. S3 defaults to
`127.0.0.1:8333` on the host and `http://oah-s3:8333` as seen by Zetaris containers.

The live smoke retrieves three synthetic requests from the Zetaris message table
(`ZETARIS_MESSAGES_TABLE`, default `messages_seed7_v3`) before running the complete
pipeline with the normal Zetaris street source. Both tables therefore participate
in the user-run sponsor integration check.

Calls have a 180-second client timeout (clipped to remaining run budget), at
most two retries on 502/timeout with bounded backoff, and an eight-minute run
deadline. Deadline expiry returns partial cases rather than fabricated output.
Late network workers cannot mutate the registry, and a shared semaphore caps
active calls at three. One run is accepted per desk process at a time. A provider
that dribbles bytes could outlive its socket timeout; the response deadline still
returns without waiting for that worker. There is no background model auto-dispatch.

## Data and no hindsight

Committed CSVs are derived from real public layers. Rebuild with
`python tools/prepare_data.py`; override `--backup PATH` if the source pack moved.
Only named OSM highways are used. Municipality membership samples all vertices
and segment midpoints in IBGE census polygons; water membership uses only
`surface=water` on May 6 and May 8. A bbox grid and indexed ray casting respect
polygon holes. Very narrow crossings can be missed between sample points.

Porto Alegre yields **6,297** normalized streets, **1,351** touching sampled
May 6 water. R3 counted 6,367 / 1,370 using a different intersecting-way method.
Normalization merges road-type/particle/accent aliases, and point sampling may
miss crossings. All municipality counts are in `data/preparation_summary.json`.

No observed layer later than replay date is selected. Publication times are
unknown, so **all water matches are marked retrospective context and excluded
from contemporaneous priority** (`in_water_by_date=null`). The OSM snapshot is
June 15, later than the replay: a name match is retrospective context, never
proof of an address available to responders at the time. There is no permanent
water mask, depth or route safety. May 8 has different coverage: no water match
does not mean recession or safety. D1 POIs have no names; a separate named OSM
landmark snapshot supports landmark-only input. Shelter open status and local outages remain unknown.

See [attribution](data/ATTRIBUTION.md). The supplied backup lacks the promised
D1–D3 manifests/reports. The surviving layer inventory does identify UFRGS source
record 14617475 and collection 11164049; full manifest/license lineage remains a
documented packaging gap. Street derivatives carry ODbL separately
from MIT application code. No raw GeoJSON is copied into this repository.

## Decisions, score and operator controls

`SEND_CANDIDATE` requires a street found within its municipality, a house number
or a second exact named street found in that municipality, and at least one
explicitly reported person. The CSV cannot prove two streets intersect or locate
a house; humans must confirm location. Missing address, unknown municipality,
incompatible totals, future request time or failed stages require CALLBACK with
specific PT-BR questions. Reported rescue produces REPORTED_RESCUED, never a
field-confirmed closure. Counts for vulnerable categories can overlap; they are
never summed into a total population.

Integer priority (a demo policy, not an operational rescue standard):

```text
5 × min(10, max(children, elderly, disabled))
+ 8 if any reported risk words
+ 4 if contemporaneously usable mapped-water flag is true (currently never usable)
+ min(24, max(0, whole hours since received_at at replay time))
```

No model changes these weights. Age uses the received timestamp, defaulting to
replay time if absent. Pets are displayed, with no invented operational weight.
Unsupported fields are dropped and logged; a matching quote does not guarantee
semantic truth, so a critic and the human review remain essential.

The web server binds `0.0.0.0` as required. This is a **trusted-operator demo**:
`actor` is an audit label, not authentication. Same-origin browser checks prevent
ordinary cross-site commands, but anyone with API/network access can assert a
human action. Keep it on a trusted network; production needs authenticated roles,
TLS, retention policy, durable audit backups and independent security review.

## API and examples

* `POST /run`: `{"replay_time":"2024-05-06T14:00:00-03:00","messages":[{"text":"fictional PT-BR request","message_id":"optional-id","received_at":"optional ISO timestamp with timezone"}]}`.
  Returns run ID, mode, seconds, partial flag and persisted cases. More than 15
  messages, malformed timestamps and repeated IDs within a batch return 400.
* `GET /api/cases`, `GET /api/cases/{id}`: current queue/detail with event version.
* `POST /api/cases/{id}/actions`:
  `{"action":"confirm_location","expected_version":1,"actor":"operador-demo"}`.
  Actions: `confirm_location`, `approve_dispatch`, `request_callback`,
  `report_rescued`, `dispatch`, `field_confirm`. Stale version returns 409.
* `GET /api/health`: mode and TCP reachability without secrets. Offline mode
  performs no probes. TCP reachability does not establish successful SQL/model use.

`examples/input_01.json` has three address/status situations; input 02 has
contradictory counts and an out-of-area request; input 03 is judge-style free
text with an injection line. `python tools/make_examples.py --sample` produces
actual offline pipeline outputs; committed outputs are clearly `sample_offline`,
**not live multi-agent evidence**. `logs/sample_trace.jsonl` is a real offline run
summary, not a pretend provider receipt. Live outputs/receipts must be generated
on the owner's machine before claiming the live submission gates pass.

## Generator and evaluation

```powershell
python tools/generate_messages.py --seed 7 --n 15
python tools/generate_messages.py --seed 101 --n 15
python eval/run_eval.py --offline
```

The deterministic generator uses real street names (80% preference for streets
in sampled May 6 water). Seed 7 is tuning data using families 0–7. Held-out seeds
101 and 202 include 15 families, including missing numbers, unnamed landmarks,
contradictory counts, out-of-area requests, injection and rescue updates. Fake
identities use `Pessoa Fictícia` and non-dialable `FONE-TESTE-A`; truth is written
separately and is never read by runtime extraction. Request rates and vulnerability
mix are assumptions; real street grounding does not validate those assumptions.

`eval/results.md` and `.json` report per-field P/R/F1, decision accuracy,
unsupported-claim rejection rate, mean/p90 seconds and calls/message, and family
breakdowns. Offline measures **only regex baseline**; intake-only and full
Intake/Critic/Revision/Location are unavailable. Run without `--offline` for actual live
ablations. Accuracy is on synthetic text-supported labels; **real-message
accuracy is UNMEASURED**, and critic benefit is UNMEASURED until live evaluation.
There is no claim of outcomes, responder benefit or real-world validity.

## Named landmarks and review limits

`data/landmarks.csv` contains 4,191 named OpenStreetMap features in six RS
municipalities, fetched by the project owner via Overpass. OSM data is licensed
under ODbL; query and snapshot timestamps are in [ATTRIBUTION](data/ATTRIBUTION.md).
This October 2026 snapshot is retrospective relative to the May 2024 replay.
No new landmark fetch was performed for V1.2. The supplied CSV lacks a Salgado
Filho airport feature, despite the earlier brief's inventory; airport queries
remain unresolved rather than being routed to the school with that name.

LocalSource reads that CSV in sample mode; normal mode reads Zetaris
`landmarks_v3`. Register all source CSVs together with `--version v3` and update
existing `.env` table settings as shown in `.env.example`. The live smoke requires
a nonempty landmark table and checks its registered row count.

Matching requires a municipality. Equal normalized primary names within 400 m
collapse into one place, preferring relation, then way, then node; distant places
remain distinct. Scores rank full equality (100), all query tokens in a name (90),
token-set similarity at least 0.8 (82+similarity), then partial matches (55).
Street context uses address columns and the streets table; bairro names use the
address column and named suburb/neighbourhood rows. Category hints and known
short names distinguish hospitals, stadiums and public places from namesakes;
sub-facilities are penalized unless named. A match needs at least 82 points and
a 7-point lead. Generic names remain ambiguous, with up to three distinct places.
Ambiguous or missing references trigger a place/bairro callback. Resolved public
places need no house number, but still require human location confirmation.
The detail view shows the location agent, place metadata, OSM link, candidates
and decision reason. Name matching and proximity are heuristics: duplicate
features with different names, missing addresses and multiple context hints can
still require review. No household coordinates, safe route or live water depth
are inferred.

The [challenge set](eval/CHALLENGE_README.md) contains 40 author-written synthetic
Portuguese requests, separate from generated held-out seeds 101 and 202. Native
speaker review is pending; its texts were preserved in V1.2. Truth now includes
canonical OSM identities where present; the missing airport remains an explicit
expected resolved place, so its failure stays visible. Evaluation runs baseline,
intake-only and full intake/critic/revision/location on both sets, in batches of
at most 15. Every measured method reports field P/R/F1, decisions, landmark
identity/status or an explicitly counted decision proxy, unsupported rate,
critic objections and field change outcomes, calls, mean/p90 message latency
and failures. Offline agents are unavailable. Generated templates are easy and
challenge labels are synthetic; neither measures real rescue performance.

Nightshift races Lightning 30B and Nemotron 3.5 Super VL 120B lanes. The receipt's
`routed_model` identifies the winning lane, not necessarily the requested model.
Streaming stays enabled to avoid the provider deadline. Short prompts ask models
to copy evidence; deterministic code derives values. Empty or unparseable JSON
is retried once within the overall retry/deadline cap; per-call timeout is
`NIGHTSHIFT_CALL_TIMEOUT` (75 seconds by default). A failed critic preserves the
intake fields, records `review_degraded`, and forces `REVIEW_REQUIRED`. It cannot
be approved for dispatch until a fresh eligible case is produced. Provider
failures and missing source data remain visible; no live measurements were made
as part of the offline V1.2 verification.

## Docker and pre-existing work

```powershell
docker build -t rescue-triage-desk .
docker run --rm -p 8080:8080 --env-file .env rescue-triage-desk
```

For host services from the app container set
`NIGHTSHIFT_BASE_URL=http://host.docker.internal:8088/v1`,
`ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0`, and
`S3_ENDPOINT_HOST=host.docker.internal:8333`. Keep the Zetaris-side S3 endpoint
reachable from Zetaris (`http://oah-s3:8333` on its Docker network). This Docker
image and host/container routing have not been executed in the sandbox.

Declared pre-existing components: public data packs D1/D2/D3, R3 red-team findings
and `gen_proto.py` / `engine_proto.py`, prepared 21–23 October during the event's
preparation phase; Gate 0 Nightshift/Zetaris/S3 contracts and stdlib signing script.
The generator takes the seeded-template approach from `gen_proto.py`; the registry
adapts `engine_proto.py` invariants to JSONL and V1 human gates rather than porting
its SQLite implementation. No other model provider or external dependency is used.
This build does not assert public-repo publication, live sponsor proof, demo video,
deck or hackathon submission. Git remotes/config are never changed and no push is run.
