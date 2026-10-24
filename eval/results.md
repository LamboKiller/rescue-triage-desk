# V1.3 synthetic evaluation

Author-written synthetic truth; challenge texts reviewed by one native Porto Alegre speaker on 24/10/2026 and labels re-derived. Real-message accuracy unmeasured. No evidence of critic benefit without live ablations. Landmark scores use a decision proxy when identity/status labels are absent. Curated aliases and airport terminal dispatch use the local snapshot.

Generated held-out seeds: [101, 202]. Challenge texts are unchanged.

Mean and nearest-rank p90 use per-message processing time; amortized batch wall time is separate.
Unsupported rate is rejected schema/span/value proposals divided by all proposals, not semantic truth.
Critic change outcomes count changed fields against truth, including removed fields.

## generated

| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 1.0 | 1.0 | 0.0 | 0.0 | 0.6185 | 0.9664 | 0 |
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
| baseline | 0.5 | 0.6 | 0.0 | 0.0 | 0.4706 | 0.905 | 0 |
| intake | unavailable (offline) | - | - | - | - | - | - |
| full | unavailable (offline) | - | - | - | - | - | - |

### baseline fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 0.7931 | 0.6571 | 0.7188 |
| children | 1.0 | 0.1429 | 0.25 |
| elderly | 0 | 0.0 | 0 |
| disabled | 0 | 0.0 | 0 |
| pets | 1.0 | 0.1667 | 0.2857 |
| street | 0.5714 | 0.2222 | 0.32 |
| number | 1.0 | 0.2222 | 0.3636 |
| municipality | 1.0 | 0.4103 | 0.5818 |
| landmark | 0 | 0.0 | 0 |
| cross_street | 0 | 0 | 0 |
| risk_words | 1.0 | 0.5 | 0.6667 |
| already_rescued | 1.0 | 0.1667 | 0.2857 |
| conflicting_counts | 0.3333 | 0.3333 | 0.3333 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 15; expected-decision proxies: 25.

*Landmark combines labelled identity/status accuracy with decision proxies, explicitly counted above.
Detailed family metrics, failures, wall time and critic counts are in results.json.
