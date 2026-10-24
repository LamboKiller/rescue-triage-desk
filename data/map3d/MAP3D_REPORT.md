# MAP3D acquisition report — 24 October 2026

**Result:** offline data acquired using one agent, Python stdlib, zero installs. MAP3D is about **55 MB**; the complete current workspace is about **145 MB**, below 150 MB including existing DEPTH inputs. Exact bytes/hashes: `manifest.json` / `payload_sizes.json`. Transfer conservative bound **313 MB**, below 1.5 GB; the ledger includes a 100 MB allowance for early overwritten concurrent request logs. Raw downloads were hashed then removed; only `out/MAP3D/` contains retained changes.

| Source | Licence | Coverage | Resolution | Verified size | Offline? | Effort/status |
|---|---|---|---|---|---|---|
| [OSM](https://www.openstreetmap.org/copyright) | ODbL | AOI + 5 zones | footprints/tags | 545,593 AOI objects | yes | acquired |
| [Microsoft](https://github.com/microsoft/GlobalMLBuildingFootprints) | CDLA-Permissive-2.0 | AOI | ML roofprints | 113.93 MB source gzip | yes | acquired/clipped |
| [Google 2.5D](https://sites.research.google/gr/open-buildings/temporal/) | CC BY 4.0 elected | Brazil + 5 zones | effective 4 m | sampled COG blocks | yes | height enrichment done |
| [Overture](https://docs.overturemaps.org/guides/buildings/) | ODbL | global / Brazil | footprints + optional height/floors | 533 MB first Parquet object | yes | full AOI query deferred |
| [ANADEM v1](https://hge-iph.github.io/anadem/) | data grant unclear; code MIT | South America | 30 m vegetation corrected | 22J TIFF 1.581 GB | pending licence | HEAD + range verified |
| [Copernicus GLO-30](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) | Copernicus open licence | AOI S30/S31 W052 | 1″ DSM | 85.46 MB / two TIFFs | yes | listing + HEAD verified |
| [FABDEM 1.2](https://research-information.bris.ac.uk/en/datasets/fabdem-v1-2/) | CC BY-NC-SA 4.0 | AOI crosses two groups | 1″ ground corrected | 865 MB + 2.135 GB ZIPs | NC restriction | excluded; headers verified |
| [Skadi/SRTM](https://registry.opendata.aws/terrain-tiles/) | public-domain regional components; credit sources | AOI + margins | 1″ merged surface | 32.88 MB HGT.gz → 1.45 MB grid + 12.20 MB PNG | yes | acquired/decoded |
| [POA MDT 2010](https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/C01_URBAN/urb_mdt_2010_102100/ImageServer?f=pjson) | service licence blank | POA, incomplete metro | 1 m | export unmeasured | online only pending grant | metadata verified |
| [Protomaps](https://docs.protomaps.com/basemaps/downloads) | ODbL Produced Work; style BSD | AOI z0–15 | vector tiles | **27.17 MB MBTiles** | yes | 2,716 tiles acquired |
| [OpenFreeMap](https://openfreemap.org/quick_start/) | OSM / OpenMapTiles attribution | global | z0–14 vector | not downloaded | permitted limits | no-key fallback |
| [CARTO](https://carto.com/legal/basemap-terms/index.html) | service terms | global | raster/vector | not downloaded | no bundle | current free tier requires key |
| [Google 3D](https://developers.google.com/maps/documentation/tile/policies) | proprietary | Brazil confirmed; POA mesh unverified | textured mesh | **0 tiles fetched** | no redistribution | optional online |
| [Cesium ion](https://cesium.com/legal/terms-of-service/) | service terms; source OSM ODbL | global OSM / POA | extrusions, not photoreal | **0 tiles fetched** | no ion bundle | token required |

**Buildings.** OSM AOI tag presence: height **712 / 545,593 (0.131%)**, levels **4,128 (0.757%)**; either **0.848%**. Counts include points/relation members. Microsoft has **909,695** intersecting footprints and **0% usable height** locally. Google supplies annual 2016–2023 rasters, not individual-building counts; 2023 height samples enrich OSM-first footprints plus non-overlapping Microsoft additions. Height fields identify community tags, ML estimates, inferred levels × 3 m, or null. Contemporary footprints are not a May 2024 reconstruction. Overture AOI count/height percentage remains **unmeasured**, not zero.

| Core zone (approximate rectangles) | Buildings | Usable height | Explicit OSM height |
|---|---:|---:|---:|
| Centro / Rodoviária | 14,761 | 96.82% | 422 |
| 4º Distrito / Farrapos | 10,656 | 95.47% | 5 |
| Humaitá / Sarandi / Arena | 35,176 | 95.07% | 0 |
| Airport | 8,173 | 92.84% | 1 |
| Canoas Mathias Velho | 28,886 | 98.93% | 5 |

Counts overlap between zones. Complete clipped lon/lat data: `buildings/recommended_*.geojson.gz`; plain review sample: `buildings/core_samples.geojson`. Estimated height coverage is not surveyed accuracy. Overlap removal / bbox-centre sampling can omit or misassign structures; provenance is retained.

**Terrain/water.** Acquired HGT is big-endian int16; exported grid is little-endian int16 zlib. **697 terrain-RGB PNGs, z9–14**, use Mapbox encoding, palettes and 1 m quantization. SRTM is nominally **EGM96** with merged fill; Copernicus/FABDEM are **EGM2008**, ANADEM inheritance is unverified, municipal vertical datum unspecified. HAND depth is relative modelled inundation depth; adding it to a different urban surface is only a rough illustration, not validated water elevation. 100 m samples preserve no-data. Three 08 May checks: airport **2.56 m** depth (brief ~2.5 m; +0.06 m), Rodoviária **0.61 m**, maximum computed surface **51.46 m**, exposing urban DEM bias. Mercado has **no-data**, so its reported ~1.5 m cannot be confirmed. 

**Publication caveat:** [CEMS public reuse](https://mapping.emergency.copernicus.eu/about/citation-guidelines/) has exceptions; inherited depth XML records conditionsUnknown / Article13_1a restrictions. Confirm scope before publicly redistributing water samples.

**Recommended stacks / remaining steps.** Offline judge: local MBTiles + bundled Latin glyphs/sprites, clipped terrain grid/RGB, provenance-labelled building extrusions, EMS depth/extent. Integrate into the workstation and vendor its MapLibre/deck.gl JS/CSS for an offline application. Run `python out/MAP3D/serve_offline.py --port 8767`; load `/style.json`, `/terrain-rgb/{z}/{x}/{y}.png` (`raster-dem`, `encoding: mapbox`, tileSize 256, maxzoom 14), and `/buildings/recommended_<zone>.geojson` (server supplies gzip). Null heights stay unextruded. Next reconcile a licensed bare-earth DEM, geoid/gauge datum and EMS reference terrain before presenting absolute water heights.

Online demo/video: retain that stack with OpenFreeMap fallback; offline downloads there are limited to 3,000 tiles or 50 MB, ≤4 concurrent requests and unique User-Agent. CARTO now requires a key for free tiers. Google 3D needs key/billing and POA mesh confirmation: 1,000 free monthly root requests, then $6/1,000 initially; independent overlays and visible credits required, no offline redistribution, promotional videos ≤30 seconds with required marking. Cesium Community is free for eligible personal/evaluation use (15 GB/month); commercial individual starts $149/month. Confirm geoid/ellipsoidal alignment for either renderer.

**Deferred tool, no installation performed:** `overturemaps 1.0.2`, MIT, [wheel download](https://files.pythonhosted.org/packages/5d/55/e3545154339873cdeeae7c5dca00c22e58de1192bf2769795cb31e319ba6/overturemaps-1.0.2-py3-none-any.whl), **25,451 bytes**, excluding dependencies (total dependency size unmeasured). Approval-only install: `python -m pip install overturemaps==1.0.2`. Then run:
```text
overturemaps download --bbox=-51.32,-30.28,-51.00,-29.65 --release=2026-10-21.0 -f geojson --type=building -o out/MAP3D/overture_aoi.geojson
```
Recount optional height/floors, clip zones and recheck caps. `remaining_tools.json` pins wheel SHA-256/dependencies. Stdlib HTTP ranges alone produced this MBTiles extract; a PMTiles alternative needs its JS protocol and a Range-capable server. **Correction to brief:** fetched PMTiles JS 4.5.0 is BSD-3-Clause, not MIT. No conversion binary is required for shipped assets.

Checks passed: JSON/gzip, SQLite, PNG CRCs/heights, water arithmetic and offline HTTP. Browser rendering untested. Evidence: `sources.json`, `self_check.json`, `METHODS.md`.
