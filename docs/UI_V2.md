# Mesa de despacho V2

Interface em português, sem framework, sem rede e sem instalação. Ponto de entrada: `/v2`; a página original permanece em `/`. `app/web/routes_v2.py` implementa o contrato `handle_get(handler, path, query) -> bool`, já chamado pelo hook em `run.py` fornecido pelo trabalho de backend. Este trabalho não altera o backend.

## Executar e validar

No diretório do repositório:

```powershell
python run.py serve --sample
# http://localhost:8080/v2
python -m unittest discover -s tests -p test_ui_v2.py -v
```

Sem `--sample`, a configuração existente do backend controla os agentes; esta UI nunca chama provedores diretamente. Nenhum mock ou pedido pré-carregado é fornecido. Use “+ Novo pedido” para colar uma mensagem. O POST `/run` é acompanhado por consultas a `/api/cases` a cada 1,5 s; o modal mostra as etapas assim que chamadas aparecem nas projeções persistidas. A API atual só persiste o caso concluído, portanto não se pode prometer um stream de chamadas ainda em execução. Os testes executam um pedido sintético transitório com registro e logs em diretório temporário.

As quatro métricas são grupos de pendências, pessoas aguardando (desconhecidos explícitos), maior espera até o fim do dia de replay e uma luz de sistema. Grupos vulneráveis podem sobrepor-se; a UI usa um limite inferior pelo máximo de cada categoria por caso quando todas as contagens existem. A fila agrupa por próxima ação, depois prioridade original; busca por local/texto. `J/K` navegam, `A` executa a ação principal habilitada, `R` registra pedido de retorno, `/` abre a busca. Atalhos não atuam dentro de campos nem do modal. `R` é uma ação humana auditada.

A localização tem “Confirmei”, ligado ao endpoint real. Extrações com `derived`, estado aberto/desconhecido/disputado, perguntas e objeções sem revisão registrada compõem as pendências. Citações são destaques textuais, não confirmações de campo. Não há endpoint para confirmar outros campos: o roteiro orienta retorno e reanálise. Uma aprovação fica desabilitada enquanto houver pendências derivadas. Objeções históricas com revisão ficam na timeline, sem serem declaradas conflitos atuais. As avaliações de meios e a decisão conservam a data da análise; a tela informa que mudar a data do mapa não reanalisa a fila atual.

Meio inadequado é desabilitado com razão; cautela exige reconhecimento explícito para o meio, caso e versão. Aprovação envia `asset`, `expected_version`, `actor` e `caution_acknowledged`. Erros 409 aparecem integralmente na faixa de retorno. Trocar meio exibe as regras e o parecer original de risco; não é uma nova chamada do crítico. Aprovação humana → registro de despacho → confirmação em campo usam as transições reais. Resgate relatado sem despacho não permite confirmação direta, conforme a API; não há atalho inventado.

## Mapa offline

`data/map3d/MANIFEST.md` descreve fontes, licenças e limitações. MBTiles é aberto somente para leitura e converte XYZ → TMS; gzip é negociado, incluindo `gzip;q=0`. PNG de terreno, glyphs, sprites e cinco zonas gzip têm rotas locais. Prédios carregam apenas na zona que contém o centro da câmera; terreno e prédios desligam no modo leve. A UI não acessa basemap/tiles externos.

Nenhum MapLibre foi encontrado em Projects (incluindo node_modules ignorados), pasta MAP3D, caches pip/npm e caches locais Hermes. Orbit deve fornecer **MapLibre GL JS 4.7.1**, **BSD-3-Clause**, em:

- `app/web/v2/vendor/maplibre-gl.js`: https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js
- `app/web/v2/vendor/maplibre-gl.css`: https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css
- `app/web/v2/vendor/LICENSE.txt`: https://unpkg.com/maplibre-gl@4.7.1/LICENSE.txt

O renderer está preparado para terreno RGB Mapbox (1,3×), prédios com `height_m` (nulo plano), células de profundidade relativa por banda, hachura cinza sem dado, flood, bloqueios, bombas, abrigos, infraestrutura, diques, pedidos por forma/estado, raio 1 km e fly-to. As consultas de profundidade são limitadas à região da câmera, no máximo aproximadamente 5 × 4,5 km. As células são retângulos WGS84 aproximados ao redor dos centros UTM de 100 m; áreas sem amostra próxima recebem uma grade ilustrativa hachurada, não informação de seca. Água não é uma cota absoluta ou rota segura.

Enquanto os arquivos MapLibre estiverem ausentes, ou WebGL falhar, o canvas 2D mostra as camadas reais, sem inventar ruas. Permite escolher pinos e filtrar camadas; não oferece pan/zoom, terreno ou prédios. A câmera é recentrada pela seleção do pedido. O botão 3D fica desabilitado com motivo. O ramo MapLibre ainda precisa de verificação visual/GPU após o fornecimento da biblioteca.

## Campos e capacidades ausentes

- Campos `fields.*.status` e confirmações humanas por campo: não constam no contrato atual. Apenas localização tem confirmação persistente. “Verificadas” conta estados explicitamente fornecidos e localização confirmada.
- Eventos/stages em andamento, status de execução global e saúde dos provedores: não expostos por `/api/cases`. A luz representa falhas registradas, modo offline e falhas de carregamento; não atesta conectividade ao vivo.
- Hora exata do controle de replay: a UI usa o dia completo (23:59:59 −03), coerente com o contrato do mapa.
- Horário publicado/licença no JSON de profundidade e em várias entradas do manifesto: `null` / “—”; fontes e ponteiros de licença originais são mantidos. Dados não disponíveis não são preenchidos com zeros.
- Contagem de vulneráveis distintos, disponibilidade real de equipes/meios, condições/rotas seguras, estado/consultas Zetaris por camada e métricas de qualidade de avaliação (recall/falso bloqueio): não expostos; permanecem “—” ou explicitamente indisponíveis.
- Confirmação direta de resgate relatado sem despacho prévio não existe. A UI mostra o bloqueio e mantém o roteiro de retorno.
- A fila reflete as projeções atuais de `/api/cases`; somente o mapa usa o recorte histórico de `/api/map`. Datas de análise e de mapa são mostradas separadamente. Prioridades não são recalculadas no navegador.

## Capturas e verificações para Orbit

Não foi possível capturar a tela: a ferramenta de navegador retornou inventário vazio (nenhum browser disponível). Os testes verificam HTTP, arquivos, gzip, limites de tamanho, sintaxe JS, gates de ação e um `/run` offline pelo servidor real.

1. **1920×1080, Despacho:** pedido real selecionado, fila 24% / caso 46% / mapa 30%; decisão e ação fixas, nomes longos sem elipse.
2. **3440×1440:** 18% / 37% / 45%, mapa 3D após instalar os arquivos vendorizados; fly-to, raio, terreno, prédios e proveniência ao clicar.
3. **Cautela e inadequação:** recurso inadequado desabilitado com motivo; cautela antes/depois de reconhecer; confirmação de localização; 409 visível para versão obsoleta.
4. **Retorno/conflito:** pendências, roteiro copiado, timeline expandida com comprovante/modelo/segundos e objeções de risco; histórico apenas em detalhes.
5. **Novo pedido:** modal durante execução, fila sendo consultada, etapas aparecendo quando o backend as persistir, caso concluído selecionado.
6. **Contexto 06/05 vs 08/05:** abrigos só a partir de 08/05, bombas datadas, água desconhecida hachurada, nenhum dado apresentado como seco. Testar também antes de 06/05.
7. **Agentes / Situação / Dados:** p50/p90, modelos, revisões, demanda por conjuntos de meios, todas as regras de alerta e fontes/licenças.
8. **Fallback / leve / 2D:** remover temporariamente os arquivos vendor, bloquear WebGL, alternar modo leve e 2D/3D; teclado, navegação por tab, zoom do browser e layout estreito.
