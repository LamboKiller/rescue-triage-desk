# Mission planner implementation plan

Spec: BRIEF_M1.md and BRIEF_COMMON.md in rtd-build. Python stdlib, existing fleet evaluator,
Nightshift streaming client, existing MapLibre/canvas UI. One agent; no commits or new dependencies.

- [x] Needs: exact evidence spans, bounded tags, deterministic fallback, per-message-version cache;
  test quotes, groups, failures, cache and history before implementing.
- [x] Planner: replay-bounded cases, fleet intersection, sourced inventory, capacity splits,
  life-safety then nearest-neighbour order, auditable math and independent approval checks.
- [x] Brief: one existing-client call, existing cited-number validator, visible template fallback.
- [x] Registry: additive action branch and projection kinds; delegate mission validation and atomic
  multi-case projections to app/missions/actions.py. Test durable reversal, stale versions and races.
- [x] API: app/web/server.py extends existing server without editing unowned run.py. Provide GET
  proposals/detail, POST approval/cancellation and existing case mission actions with origin gates.
- [x] UI: Missões tab, requirements/quotes/reasons/blockers, approval/cancel, numbered dashed map.
- [x] Eval: 12 original synthetic scenarios on real data points and 15 needs messages; offline/live
  mode, grouping/order/capacity/veto metrics. Full suite and JS syntax checks; ≤45-line report.

Ruling: production inventory is absent from data; never fabricate capacity. A dated, sourced
operator inventory JSON is supplied to the mission server; missing values block approval.
Ruling: existing launcher has no POST extension hook; add a documented app.web.server entrypoint
within owned files. Keep run.py unchanged. Browser acceptance is assigned to Orbit by the brief.
Ruling: task specification is already supplied and execution explicitly requested; no additional
design approval, worktree, commits, or subagents (brief overrides skill defaults).

Baseline: feature absent; prior report records unknown registry actions. Existing suite started.

Verification ledger: initial tests failed for absent modules; behavior tests exposed capacity reservation, rear-house extraction, and assignment invalidation gaps; fixed with regressions. Baseline suite: 163 passing. Mission tests: 27 passing. Final full suite: 191 tests passed in 182.804 s (exit 0). Offline mission eval: 12/12 groups, no capacity/veto errors, 100% life-safety order; needs 15/15 tags and groups. JS syntax and unmocked real-replay HTTP approval/cancel checks pass. Live/provider and browser acceptance are not claimed.
