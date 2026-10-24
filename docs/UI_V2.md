# Console de despacho /v2 — V2-D

Interface offline em português do Brasil. Os dados e o replay são sintéticos. Esta revisão altera somente `app/web/**`, este documento e `tests/test_ui_v2.py`; não altera decisões, roteamento nem o World Model.

## Organização e princípios CAD

Aplicamos os princípios de consoles CAD/911 descritos no brief (Hexagon, Motorola, Tyler, Mark43, RapidSOS, Esri e fatores humanos NENA/APCO), sem copiar aparência de fornecedor nem consultar a internet.

O mapa é a área principal. Em 1920 × 1080, a fila tem 360 px e o incidente 440 px: mapa de 1120 px (58,3%). Com o incidente recolhido para o trilho de 48 px, são 1512 px (78,8%). Em 3440 × 1440, fila de 420 px, incidente de 560 px e mapa de 2460 px (71,5%); a coluna opcional Agentes de 380 px deixa 2080 px (60,5%). Ambos os painéis recolhem. Abaixo de 1600 px, o incidente sobrepõe o mapa e conserva sua largura; o operador pode recolhê-lo para consultar o território. Há adaptação para telas estreitas, sem truncar locais.

A barra superior tem 40 px: produto, data do replay, contagens P1–P4, maior espera, estado do sistema, indicação de dados sintéticos e novo pedido. Vistas de apoio ficam na barra do mapa. Não há cartões de KPI. O incidente usa cinco abas: Resumo (situação, risco à vida, próxima ação e confirmações), Meios (tabela, escolha, cautelas e Crítico de risco), Mensagens (original, respostas, citações, roteiro e formulário), Agentes (papel, modelo, comprovante, segundos e objeções) e Histórico (versões e alterações). Identificadores, fontes e pareceres completos ficam em detalhes fechados. A coluna de agentes pode ser fixada em telas grandes.

A fila ordena por P1–P4 e depois pelo recebimento mais antigo. Qualquer flag de bebê, mobilidade reduzida, telhado, água ≥ 1,2 m ou água subindo determina P1 na interface. Sem flags, o escore existente é agrupado em P1 ≥ 30; P2 ≥ 15; P3 ≥ 5; P4 < 5 ou desconhecido. Isso organiza a apresentação e não modifica a decisão do backend. Água estimada vem do contexto de profundidade; os demais sinais usam o relato ou o campo de mobilidade. As flags são o destaque vermelho; a prioridade não recebe uma segunda escala de cores. Esperas têm atualização de 1 s, âmbar após 1 h e vermelho após 2 h, usando o horário de replay do caso mais o tempo transcorrido na sessão. Horários são apresentados em BRT, 24 h; números e temporizadores usam Plex Mono.

Cores: fundo #0f1419, painel #161c23, borda #26303b, texto #e6edf3 e secundário #9aa7b4. Vermelho #e5484d para risco/bloqueio, âmbar #f5a524 para ação/cautela, azul para profundidade e verde #30a46c para confirmação. Estados incluem texto e forma. Bordas de 1 px, raio de 4 px, espaçamento por 8 px e foco visível. IBM Plex Sans 400/500/600, Condensed 500/600 e Mono 400/500 são locais; OFL preservada e atribuída em Dados.

## Teclado e decisões humanas

| Tecla | Ação |
|---|---|
| J / K | Próximo / anterior na fila filtrada |
| Enter | Abrir incidente selecionado |
| A | Abrir Meios e focar a escolha |
| R | Abrir Mensagens e focar a resposta |
| C | Abrir cartão de despacho |
| / | Buscar |
| Esc | Recolher incidente / fechar menu; diálogos usam fechamento nativo |
| ← / → nas abas | Trocar aba; Home / End vão às extremidades |

Atalhos de letras não interceptam campos editáveis. A não aprova diretamente: abre o seletor. Aprovação exige meio válido, localização confirmada, ausência de pendências e reconhecimento das cautelas por caso, meio e versão. Meio inadequado permanece bloqueado. O servidor revalida ações com a versão esperada. Resposta do contato é reanalisada pelo backend.

Estatísticas consolidadas (`/api/stats?date=`) entram em Situação; sugestões de duplicatas entram em detalhes no Resumo, sem mesclar automaticamente. Execução usa `/run` assíncrono quando disponível e acompanha `/api/runs/<id>/events` via SSE, consultando o resultado a cada 1,5 s. Resposta síncrona de servidores anteriores continua aceita. Recursos opcionais não aparecem quando ausentes. A indisponibilidade do stream não repete o pedido.

## Mapa e desempenho

Padrão: água drapeada em 2D por faixas, profundidade relativa e hachura para ausência de dado. Quando há células visíveis, a inundação tem apenas contorno; não há duas superfícies preenchidas sobrepostas. As células usam uma grade WGS84 aproximada, sem duplicar polígonos conhecidos/desconhecidos; não representam cotas absolutas ou uma rota segura. 3D é opcional, minzoom 14, base 0, opacidade 0,55 e fonte separada limitada a 4000 células no enquadramento. Modo leve desliga extrusão da água, prédios e terreno.

Profundidade: debounce de 300 ms, AbortController e token contra respostas antigas; cache LRU limitado a 96 tiles z13 por data. As consultas usam o viewport, recortado ao domínio offline. Acima de 64 tiles, a interface pede aproximação em vez de consultar uma área excessiva. Cache impede novas consultas ao revisitar a área. Prédios: apenas zonas que interceptam a vista, filtrados ao enquadramento, minzoom 14; fontes são esvaziadas em modo leve ou abaixo do zoom. Os cinco arquivos originais têm 8173, 28886, 14761, 10656 e 35176 feições. Não se alteraram os dados.

Terreno fica desligado com DPR ≥ 1,5 ou largura ≤ 1920; nas demais telas, ligado. O menu permite mudar isso; exagero 1. O mapa começa sem inclinação. Casos usam uma fonte e camadas symbol/circle, sem marcadores DOM; seleção recebe halo e anel de 1 km, voo de 600 ms (sem animação com movimento reduzido). Fundo vetorial é local; Satélite fica desabilitado com a explicação de dependência de internet. Há fallback 2D quando WebGL/MapLibre falha.

### Diagnóstico antes / depois (24/10/2026)

BBox de comparação: -51.235,-30.03,-51.185,-29.99. Contagem de fontes originais:

| Data | Inundação | Bloqueios | Bombas | Infraestrutura | Abrigos | Diques | Células de profundidade |
|---|---:|---:|---:|---:|---:|---:|---:|
| 06/05/2024 | 3196 | 6 | 38 | 13 | 0 | 52 | 1095 |
| 08/05/2024 | 4580 | 8 | 38 | 13 | 205 | 52 | 1106 |

Contagens das fontes territoriais são preservadas. Na área comparada, a construção da grade de profundidade tem 2124 feições nas duas versões (conhecidas + sem dado); extrusões padrão passam de 1095/1106 para zero. A redução de custo vem de drapeamento, terreno desligado em laptops, cache/debounce e controle de visibilidade, não de suprimir dados de risco.

Harness Node 24.19.0 com dados reais, fetch e MapLibre simulados; 100 eventos moveend em sequência. Antes, handler original; depois, onMoveEnd. Cada cache começou vazio. O backend e a GPU não fazem parte dos tempos. São amostras únicas sujeitas à carga do host (inclusive p95 ligeiramente maior em 06/05), não um benchmark estatístico:

| Data | Consultas antes → depois | Handler p50 antes → depois | Handler p95 antes → depois |
|---|---:|---:|---:|
| 06/05 | 100 → 4 | 0,0263 → 0,0111 ms | 0,5680 → 0,6330 ms |
| 08/05 | 100 → 4 | 0,0248 → 0,0076 ms | 0,1793 → 0,0467 ms |

As quatro consultas posteriores correspondem aos quatro tiles z13 da área. Repetir a mesma vista usa o cache (testado). O fetch simulado usa as mesmas células para o bbox de comparação em cada tile; não mede rede ou latência da API. O diagnóstico inicial Python de leitura de mapa + profundidade levou 2742,90 ms e 987,69 ms, respectivamente; não é tempo de interação.

Não há navegador disponível nesta sessão (inventário de apps e navegadores vazio). Portanto, FPS de GPU, console real e inspeção visual em 1920/3440 não foram medidos; não se afirma atingir 45 FPS. `?fps=1` habilita contador de requestAnimationFrame e tempo máximo do handler. `DeskMap.metrics` expõe contagens de fontes, erros, requisições e os últimos 120 tempos. Em laptop real, aproximar a zoom 14 e arrastar por 10 s para conferir a meta ≥ 45 FPS com camadas padrão. RAF é uma aproximação da cadência do navegador, não uma medida exclusiva do renderizador.

## Verificação

`python -m unittest discover -s tests -p test_ui_v2.py -v`: rotas offline, MIME font/woff2 para as sete fontes, OFL, tiles/compressão, segurança de caminhos, orçamento de 180000 bytes sem vendor, node --check, decisões de aprovação, ordenação, cinco abas em DOM simulado, cache/abort/debounce, hachura sem sobreposição, água padrão 2D, limite 3D e descarte de prédios em modo leve. O teste Node usa stdin para respeitar o limite de linha de comando do Windows. Os testes de integração usam registry temporário, sem alterar registros operacionais.

Resultado final: 9 testes de UI passaram; os dois testes de JavaScript/contrato de mapa também foram reexecutados após os ajustes finais. `node --check` e `git diff --check` passaram. Interface: 76486 bytes sem vendor (limite 180000). Suíte completa: 135 testes, 134 passaram; falhou `test_slow_source_cannot_exceed_response_deadline`, fora do escopo UI, com 0,312 s para teto de 0,300 s. Reexecução isolada após a suíte também falhou (1,344 s). Não se alteraram pipeline ou seus testes para ocultar a falha.
