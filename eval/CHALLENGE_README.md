# Synthetic challenge set

The 40 PT-BR messages are author-written fictional requests, not collected rescue
messages or generator templates. Names and contact placeholders are fictional.
Texts were reviewed and rewritten by Yussef, a native speaker from Porto Alegre,
on 24/10/2026: 32 rewrites were applied and eight entries marked `ok` kept their
original text. Labels were independently re-derived from the new texts.
Tags identify language and reasoning challenges; truth follows what each text
supports, with omitted fields unknown and explicit negations zero/false.

`challenge_truth.json` is evaluation-only. `expected_landmark` holds a desired
status and canonical OSM name/type/id when available. Duplicate OSM member IDs
are accepted as one place. Salgado Filho airport is labelled with its canonical aerodrome identity;
curated aliases connect its popular name to the snapshot. Escola Estadual Infante
Dom Henrique (Porto Alegre) and Paróquia São Pio X (Mathias Velho, Canoas) now
refer to verified snapshot places. Supermercado Rissul in Guaíba is absent from
the snapshot and requires CALLBACK asking for the place/street; stores in other
cities cannot supply its location. Unnamed places retain unresolved labels
(a generic school may produce ambiguous candidates, still requiring CALLBACK). Truth is
never imported by runtime agents or deterministic matching.

Run `python eval/run_eval.py --offline` for baseline measurements on this set and
generated held-out seeds 101/202. Intake and full are marked unavailable offline;
run without that flag to measure provider methods. Landmark metrics distinguish
identity/status labels from the expected-decision proxy used on other messages.
Synthetic labels, author bias, easy generated templates, a single native reviewer,
and incomplete OSM coverage limit interpretation. No real-message accuracy or
critic benefit is established by offline results.
