# V1.3 synthetic evaluation

Author-written synthetic truth; native review pending. Real-message accuracy unmeasured. No evidence of critic benefit without live ablations. Landmark scores use a decision proxy when identity/status labels are absent. Curated aliases and airport terminal dispatch use the local snapshot.

Generated held-out seeds: [101, 202]. Challenge texts are unchanged.

Mean and nearest-rank p90 use per-message processing time; amortized batch wall time is separate.
Unsupported rate is rejected schema/span/value proposals divided by all proposals, not semantic truth.
Critic change outcomes count changed fields against truth, including removed fields.

## generated

| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 1.0 | 1.0 | 0.0 | 0.0 | 0.679 | 1.1234 | 0 |
| intake | unavailable (offline) | - | - | - | - | - | - |
| full | unavailable (offline) | - | - | - | - | - | - |

### baseline fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 1.0 | 1.0 | 1.0 |
| children | 1.0 | 1.0 | 1.0 |
| elderly | 1.0 | 1.0 | 1.0 |
| disabled | 1.0 | 1.0 | 1.0 |
| pets | 1.0 | 1.0 | 1.0 |
| street | 1.0 | 0.9231 | 0.96 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 1.0 | 1.0 | 1.0 |
| landmark | 0.0 | 0.0 | 0 |
| cross_street | 0 | 0 | 0 |
| risk_words | 1.0 | 1.0 | 1.0 |
| already_rescued | 1.0 | 1.0 | 1.0 |
| conflicting_counts | 1.0 | 1.0 | 1.0 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 0; expected-decision proxies: 30.

## challenge

| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0.55 | 0.7 | 0.0 | 0.0 | 1.4687 | 2.5246 | 0 |
| intake | unavailable (offline) | - | - | - | - | - | - |
| full | unavailable (offline) | - | - | - | - | - | - |

### baseline fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 0.6957 | 0.4571 | 0.5517 |
| children | 0 | 0.0 | 0 |
| elderly | 1.0 | 0.2 | 0.3333 |
| disabled | 0 | 0.0 | 0 |
| pets | 1.0 | 0.3333 | 0.5 |
| street | 0.8571 | 1.0 | 0.9231 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 0.9737 | 0.9487 | 0.961 |
| landmark | 0 | 0.0 | 0 |
| cross_street | 0 | 0 | 0 |
| risk_words | 1.0 | 1.0 | 1.0 |
| already_rescued | 1.0 | 0.1667 | 0.2857 |
| conflicting_counts | 0.6 | 1.0 | 0.75 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 15; expected-decision proxies: 25.

*Landmark combines labelled identity/status accuracy with decision proxies, explicitly counted above.
Detailed family metrics, failures, wall time and critic counts are in results.json.
