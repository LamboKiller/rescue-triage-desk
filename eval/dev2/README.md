# dev2 — second labelled dev set (PT-BR, ~180 messages)

All texts are original (written for this set, fictional people, phones `51 9XXXX-0000`). ~66% target known failure classes,
~20% are clean variants of cases already handled (`reg_*`, regression guard), ~14% hard adversarial/edge (`adv_*`).
Streets, bairros and landmarks in `key_fields` exist in `data/streets_flood.csv` / `data/landmarks.csv` (checked by tests).

`messages.jsonl` is generated: edit `items_a.py` / `items_b.py`, then `python -m eval.dev2.build` and `python -m eval.dev2.check`.

## Item fields
`id`, `text`, `replay_date` (replayed at 14:00-03:00), `expected_decision` (SEND | SEND_APPROX | CALLBACK | REVIEW | RESCUED),
`expected_people` (int or null = unknown/not applicable), `count_basis` (stated | derived | unknown | none),
`expected_route` (street, landmark, ambiguous_place, already_rescued, not_a_request_or_injection, not_a_rescue, out_of_area,
incomplete, or null = not scored), `expected_precision`, `key_fields`, `class`, `bucket`, `rationale`, `ambiguous`, `in_area`.

## Label rules
Unknown count does not block SEND; bairro/street without number + life risk -> SEND_APPROX; partial rescue -> SEND (remaining
people); info/volunteer/animals-only/injection -> REVIEW; truly out-of-area city -> CALLBACK (route out_of_area); derived counts
are computed (writer + listed relatives; pets not counted). `ambiguous=true` items are scored in a separate row.

## Scoring (`eval/run_dev2.py`)
`decision` treats SEND and SEND_APPROX as one family; `strict` requires the exact label. `unsafe` = SEND family when expected
is not. `missed SEND` = expected SEND family but got something else. People scored only where `expected_people` is an int.

```
python eval/run_dev2.py --offline [--only derived_count,reg_,d2-001] [--sample 40 --seed 1] [--jobs 3]
python eval/run_dev2.py --live --jobs 2          # Orbit only; needs provider settings in .env
```
Output: `out/dev2/dev2_<mode>.json|.md` (+ timestamped copy). Exit code 1 if any unsafe send in the non-ambiguous set.

## Self-check
`relabel_sample_ids.json` / `relabel_result.json`: 40 random items re-labelled from the text alone. Same author, so it
measures label consistency, not independent inter-annotator agreement.
