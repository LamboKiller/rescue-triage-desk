# Input and output examples

`input_01.json`, `input_02.json`, `input_03.json` contain fictional messages grounded
in public geographic data (3, 2 and 1 messages), not real victims' messages.

Corresponding outputs have `mode=full`, 3/2/1 completed cases and 6/5/3 model-call
records. All 14 saved call records have a routed model and receipt. These are saved
pipeline artifacts, not independently revalidated receipts or evaluation scores.
`tools/make_examples.py:19` reads each input; lines 21–23 call `Pipeline.run` and
serialize the result. Sample mode recomputes input and never reads these outputs.

This audit parsed all six files without regenerating them. After the active
evaluation ends, Yussef can reproduce connected examples with valid credentials,
`SAMPLE_MODE=false` and `python tools/make_examples.py`. This writes output files,
registry/log artifacts and calls sponsor services. `python tools/make_examples.py
--sample` instead replaces them with offline baseline results; label those offline.
