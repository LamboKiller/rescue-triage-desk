# Road graph attribution

© OpenStreetMap contributors; Open Database License (ODbL) 1.0.
https://www.openstreetmap.org/copyright ; https://opendatacommons.org/licenses/odbl/1-0/
The derived road database and cached source responses are distributed under ODbL 1.0.
Current geometry is retrospective relative to May 2024. Rebuild offline from source/*.json.gz.
HAND: Copernicus EMS (© 2024 European Union), EMSN194; observed May 6/8, created June 12 2024.
Depth product terms remain unresolved as documented in data/ATTRIBUTION.md.
Unknown is not dry. HAND is ground water, not bridge-deck clearance. Parking/access unverified.

## Canoas — 2026-10-26T06:23:25.141961+00:00
https://overpass-api.de/api/interpreter
```overpass
[out:json][timeout:180];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.rs;area(area.rs)["name"="Canoas"]["admin_level"="8"]->.city;way(area.city)["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"];out body geom;
```

## Eldorado do Sul — 2026-10-26T06:24:09.141955+00:00
https://overpass-api.de/api/interpreter
```overpass
[out:json][timeout:180];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.rs;area(area.rs)["name"="Eldorado do Sul"]["admin_level"="8"]->.city;way(area.city)["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"];out body geom;
```

## Guaíba — 2026-10-26T06:24:54.136457+00:00
https://overpass-api.de/api/interpreter
```overpass
[out:json][timeout:180];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.rs;area(area.rs)["name"="Guaíba"]["admin_level"="8"]->.city;way(area.city)["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"];out body geom;
```

## Novo Hamburgo — 2026-10-26T08:21:21.126222+00:00
https://overpass-api.de/api/interpreter (+mirrors)
```overpass
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.8000,-51.2000,-29.7450,-51.1450);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.8000,-51.1450,-29.7450,-51.0900);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.8000,-51.0900,-29.7450,-51.0350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.8000,-51.0350,-29.7450,-50.9800);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.7450,-51.2000,-29.6900,-51.1450);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.7450,-51.1450,-29.6900,-51.0900);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.7450,-51.0900,-29.6900,-51.0350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.7450,-51.0350,-29.6900,-50.9800);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6900,-51.2000,-29.6350,-51.1450);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6900,-51.1450,-29.6350,-51.0900);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6900,-51.0900,-29.6350,-51.0350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6900,-51.0350,-29.6350,-50.9800);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6350,-51.2000,-29.5800,-51.1450);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6350,-51.1450,-29.5800,-51.0900);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6350,-51.0900,-29.5800,-51.0350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-29.6350,-51.0350,-29.5800,-50.9800);out body geom;
```

## Porto Alegre — 2026-10-26T07:53:32.640862+00:00
https://overpass-api.de/api/interpreter (+mirrors)
```overpass
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.2700,-51.3100,-30.1850,-51.2350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.2700,-51.2350,-30.1850,-51.1600);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.2700,-51.1600,-30.1850,-51.0850);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.2700,-51.0850,-30.1850,-51.0100);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1850,-51.3100,-30.1000,-51.2350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1850,-51.2350,-30.1000,-51.1600);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1850,-51.1600,-30.1000,-51.0850);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1850,-51.0850,-30.1000,-51.0100);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1000,-51.3100,-30.0150,-51.2350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1000,-51.2350,-30.0150,-51.1600);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1000,-51.1600,-30.0150,-51.0850);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.1000,-51.0850,-30.0150,-51.0100);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.0150,-51.3100,-29.9300,-51.2350);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.0150,-51.2350,-29.9300,-51.1600);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.0150,-51.1600,-29.9300,-51.0850);out body geom;
[out:json][timeout:300];way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"](-30.0150,-51.0850,-29.9300,-51.0100);out body geom;
```

## São Leopoldo — 2026-10-26T06:34:36.881898+00:00
https://overpass-api.de/api/interpreter
```overpass
[out:json][timeout:180];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.rs;area(area.rs)["name"="São Leopoldo"]["admin_level"="8"]->.city;way(area.city)["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|service|unclassified|living_street|track)$"];out body geom;
```
