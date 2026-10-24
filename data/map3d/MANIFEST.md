# Mapa offline · proveniência e limites

Pacote copiado da aquisição MAP3D de 24/10/2026. Uso local, sem rede. Arquivos originais de evidência: `sources.json`, `METHODS.md`, `MAP3D_REPORT.md`. O catálogo abaixo não atribui disponibilidade em tempo real.

| Arquivo / camada | Fonte | Licença / atribuição | Data e limite |
|---|---|---|---|
| basemap.mbtiles | Protomaps, dados OpenStreetMap | ODbL 1.0; © OpenStreetMap contributors; Protomaps | Extrato atual, z0–15, 2.716 tiles; não reconstrução de maio/2024 |
| offline_style.json | Protomaps basemap style | BSD, conforme relatório de aquisição | Estilo offline; glyphs e sprites locais |
| fonts/ | Noto Sans, glyphs preparados na aquisição | SIL Open Font License; texto em fonts/OFL.txt | Faixas latinas 0–511 |
| sprites/ | Protomaps basemap assets | Licença incluída em sprites/LICENSE.txt | Ícones locais |
| terrain-rgb/ | Skadi / SRTM terrain-tiles | Componentes regionais de domínio público; creditar SRTM / NASA / USGS e fontes descritas em sources.json | 697 PNG, z9–14, Mapbox RGB, quantização 1 m; EGM96 nominal, preenchimentos mesclados; não terreno urbano validado |
| buildings/recommended_centro_rodoviaria.geojson.gz | OSM + Microsoft footprints + Google Open Buildings 2.5D Temporal 2023 | Banco derivado ODbL 1.0; Microsoft CDLA-Permissive-2.0; Google CC BY 4.0 | bbox [-51.245,-30.045,-51.205,-30.018] |
| buildings/recommended_farrapos_4d.geojson.gz | mesmas fontes | mesmas licenças e créditos | bbox [-51.225,-30.018,-51.19,-29.993] |
| buildings/recommended_humaita_sarandi_arena.geojson.gz | mesmas fontes | mesmas licenças e créditos | bbox [-51.215,-29.993,-51.115,-29.955] |
| buildings/recommended_airport.geojson.gz | mesmas fontes | mesmas licenças e créditos | bbox [-51.19,-30.006,-51.15,-29.974] |
| buildings/recommended_canoas_mathias_velho.geojson.gz | mesmas fontes | mesmas licenças e créditos | bbox [-51.215,-29.94,-51.17,-29.895] |
| Água / profundidade (API, não duplicada neste pacote) | Copernicus EMS EMSN194, © 2024 European Union | Conforme data/ATTRIBUTION.md e manifesto de riscos; relatório registra conditionsUnknown / Article13_1a no XML herdado: escopo de redistribuição pública pendente | Observações 06 e 08/05/2024; grades criadas em 12/06/2024, HAND ±1 m, retrospectivas; nunca autorização de rota |

Prédios conservam `height_m` e `height_source`. Altura nula permanece plana (0 de extrusão visual, não altura medida de 0 m). Alturas Google são estimativas ML por amostra no centro do bbox; níveis OSM × 3 m são inferidos. Footprints atuais não são uma reconstrução de maio/2024. Zonas sobrepostas não devem ser somadas como prédios únicos.

Terreno com exagero visual 1,3×; água é profundidade relativa em metros, sem cota absoluta validada ou reconciliação entre datums. Retângulos WGS84 da tela aproximam células UTM de 100 m. Hachura cinza significa sem dado, nunca seco.

MapLibre GL JS não está incluído: nenhum build encontrado localmente. Para completar 3D offline, Orbit deve obter **maplibre-gl 4.7.1**, BSD-3-Clause, os arquivos exatos `https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js` e `https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css`, e a licença `https://unpkg.com/maplibre-gl@4.7.1/LICENSE.txt`, colocando-os em `app/web/v2/vendor/`. A UI já tenta estes caminhos e oferece mapa canvas 2D quando ausentes. Nenhuma dependência é baixada em tempo de execução.
