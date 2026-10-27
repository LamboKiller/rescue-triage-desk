# Arca — pre-existing work declaration — OWNER DRAFT, NOT ATTESTED

Yussef must complete and sign this before submission. Cutoff: **21 October 2026, 21:00**. Applicable organizer timezone: **TO CONFIRM**.
Evidence available in the repo: git history starts **2026-10-24 01:44 -0300** (`git log --reverse`); every component below that is marked
"external" existed outside this repository before or independently of that history. Dates not shown in a source file stay **TO CONFIRM**.

## A. Own work prepared before the event (inventory carried into the repo)

| Component | Before cutoff? | Creation date (tz) | Author / evidence | How it is used |
|---|---|---|---|---|
| Public source packs D1/D2/D3 (OSM streets, IBGE, UFRGS water, Copernicus, closures) | TO CONFIRM | Prepared 21–23 Oct 2026 per `data/ATTRIBUTION.md`; time/tz TO CONFIRM | Owner; backup lacks D1–D3 manifests (gap) | Source of `data/streets_flood.csv`, `data/hazards/*`, `data/depth/*` via `tools/prepare_*.py` |
| R3 red-team findings | TO CONFIRM | TO CONFIRM | Owner planning notes (private) | Requirements and test ideas |
| `gen_proto.py` seeded-template generator | TO CONFIRM | TO CONFIRM | Owner prototype (external) | Ideas adapted in `tools/generate_messages.py` |
| `engine_proto.py` registry invariants | TO CONFIRM | TO CONFIRM | Owner prototype (external) | Adapted as JSONL/human-gate World Model, not ported |
| Gate 0 Nightshift / Zetaris / S3 contracts and stdlib S3 SigV4 signing | TO CONFIRM | TO CONFIRM | Owner Gate 0 probes (external) | `app/llm/nightshift.py`, `app/data/zetaris.py`, `tools/load_zetaris.py` |
| Curated landmark alias list (24 rows) | TO CONFIRM | Used from 24 Oct 2026 | Owner / agents | `data/landmark_aliases.csv` |
| Fleet dispatch rules research baseline (v1.0.0-research) | No (created 2026-10-24) | 2026-10-24 | Research agent; citations in `data/fleet/dispatch_rules.json` | Asset screening |
| Any additional prior component | TO CONFIRM | TO CONFIRM | Owner adds all other prior work | TO CONFIRM |

## B. Third-party material shipped in the repo

| Component | Licence | Location |
|---|---|---|
| F2 OSM road graph, cached source responses, HAND edge/launch estimates (built 2026-10-26; source dates retained) | ODbL 1.0 (OSM derivatives); Copernicus EMS EMSN194 depth terms unresolved as above | `data/roads/`, exact queries/download dates in `data/roads/ATTRIBUTION.md`; derived by `tools/prepare_roads.py` |
| MapLibre GL JS (vendored) | BSD-3-Clause | `app/web/v2/vendor/maplibre-gl.js`, `.css` |
| Noto Sans glyphs | SIL OFL 1.1 | `data/map3d/fonts/` (`OFL.txt`) |
| Protomaps basemap extract, style, sprites | ODbL (data), BSD-3 (style), licence file in `data/map3d/sprites/LICENSE.txt` | `data/map3d/basemap.mbtiles`, `offline_style.json`, `sprites/` |
| OpenStreetMap-derived streets, landmarks, buildings | ODbL 1.0 | `data/streets_flood.csv`, `data/landmarks.csv`, `data/map3d/buildings/` |
| Microsoft ML Building Footprints / Google Open Buildings 2.5D | CDLA-Permissive-2.0 / CC BY 4.0 | `data/map3d/buildings/` |
| Skadi / SRTM terrain tiles | Public-domain components, attribution | `data/map3d/terrain-rgb/` |
| UFRGS/Possantti observed flood layers (Zenodo 14617475) | CC BY 4.0 per brief (unverified on record page) | `data/hazards/flood_*.geojson` |
| Copernicus EMS EMSN194 flood delineation and HAND depth | Copernicus attribution; per-product terms unresolved | `data/hazards/`, `data/depth/`, `data/map3d/water/` |
| DNIT / DMAE / Porto Alegre bulletins (closures, events) | Reuse terms not supplied | `data/hazards/closures.*`, `events.*` |
| IBGE Censo 2022; IBGE municipality list (497) | Public IBGE data | `data/rs_municipios.csv` |
| Wikimedia Commons flood photos (22) | CC BY 4.0 per file | `data/photos/` (`ATTRIBUTION.md`) |

Full per-layer credits: `data/ATTRIBUTION.md`, `data/map3d/MANIFEST.md`, `data/photos/ATTRIBUTION.md`.

## C. Built during the event

Everything under `app/`, `eval/`, `tests/`, `tools/`, `docs/` other than the items in A and B: pipeline, agents (intake, critic, location with tools, hazard critic,
needs, duplicate reviewer, callback planner, feedback, mission planner/brief, supervisor, red team, credibility module), World Model registry, dispatcher UI, replay timeline, evaluations.

Owner attestation / name / date: **PENDING**. Replace every TO CONFIRM with substantiated facts, disclose this inventory in the deck and form,
and do not submit this draft as a completed declaration.
