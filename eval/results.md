# V1.3 synthetic evaluation

Author-written synthetic truth; challenge texts reviewed by one native Porto Alegre speaker on 24/10/2026 and labels re-derived. Real-message accuracy unmeasured. No evidence of critic benefit without live ablations. Landmark scores use a decision proxy when identity/status labels are absent. Curated aliases and airport terminal dispatch use the local snapshot.

Generated held-out seeds: [101, 202]. Challenge texts are unchanged.

Mean and nearest-rank p90 use per-message processing time; amortized batch wall time is separate.
Unsupported rate is rejected schema/span/value proposals divided by all proposals, not semantic truth.
Critic change outcomes count changed fields against truth, including removed fields.

## generated

| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 1.0 | 1.0 | 0.0 | 0.0 | 0.7735 | 1.141 | 0 |
| intake | 0.9667 | 0.9667 | 0.0 | 1.0333 | 11.7344 | 23.203 | 0 |
| full | 1.0 | 1.0 | 0.0 | 2.3667 | 19.6401 | 31.031 | 2 |

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


### intake fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 1.0 | 1.0 | 1.0 |
| children | 1.0 | 1.0 | 1.0 |
| elderly | 1.0 | 1.0 | 1.0 |
| disabled | 1.0 | 1.0 | 1.0 |
| pets | 1.0 | 1.0 | 1.0 |
| street | 1.0 | 1.0 | 1.0 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 1.0 | 0.9643 | 0.9818 |
| landmark | 0.0 | 0.0 | 0 |
| cross_street | 0 | 0 | 0 |
| risk_words | 0.5 | 0.6667 | 0.5714 |
| already_rescued | 1.0 | 1.0 | 1.0 |
| conflicting_counts | 1.0 | 1.0 | 1.0 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 0; expected-decision proxies: 30.


### full fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 1.0 | 1.0 | 1.0 |
| children | 1.0 | 1.0 | 1.0 |
| elderly | 1.0 | 1.0 | 1.0 |
| disabled | 1.0 | 1.0 | 1.0 |
| pets | 1.0 | 1.0 | 1.0 |
| street | 1.0 | 1.0 | 1.0 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 1.0 | 1.0 | 1.0 |
| landmark | 0.0 | 0.0 | 0 |
| cross_street | 0 | 0 | 0 |
| risk_words | 0.5 | 0.6667 | 0.5714 |
| already_rescued | 1.0 | 1.0 | 1.0 |
| conflicting_counts | 1.0 | 1.0 | 1.0 |

Critic: {"changes_correct": 3, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 3, "messages_with_objections": 5, "objections": 5, "revisions": 5, "revisions_changed_field": 3}.
Landmark identity/status labels: 0; expected-decision proxies: 30.

## challenge

| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0.6 | 0.6 | 0.0 | 0.0 | 0.4824 | 1.0 | 0 |
| intake | 0.975 | 0.975 | 0.0061 | 1.025 | 15.4918 | 27.765 | 0 |
| full | 0.975 | 0.975 | 0.0086 | 3.15 | 53.4765 | 98.859 | 2 |

### baseline fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 0.8333 | 0.8571 | 0.8451 |
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
| conflicting_counts | 0.5 | 1.0 | 0.6667 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 15; expected-decision proxies: 25.


### intake fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 0.8611 | 0.8857 | 0.8732 |
| children | 1.0 | 0.8571 | 0.9231 |
| elderly | 1.0 | 0.8 | 0.8889 |
| disabled | 1.0 | 0.75 | 0.8571 |
| pets | 1.0 | 0.8333 | 0.9091 |
| street | 0.9474 | 1.0 | 0.973 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 0.9744 | 0.9744 | 0.9744 |
| landmark | 0.7857 | 0.7333 | 0.7586 |
| cross_street | 0 | 0 | 0 |
| risk_words | 0.0 | 0.0 | 0 |
| already_rescued | 1.0 | 0.1667 | 0.2857 |
| conflicting_counts | 0.75 | 1.0 | 0.8571 |

Critic: {"changes_correct": 0, "changes_neutral": 0, "changes_wrong": 0, "failed": 0, "fields_changed": 0, "messages_with_objections": 0, "objections": 0, "revisions": 0, "revisions_changed_field": 0}.
Landmark identity/status labels: 15; expected-decision proxies: 25.


### full fields

| Field | P | R | F1 |
|---|---:|---:|---:|
| people | 0.8378 | 0.8857 | 0.8611 |
| children | 1.0 | 0.9286 | 0.963 |
| elderly | 1.0 | 0.8 | 0.8889 |
| disabled | 1.0 | 0.75 | 0.8571 |
| pets | 1.0 | 0.8333 | 0.9091 |
| street | 0.9 | 1.0 | 0.9474 |
| number | 1.0 | 1.0 | 1.0 |
| municipality | 0.9744 | 0.9744 | 0.9744 |
| landmark | 0.8571 | 0.8 | 0.8276 |
| cross_street | 0 | 0 | 0 |
| risk_words | 0.0 | 0.0 | 0 |
| already_rescued | 0.5 | 0.1667 | 0.25 |
| conflicting_counts | 0.75 | 1.0 | 0.8571 |

Critic: {"changes_correct": 18, "changes_neutral": 1, "changes_wrong": 3, "failed": 0, "fields_changed": 22, "messages_with_objections": 18, "objections": 23, "revisions": 18, "revisions_changed_field": 14}.
Landmark identity/status labels: 15; expected-decision proxies: 25.

*Landmark combines labelled identity/status accuracy with decision proxies, explicitly counted above.
Detailed family metrics, failures, wall time and critic counts are in results.json.
