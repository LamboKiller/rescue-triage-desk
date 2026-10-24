# Three-minute demo script

Yussef: record only after the active evaluation finishes. Use fictional data and
a trusted local browser. Keep `.env`, credentials and private desktop content out
of frame. This recording needs one real Nightshift request, not sample-mode output.
If latency requires an edit, label the cut and show actual request elapsed time;
never portray a failed/offline call as live sponsor proof.

Preparation (not run by this audit): configure local credentials and
`SAMPLE_MODE=false`, run `python run.py serve`, open http://localhost:8080.
Prepare a terminal showing only the new run's trace, a browser tab for
http://localhost:8080/api/cases, and the slides from `DECK_OUTLINE.md`.
Use replay `2024-05-06T14:00:00-03:00`. Do not clear shared runtime state.

| Time | Click/show | Narration |
|---|---|---|
| 0:00–0:20 | Title/RS map slide with fictional rescue message. | “During the May 2024 RS floods, informal messages mixed location hints, vulnerability and uncertainty. This desk helps an operator review evidence.” |
| 0:20–0:40 | Page connected health state. Paste the exact message below into **Cole uma mensagem de demonstração**, show replay time, click **Analisar pedido** once. | “This new request goes through Meterless Nightshift, with Zetaris as the connected data layer.” |
| 0:40–1:10 | Processing, then new case in **Fila de revisão**. Show **Intake → Crítica → Uma revisão**, panels **Leitura inicial**, **Crítica**, **Revisão**, **Localização**. | “Intake extracts evidence, Critic challenges claims, and at most one revision follows objections. Location proposes a place for code to verify.” If no revision triggered, explicitly show/say that; do not invent one. |
| 1:10–1:35 | **Modelo, comprovante e duração** and matching fresh `logs/run_<id>.jsonl` record/stdout. Point to role, message ID, requested model, actual routed model and receipt. | “Nightshift races Nemotron lanes. This receipt identifies the winner for this call; the requested model alone does not.” Show metadata, never hidden reasoning or credentials. |
| 1:35–2:00 | **Ponto de referência**: Rodoviária match/source. Expand **Campos e verificações determinísticas** and show **Motivo da decisão**. | “Public OSM context and curated aliases verify this landmark. Code derives sender plus two babies, marked “Contagem derivada — confirmar”. Both location and inferred count need human verification.” If the expected flag/match is absent, disclose the actual result. |
| 2:00–2:25 | For an eligible candidate, click **Confirmar localização**, then **Aprovar despacho** with `operador-demo`; show status/version change. | “Approval is a recorded human decision. The model cannot approve a dispatch.” If not `SEND_CANDIDATE`, show **Pedir retorno** and explain the block; never force approval or claim field confirmation. |
| 2:25–2:45 | `/api/cases`: locate the new case by message ID, show version, status and provenance; return to queue. | “The World Model registry rebuilds state from append-only events, retains conflicting updates and rejects stale commands. Offline tests prove its human-transition and HTTP queue behavior.” |
| 2:45–3:00 | Evaluation/limitations slide, then repo/sponsor closing slide. | “Evaluation results await Orbit's verified live run. Synthetic tests do not establish real-message accuracy. Zetaris grounds context; Nightshift interprets language; code and humans control decisions.” |

Exact message (preserve the supplied spelling):

> socorro estamos dentro da rodoviaria de porto alegre e esta alagando tudo, estou com meus dois bebes

Evaluation slide placeholder:

Live eval 24/10 (challenge set, 40 hand-written): decision accuracy rules 0.60 → intake agent 0.975 → full loop 0.975; field F1 rules→full: children 0.25→0.96, elderly 0→0.89, street 0.32→0.95; critic changes right 18/22. Caveat: rules tuned on this set after the first run; numbers optimistic.

Yussef checks final duration (1–4 minutes), readability of at least one real
Nightshift receipt/model, and that no credentials appear. Upload the video/deck
and record shareable URLs plus repository URL in the submission. No recording,
upload or live request was performed in this audit.
