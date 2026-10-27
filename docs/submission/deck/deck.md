# Rescue Triage Desk: deck content

## 1. Rescue Triage Desk
*Messy flood messages in, human-approved rescue dispatch out*

- Built and replayed on the May 2024 Rio Grande do Sul floods
- Portuguese rescue requests become evidence-linked cases
- Code checks, agents explain, a human approves every dispatch

Visual: `img/ux2_route_1920x1080.png`

Retrospective replay desk, not a deployed emergency system.

## 2. The problem: requests are messy, decisions are urgent
*Users: dispatchers, coordinators, volunteer boat crews*

- Citizens write half an address, "my two babies", a landmark, a rumour of rescue
- Dispatchers must decide where, how many, who is vulnerable, what is already rescued
- A wrong guess sends a boat to the wrong street, or leaves a family waiting
- They need evidence they can check, not a black-box score

Visual: `img/ux2_new_emergency_1920x1080.png`

## 3. The solution: an evidence-linked dispatch desk
*From message to approved mission, every step checkable*

- Reads PT/EN/ES messages; every extracted field carries an exact quote
- Code verifies places, counts, hazards, freshness and asset safety
- Callback agent asks the citizen at most three questions, then re-triages
- Groups cases into missions, routes land and water legs, tracks field feedback
- Human confirms the location and approves; undo is available

Visual: `img/i18n_en_queue.png`

## 4. Agent workflow and architecture
*An agent exists only where it decides something code cannot*

Flow: Message -> Redact + injection check -> Intake -> Critic (max 1 revision) -> Location + tools -> Code checks + hazards -> Human approval

- Also: Needs, Duplicate reviewer, Callback planner, Field feedback, Mission brief, Supervisor, Red team
- Strict JSON, one retry, visible fallback; unsafe asset or injection blocks dispatch

Visual: `img/i18n_en_agentes.png`

## 5. Technology stack
*Small, auditable, runs on a 16 GB laptop*

- Python 3.12 standard library only; no pip install
- Nemotron 3.5 (Super VL 120B, Lightning 30B) via Meterless Nightshift, thinking on
- Zetaris REST + SeaweedFS S3 for streets, landmarks, shelters, pumps
- MapLibre GL, OSM, Copernicus EMS flood extent and HAND depth, IBGE
- SAMPLE_MODE=true runs everything offline; Docker image included

## 6. Zetaris and Meterless in the product
*Sponsor technology is used in user-facing features*

- Nightshift: every call logs the routed model and a receipt (lanes race)
- World Model engine: append-only journal, replay, 409 on stale versions, human-only transitions; 6 conformance tests
- Zetaris: 5 sources onboarded, 3 semantic views; Rodoviária in flood extent, 4,514 flooded segments
- Data-quality rule: 62 of 734 shelter snapshots over capacity

Visual: `img/i18n_en_case_Retorno.png`

## 7. What is different
*Safety by construction, not by prompt*

- Every model claim is tied to a quote or fact id and validated by code
- Counts, distances and ranks are never model output; derived counts are flagged "confirm"
- Red-team attacker declares its expected outcome first; failures become human-approved regressions
- Straight-line water legs and retrospective depth are labelled estimates, never safe-route claims
- Place memory is exact, city-scoped and revocable

## 8. The product
*Dispatcher console (offline sample mode shown, synthetic data)*


Visual: `img/ux2_meios_1920x1080.png`, `img/ux2_route_1920x1080.png`, `img/ux2_dispatched_1920x1080.png`

## 9. Results (our own sets, labelled)
*Commit 4867ff0; live run 26 Oct 2026 19:40*

- Live realdev 30-sample: 29/30, 0 unsafe, mean 20.6 s, p95 53 s
- Offline: realdev 134/150, 0 unsafe; red team 42/42; adversarial 24/24; 1170 tests
- dev2 (180 author-written messages), live 60-sample before fixes: 36/46 non-ambiguous, people count 28/29
- Sealed 50: [TBD-sealed50]. Holdout 2: [TBD-holdout2] (run once after freeze)
- Limits: dev sets are ours; fleet and GPS simulated; HAND depth retrospective

Visual: `img/i18n_en_evals.png`

## 10. Future enhancements
*Reproduce it: clone, SAMPLE_MODE=true python run.py serve --sample, open /v2*

- Real fleet and GPS feeds; authentication and roles for operators
- Real-message evaluation with responders; sealed and held-out results
- Navigable water routing with verified depth; live gauge data
- Persist the Zetaris semantic views through the product UI
- Repo, video and deck links: [fill in at submission]
