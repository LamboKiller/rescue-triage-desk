# Derived data attribution

Derived CSVs and simplified GeoJSON are distributed. Source packs D1–D3 were prepared 21–23 October 2026.
The supplied backup contains no D1–D3 REPORT.md or manifest.json. Full manifest-based
attribution could not be verified; do not describe it as complete. Available source
research and inventories support the following credits:

* Street names/geometries: © OpenStreetMap contributors, Open Database License 1.0
  (https://www.openstreetmap.org/copyright). Derived database streets_flood.csv is
  distributed under ODbL 1.0, separately from the MIT application code.
  D1 snapshot 2024-06-15 is retrospective, later than the replay window.
* Census tracts/municipalities: IBGE, Censo Demográfico 2022; supplied D1 export.
  https://www.ibge.gov.br/estatisticas/sociais/populacao/22827-censo-demografico-2022.html
* Observed water: Possantti et al., UFRGS and collaborators, Banco de dados das
  cheias na Região Hidrográfica do Lago Guaíba em Maio de 2024, CC BY 4.0 per the
  supplied source brief. D1 gpkg_layer_inventory.json links the observed-water
  layers and IBGE input to Zenodo record 14617475 (v1.4, published 2025-01-08):
  https://doi.org/10.5281/zenodo.14617475 . Collection DOI:
  https://doi.org/10.5281/zenodo.11164049 . Earliest supplied version is record
  11164050 (2024-05-09); original per-layer publication remains unverified.
  The public record confirms version/date/authors; its extracted rights section
  did not expose a license identifier, so the license statement relies on the brief.
* Road closures: supplied D3 road_closures.csv, 31 rows. Each row preserves source,
  source_locator, published timestamp and quality notes. Sources include DNIT and
  public official bulletins. Research also identifies Fiocruz GIS Zenodo 11193971,
  CC BY 4.0 (https://doi.org/10.5281/zenodo.11193971); it is not claimed as D1's record.

Method: named OSM highway ways, street normalization, census polygon membership of
all road vertices and segment midpoints (bbox grid prefilter + ray casting, holes
respected); count a way once per municipality/name and once per observed-water date.
Narrow polygon crossings between sample points can be missed. Normalization merges
aliases differing only by road type, accents and de/da/do/das/dos; counts therefore
differ from the R3 intersecting-way calculation. No household location is inferred.
Unknown publication times exclude flood overlap from contemporaneous decisions.
No permanent-water mask: overlap is not flood depth, passability or a route check.
May 8 coverage differs substantially; zero overlap never establishes recession.

## Named landmarks snapshot 2026-10-24T12:48:37.916512+00:00

© OpenStreetMap contributors; ODbL 1.0 (https://www.openstreetmap.org/copyright). Current Overpass snapshot is retrospective relative to May 2024; names and geometry may have changed. Way/relation centers are representative points, not entrances. Membership uses the same census and observed-water layers and indexed point-in-polygon code as prepare_data (holes respected). Unknown publication times exclude water flags from contemporaneous priority. Features whose center is outside census coverage are excluded. Queries:

```overpass
[out:json][timeout:180];(nwr["name"]["amenity"~"^(bus_station)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(hospital)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(clinic)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(school)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(university)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(place_of_worship)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(marketplace)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(fire_station)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(police)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(townhall)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(community_centre)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(pharmacy)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["amenity"~"^(fuel)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["shop"~"^(supermarket)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["shop"~"^(mall)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["public_transport"~"^(station)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["railway"~"^(station)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["leisure"~"^(stadium)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["leisure"~"^(park)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["place"~"^(square)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["place"~"^(neighbourhood)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["place"~"^(suburb)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["tourism"~"^(attraction)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["tourism"~"^(museum)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
```

## Named landmarks snapshot 2026-10-24T13:42:00.004221+00:00

© OpenStreetMap contributors; ODbL 1.0 (https://www.openstreetmap.org/copyright). Current Overpass snapshot is retrospective relative to May 2024; names and geometry may have changed. Way/relation centers are representative points, not entrances. Membership uses the same census and observed-water layers and indexed point-in-polygon code as prepare_data (holes respected). Unknown publication times exclude water flags from contemporaneous priority. Features whose center is outside census coverage are excluded. Queries:

```overpass
[out:json][timeout:180];(nwr["name"]["aeroway"~"^(aerodrome)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
[out:json][timeout:180];(nwr["name"]["aeroway"~"^(terminal)$"](-30.35,-51.7,-29.55,-50.98););out tags center;
```

## Hazard layers V2-A

`data/hazards/manifest.json` records SHA-256, input counts, output sizes and
15 m Douglas-Peucker simplification for every read-only source used by
`tools/prepare_hazards.py`. Coordinates use WGS84 longitude/latitude.

* `D1/clean/flood_observed.geojson`: UFRGS/Possantti observed water, credited above.
* `D1/clean/copernicus_flood_delineation.geojson`: Copernicus Emergency Management
  Service EMSN194 flood delineation, European Union/Copernicus EMS;
  https://mapping.emergency.copernicus.eu/ . Product filenames are retained as
  source_layer. Exact licence/version lineage is not supplied in the backup.
* `D1/clean/pump_stations.geojson`, `pump_status_daily.csv`, `levees.geojson`
  and `shelters_timeseries.geojson`: supplied UFRGS/D1 crisis layers; original
  pump source-layer identifiers retained in the daily status table. Original
  per-layer licences and full publisher lineage were not supplied; they remain
  unverified. The water-layer CC BY claim above does not verify these layers.
  APURAR is unknown; shelter snapshots begin 8 May.
* `D3/clean/infrastructure_events.geojson`, `road_closures.csv`: public DMAE,
  Porto Alegre and DNIT bulletins; per-record source URLs, timestamps and
  quality notes retained. Bulletin reuse terms were not supplied.
* `D3/clean/transport_geometry_candidates.geojson`, `D1/clean/osm_roads.geojson`:
  Copyright OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright .
  Closure lines are unverified corridor candidates, never a routing constraint
  or proof that an entire displayed road was closed. Street representative
  vertices, derived street database and OSM line derivatives are under ODbL.
* `D1/clean/census_tracts_2022.geojson`: IBGE municipal membership as above.

Observation-date filtering prevents later observations appearing in earlier
replays. Flood/pump/shelter publication times are unavailable: this is
retrospective context, not proof of what dispatchers knew that day. Levees and
OSM street positions are static reference geometry, not dated asset condition.
