# V1 synthetic evaluation

Synthetic text-supported truth only; real-message accuracy UNMEASURED. No claim that the critic improves accuracy without live ablations. Seeds vary counts, streets and vulnerabilities; request-rate assumptions are not validated.

Tuning seed: 7 (families 0–7). Held-out seeds: [101, 202]; all 15 families, including held-out families 8–14.

| Method | Decision accuracy | Unsupported rate | Mean s/message | Calls/message |
|---|---:|---:|---:|---:|
| baseline | 1.0 | 0.0 | 0.263 | 0.0 |
| intake | 1.0 | 0.0 | 3.1328 | 1.0 |
| full | 0.9333 | 0.0 | 9.7422 | 2.0667 |

## Regex baseline fields

| Field | Precision | Recall | F1 |
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
| risk_words | 1.0 | 1.0 | 1.0 |
| already_rescued | 1.0 | 1.0 | 1.0 |
| conflicting_counts | 1.0 | 1.0 | 1.0 |

Unsupported rate counts span/schema/value rejections; semantic errors are reflected in field metrics.
The offline baseline emits only literal spans, so a zero rejection rate is expected and does not imply correctness.
Wall time/message is amortized run time, including deterministic tools and registry; provider retries are in traces.
Detailed counts and per-template decision accuracy are in results.json.
