# V1 build verification

Measured on 2026-10-24, Windows, Python 3.11.16 (target remains 3.12).
Only standard-library mocks and local offline runs were used for provider tests.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 30 passing tests, no skips |
| Registry concurrency | 10 writers, 200 deliveries, 100 unique events, zero lost updates |
| Registry gates | idempotency, optimistic conflict, human-only transitions, location before approval, rebuild, stale retention and changed replay covered |
| `python tools/prepare_data.py` | 12,586 street/municipality rows; 31 road closures |
| Generator seeds 7 / 101, n=15 | 15 each; separate truth; deterministic test passes |
| Sample CLI input 01 | exit 0, sample_offline, no partial results; candidate + callback + reported rescue |
| Ephemeral HTTP test | POST /run 200, GET /api/cases 200, human action version 1 to 2, stale action 409; health offline; over-budget batch 400 |
| `python eval/run_eval.py --offline` | 30 requests, seeds 101/202, regex decision accuracy 1.0; live ablations unavailable |
| JavaScript / Python syntax | `node --check` extracted inline script and `python -m compileall` pass |
| Packaging / identifier check | `python tools/audit_repo.py`: under 2 MB excluding .git; zero heuristic CPF/phone/credential matches in public files |
| Git | no existing commits; commit attempt rejected because .git is read-only; working tree remains untracked |
| Browser rendering | not verified: computer-use returned no available browsers |
| Nightshift, Zetaris, S3, Docker, Python 3.12 | not run live in this sandbox |

| Municipality | Streets | May 6 sampled water | May 8 sampled water |
|---|---:|---:|---:|
| Porto Alegre | 6297 | 1351 | 1 |
| Canoas | 1652 | 579 | 0 |
| Eldorado do Sul | 316 | 198 | 0 |
| São Leopoldo | 1898 | 655 | 0 |
| Novo Hamburgo | 1826 | 226 | 2 |
| Guaíba | 597 | 221 | 0 |

Normalized aliases and vertex/midpoint membership explain differences from R3's
intersecting-way counts. Water overlap is retrospective and excluded from score:
publication availability is not established for original per-date layers.
The supplied bundle is a 2025 release. May 8 zeros are coverage differences, not
proof of recession. No permanent-water subtraction or safe-route claim is made.

Evaluation field metrics are in `eval/results.md`; perfect template decision
accuracy does not establish real-world accuracy. Unsupported rate is a rejection
metric, not a semantic-truth guarantee. Sample trace is an actual offline summary;
no live model receipts or live multi-agent outcomes are claimed.

To complete owner-side gates: configure .env, load S3/Zetaris, run smoke_live.py,
then regenerate examples and evaluation in connected mode. Run tests with Python
3.12, visually inspect the web page, and create local commits. Never push as part
of this build. Missing D1–D3 manifests remain a provenance gap; surviving inventories
identify UFRGS record 14617475 and collection 11164049.
