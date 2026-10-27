# Demo script: 3:30, narrated by Yussef (EN narration, PT UI)

Target **3:30** (limit 1-4 min). Read the *Say* column aloud at a calm pace (about 140 words per minute; each row's word count fits its slot). The UI stays in Portuguese on purpose: it is the dispatcher's language. Use fictional data only.
Honesty rule: show **one real Nightshift request with the routed model visible**. If a live call is slow, cut the wait in editing and say so in a caption ("cut: 19 s wait"); never show offline or sample output as live proof.

## Preparation (before you press record)

1. Services up: Zetaris Docker stack and the Nightshift app at `http://127.0.0.1:8088` (the NVIDIA key is already in its **Providers** tab; never open that tab on camera).
2. Desk in connected mode: `SAMPLE_MODE=false` in your local `.env`, then `python run.py serve`; open `http://localhost:8080/v2`. Optional clean state: `python tools/reset_demo.py --demo` (moves runtime state to `runtime/demo_backup`, deletes nothing).
3. Replay time: 06/05/2024 afternoon (picker in the top bar). Message below in the clipboard.
4. Tabs ready, in order: (a) desk `/v2`; (b) Nightshift app request list; (c) a terminal in the repo where `python tools/zetaris_usl.py --check` has just run (scroll to the Rodoviária row); (d) `/v2` on the **Evals** tab.
5. Hide bookmarks, notifications and the taskbar; browser at 100% zoom, 1920x1080. Use `cd` into the repo so the prompt does not show a long personal path.

Message to paste (fictional; keep the spelling):
> socorro estamos dentro da rodoviaria de porto alegre e esta alagando tudo, estou com meus dois bebes

## Shot list and narration

| Time | Show (click path) | Say |
|---|---|---|
| 0:00-0:20 | Title slide, or the `/v2` map at the May 2024 replay (60x playing). | "In May 2024 the Rio Grande do Sul floods produced thousands of rescue requests as informal text: half an address, 'my two babies', a landmark. Dispatchers had to work out where, how many, who is vulnerable and what can safely go. This is Rescue Triage Desk." |
| 0:20-0:45 | Top bar: the mode badge must **not** say "Modo amostra · offline". Click **Nova emergência**, paste the message, submit. | "I paste a new message. The desk runs connected: Zetaris for data, Nemotron through Meterless Nightshift for language. Nothing is dispatched automatically; a human approves every step." |
| 0:45-1:10 | The case appears in the queue; open it. Bottom bar / **Agentes** shows agents running live (intake, critic, location). Show quoted evidence in **Resumo**. | "Agents work live. Intake extracts fields with exact quotes, a Critic challenges each claim, Location proposes a place. Then code checks the landmark and derives the count: sender plus two babies is three, marked 'confirmar'. The model reads language; code does the arithmetic." |
| 1:10-1:35 | Open the call panel (**Modelo, comprovante e duração**). Switch to the Nightshift app tab and show the same request with its model and receipt. | "Every call is logged with the model that actually answered and a receipt. Nightshift races its lanes, so the requested model is not enough. Here is the winner, the receipt and the seconds. This is the one real sponsor request in this recording." |
| 1:35-2:00 | Back to the case: **Meios**, **Qual meio enviar**, pick the recommended boat. Click **Ver rota**: land leg plus a straight water leg, warnings visible. | "Meios lists every asset with a reason and blocks unsafe ones. The route is land on OpenStreetMap plus a water leg that is a labelled straight-line estimate, because retrospective flood depth cannot certify a safe route. We say so on screen." |
| 2:00-2:20 | **Confirmar localização**, tick the checklist, click **Despachar**. Open **Missões** and show the **[SIMULADO]** GPS fix. | "The human confirms the location, reads the cautions and dispatches; there is an undo. GPS fixes are simulated and labelled. We have no real fleet integration." |
| 2:20-2:45 | **Retorno** tab: callback questions (at most three), the **[SIMULADO]** citizen reply; submit it and show the case re-triaging. | "When something is missing, a Callback agent asks at most three questions about open items only. The citizen's reply goes back through the same checks and the case is triaged again. No invented facts." |
| 2:45-3:00 | **Registro** tab (events and versions). Optional: a terminal call with a stale `expected_version` returning 409. | "State lives in our World Model, a Meterless Engine adaptation: append-only journal, replay, retained conflicts, version gates and human-only transitions. A stale command gets a 409. Six conformance tests pass." |
| 3:00-3:15 | Terminal: `zetaris_usl.py --check` output, the Rodoviária row (4,514 flooded segments in its municipality) and the shelter quality line (734 checked, 62 over capacity). | "Zetaris holds five sources. A semantic layer joins landmarks, flood exposure, pumps and shelters in SQL. Rodoviária sits inside the flood extent, and a quality rule flags 62 of 734 shelter snapshots over capacity." |
| 3:15-3:30 | **Supervisor** tab for two seconds, then **Evals**. End on the closing slide with the repo URL. | "A supervisor proposes one action and a human accepts. Our live test: 29 of 30 correct, zero unsafe, 20 seconds average. These are our own development sets; sealed results come after the freeze. Code decides, agents explain, humans approve." |

## Fallbacks

- Live call fails or times out: say "the desk degrades visibly", show the degraded flag and the deterministic result, then re-record the live segment. Do not label offline output as live.
- No revision was triggered: say the critic had no objection; do not invent one.
- Decision is not `SEND_CANDIDATE`: show **Pedir retorno**, explain the block, never force an approval.
- Quote only numbers that are in the README eval table (commit `4867ff0`, 26 Oct 2026).

## Do not show

- `.env`, the Nightshift **Providers** tab, any key or token, terminal history, environment dumps.
- Zetaris, S3 or NVIDIA credentials in any settings screen; Docker Desktop settings.
- Personal data: your desktop, browser profile, bookmarks, other chats, paths that contain your username.
- The planning repo (`open-agent-hackathon-2026`), `review/` folders, sealed50 / holdout2, build reports (`*_REPORT.md`).
- Real citizen messages: only the fictional message above.

## After recording

Check duration (1-4 min), that the model name and receipt are readable at 1080p, and that no credential or personal path flashed by. Upload the video and keep the URL for the submission form (`GATE2_CHECKLIST.md`).
