# Arca — pre-existing work declaration

**Team Orbital · Open Agent Hackathon 2026 · attested 27 October 2026**

## A. Pre-existing components

**Pre-existing components: none.** All Arca code, design, data preparation and evaluations were created during the build window
(22–27 Oct 2026; git history starts 24 Oct 2026, `git log --reverse` → `2026-10-24 01:44 -0300`). We reused only open-source
libraries and public open datasets, listed with their licences in section B.

## B. Third-party open-source libraries and open datasets shipped in the repo

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

## C. Built during the build window

Everything else in the repository: pipeline, agents (intake, critic, location with tools, hazard critic, needs, duplicate reviewer,
callback planner, feedback, mission planner/brief, supervisor, red team, credibility module), World Model registry, data preparation
scripts (`tools/prepare_*.py`) and their derived files, dispatcher UI, replay timeline, tests and evaluations.

## Attestation

We attest that this declaration is complete and accurate.

Team **Orbital**, 27 October 2026.
