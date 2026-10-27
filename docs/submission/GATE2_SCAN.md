# Gate 2 safety scan

Generated 2026-10-27 01:20 (local time) by `python tools/gate2_scan.py --md docs/submission/GATE2_SCAN.md`. Files considered: 1230 (text files scanned: 465); commit: 4867ff0.

Scope: every file Git would publish (tracked plus untracked-and-not-ignored). `.env` and other `.env.*` files are never opened. Evidence is masked (path:line + first 3 characters).

| Check | Result | Hits |
|---|---|---:|
| Secrets / key patterns | PASS | 0 |
| .env files in publishable tree | PASS | 0 |
| .gitignore covers .env, runtime/, logs/, out/, review/, data-backup/ | PASS | 0 |
| Runtime/log/out/review files tracked | PASS | 0 |
| Absolute personal paths / username | FAIL | 1 |
| E-mail addresses (non-placeholder) | PASS | 0 |
| Phone numbers (non-synthetic) | PASS | 0 |
| CPF numbers | PASS | 0 |
| Files > 50 MB | PASS | 0 |
| Sealed50 / holdout2 paths or references | FAIL | 1 |
| Dummy phone numbers in synthetic fixtures (informational) | INFO | 18 |
| Author first name in comments/docs (informational) | INFO | 47 |

**Overall: FAIL**

## Evidence

```

Absolute personal paths / username - evidence (masked, first 8):
  tools/ablation.py:34

Sealed50 / holdout2 paths or references - evidence (masked, first 8):
  ref tools/ablation.py:15

Dummy phone numbers in synthetic fixtures (informational) - evidence (masked, first 8):
  data/demo/scenario.jsonl:2
  data/demo/scenario.jsonl:7
  eval/reunite_set.jsonl:10
  eval/volunteer_set.jsonl:1
  eval/volunteer_set.jsonl:3
  eval/volunteer_set.jsonl:6
  eval/volunteer_set.jsonl:7
  eval/volunteer_set.jsonl:8

Author first name in comments/docs (informational) - evidence (masked, first 8):
  README.md:273
  app/credibility/reviewer.py:3
  app/pipeline.py:637
  docs/submission/DECK_OUTLINE.md:27
  docs/submission/DEMO_SCRIPT.md:1
  docs/submission/PRE_EXISTING_DECLARATION.md:3
  docs/submission/SPONSOR_GAPS.md:29
  eval/CHALLENGE_README.md:5
```

## Fix before publishing

- Replace absolute personal paths with repo-relative or environment-driven paths (or move the file out of the public repo).
- Remove references to sealed50/holdout2 locations from published code; those sets must never be reachable from the public tree.

Informational rows: dummy phone numbers (sequential/repeated digits, `@exemplo.com`) are fictional fixtures; the author first name appears in decision comments and review metadata (decide whether you want that public).

## What the scan cannot see

- Real people in free-text fixtures that look like ordinary words (names without digits); review `eval/*.jsonl` and `examples/` by eye.
- Photos in `data/` (Wikimedia Commons, credited per file in `data/ATTRIBUTION.md`); the scan checks size only.
- Git history: this scan reads the working tree. Run `git log -p` searches or a history scanner before the first push if any secret was ever committed.
- Ignored folders (`runtime/`, `logs/`, `out/`, `review/`) are verified as ignored but not inspected; do not force-add them.
