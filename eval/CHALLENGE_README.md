# Synthetic challenge set

The 40 PT-BR messages are author-written fictional requests, not collected rescue
messages or generator templates. Names and contact placeholders are fictional.
Native-speaker review and rewriting are pending; V1.2 leaves message texts intact.
Tags identify language and reasoning challenges; truth follows what each text
supports, with omitted fields unknown and explicit negations zero/false.

`challenge_truth.json` is evaluation-only. `expected_landmark` holds a desired
status and canonical OSM name/type/id when available. Duplicate OSM member IDs
are accepted as one place. Salgado Filho airport is absent from the supplied
snapshot; its desired resolved label is retained so the missing coverage counts
as a failure. Fictional and unnamed places remain unresolved labels. Truth is
never imported by runtime agents or deterministic matching.

Run `python eval/run_eval.py --offline` for baseline measurements on this set and
generated held-out seeds 101/202. Intake and full are marked unavailable offline;
run without that flag to measure provider methods. Landmark metrics distinguish
identity/status labels from the expected-decision proxy used on other messages.
Synthetic labels, author bias, easy generated templates, pending native review,
and incomplete OSM coverage limit interpretation. No real-message accuracy or
critic benefit is established by offline results.
