# Rescue Triage Desk V1 implementation plan

Goal: implement the supplied BRIEF_V1 and binding V1 design, in this repository, as one agent.
Architecture: quoted Intake -> Critic -> at most one revision; Python tools validate, locate, score and append registry events; humans control dispatch. Python 3.12 standard library and one HTML/vanilla JS frontend.
Spec: C:/Users/yusse/AppData/Local/hermes/cache/scratch/rtd-build/BRIEF_V1.md.

User supplied execution method: implement and verify autonomously, one agent, local commits, no push. This overrides skill handoff/reviewer delegation requirements.

1. Data and privacy: prepare derived street/date CSV using indexed bbox and ray casting; normalisation, redaction and exact-span tests. No raw geography committed.
2. Registry: JSONL append-only events, provenance idempotency, per-process lock plus OS file lock, optimistic versions, human location/transition gates; concurrency and rebuild tests.
3. Providers and pipeline: bounded Nightshift calls with true-model receipts; Zetaris/S3 clients; sample regex baseline with unavailable agents; 3 workers, 15-message and 8-minute budgets; fake-provider tests.
4. Product: CLI, HTTP API, Portuguese queue and detail, evidence panels and explicit human actions; ephemeral HTTP tests.
5. Evidence: seeded generator, separate ground truth, held-out ablations, examples, load/smoke scripts, README/Docker/attribution; execute all seven self-checks and report measured results and live gaps.

Review focus: untrusted values despite matching quotes; future/unknown publication dates; concurrent duplicate deliveries and stale human commands; raw identifiers in errors/logs; slow provider calls exceeding global budget.

Decisions: publication times are unknown so observed-water overlap is labelled retrospective context and excluded from contemporaneous scoring. Sample mode uses the documented regex baseline, never agent answers. UI actor labels are audit labels, not authentication; localhost demo is a trusted-operator deployment.

Implementation status: all five build tasks implemented and offline checks run.
Local git commit/status-clean requirement is blocked by the session's read-only
.git permission: git cannot create .git/index.lock. No push or git configuration
change was attempted. Sponsor live calls, Python 3.12/Docker execution and browser
rendering remain unverified (no connected services/keys or available browsers).
Review was performed by the author, following the user's one-agent constraint;
there was no independent agent review. Review fixes: literal value corroboration,
replay analysis versioning, retry/message trace correlation, future-message gating,
and response-deadline bounds for slow data sources. See tests and V1_REPORT.md.
