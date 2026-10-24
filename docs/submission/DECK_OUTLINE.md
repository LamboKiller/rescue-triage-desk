# Submission deck outline — 10 slides

Each slide has exactly three content bullets. Rubric labels map coverage, not
predicted scores. Orbit alone fills verified live evaluation results.

| Slide / title | Three bullets | Visual | Rubric |
|---|---|---|---|
| 1. Rescue Triage Desk | May 2024 RS flood replay<br>Portuguese evidence-linked review queue<br>Human approval before dispatch | RS map with fictional message | Impact 30; Product & UX 10 |
| 2. The review bottleneck | Informal messages omit precise locations<br>People/vulnerability can be ambiguous<br>Operators need provenance and uncertainty | Annotated Rodoviária message | Impact 30 |
| 3. Message to reviewable case | Intake extracts quoted evidence<br>Critic enables at most one revision<br>Location proposals enter deterministic checks | Pipeline to dispatcher page | Technical 20; Demo 15 |
| 4. Zetaris grounds context | Local REST queries OAH_S3 tables<br>SeaweedFS stores CSVs with inferSchema false<br>Runtime reads streets/landmarks; offline uses local files | REST/S3 flow and table inventory | Technical 20; Sponsor tech 10 |
| 5. Nemotron with receipts | Nightshift is the primary AI provider<br>Supplied deployment races Lightning 30B and Super VL 120B<br>Calls show actual model, receipt and timing | Real masked trace paired with page panel | Sponsor tech 10; Technical 20 |
| 6. World Model case memory | Append-only events rebuild state<br>Stale/conflicting observations remain inspectable<br>Human commands require expected versions | State diagram and real test names | Innovation 15; Sponsor tech 10 |
| 7. Live Rodoviária walkthrough | Submit one fresh Nightshift request<br>Show verified landmark and derived-count flag<br>Confirm location and approve only eligible candidates | Actual page recording/screenshots | Demo 15; Product & UX 10 |
| 8. Evidence and evaluation | Offline suite checks invariants and failures<br>Orbit supplies verified live results/methodology<br>Synthetic labels do not prove real-message accuracy | Evaluation placeholder with source/date fields | Technical 20; Demo 15 |
| 9. Safety and limits | Retrospective maps cannot certify route safety<br>Code-derived counts/place checks remain reviewable<br>Trusted-operator demo needs production identity/retention | Evidence, uncertainty and human-gate case view | Impact 30; Product & UX 10 |
| 10. Reproducibility and declaration | Repo has run.py, POST /run, examples and Dockerfile<br>Declare work before 21/10/2026 21:00 with timezone<br>Supply repo/video/deck/sponsor-explanation links | Link/QR panel and owner-approved inventory | Demo 15; Sponsor tech 10; Innovation 15 |

Slide 8 placeholder:

Live eval 24/10 (challenge set, 40 hand-written): decision accuracy rules 0.60 → intake agent 0.975 → full loop 0.975; field F1 rules→full: children 0.25→0.96, elderly 0→0.89, street 0.32→0.95; critic changes right 18/22. Caveat: rules tuned on this set after the first run; numbers optimistic.

World Model proof: `RegistryTests.test_human_transition_gate_and_versions`,
`RegistryTests.test_stale_retained_and_rebuild`, and
`PipelineTests.test_http_run_queue_action_and_stale_version`.
Do not present loaded closures as routing, local aliases as runtime Zetaris
queries, or any lane as used without a receipt. Yussef must render/export/upload
the deck; this Markdown is an outline, not the submitted deck.
