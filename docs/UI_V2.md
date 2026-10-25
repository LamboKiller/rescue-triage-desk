# Console de despacho /v2 — V2-E

Interface offline em português. Dados e replay sintéticos; decisões, pipeline, modelos e regras operacionais não foram alterados. Sem novas dependências ou CDNs. A interface usa apenas recursos locais e MapLibre vendorizado.

## Organização operacional

Mapa central, fila recolhível e incidente com Resumo, Meios, Mensagens, Agentes e Histórico. A coluna Agentes pode ser fixada em telas grandes. A composição e os atalhos anteriores permanecem: J/K navegam, Enter abre, A escolhe meio, R abre retorno, C abre cartão, / busca, Esc recolhe. Abas aceitam setas e Home/End. Aprovação continua dependendo das validações do servidor, localização confirmada, recurso adequado e reconhecimento de cautelas por versão.

## Água preparada e disponibilidade

`python tools/prepare_water_tiles.py` produz duas imagens RGBA PNG em `data/map3d/water/`, com manifesto de coordenadas WGS84 e metadados. A reprojeção amostra a grade nativa HAND de 20 m com interpolação bilinear ponderada pelos vizinhos válidos. O pixel nativo desconhecido permanece transparente; a borda válida tem alfa ponderado. MapLibre usa fonte `image`, `raster-resampling: linear` e opacidade 0,50, abaixo das camadas de rótulos.

As quatro cores agrupam os limites reais do catálogo de frota: 0–<0,3; 0,3–<1,2; 1,2–2,5 inclusive; >2,5 m. A legenda vem do manifesto, sem escala independente. Transparência significa desconhecido, nunca seco. Profundidade HAND ±1 m é estimativa retrospectiva e não autoriza acesso. Contornos de inundação preservam os dados territoriais existentes, sem preenchimento adicional sobre ruas.

`GET /api/water?date=YYYY-MM-DD` seleciona a observação mais recente cujo dia observado E publicado não exceda o replay. A grade existente documenta criação em 12/06/2024, apesar das observações de 06/05 e 08/05, mas não registra publicação. Criação não é publicação: `created_at` preserva 12/06 e `published_at` fica null. Portanto as imagens preparadas não são exibidas em nenhuma data até haver uma publicação documentada; a nota explica a indisponibilidade. A fixture de teste registra publicação explicitamente para verificar a seleção elegível de 08/05 somente a partir de 12/06. Não se apresenta conhecimento futuro ou publicação inventada. O manifesto mantém ambas as observações; não preenche lacunas da mais recente com dados antigos.

`/api/depth` não é consultado no movimento. Um clique no mapa consulta `/api/depth?date=&lon=&lat=&bbox=`; a extensão read-only faz lookup nativo no ponto, aplica a mesma disponibilidade por publicação e mostra banda, fonte, observação e publicação. O contrato bbox anterior continua aceito pelo servidor original para outros consumidores.

Metadados de água têm cache de até 12 datas. Uma imagem completa é carregada ao selecionar a data, sem tiles de água carregados durante o pan. Cada imagem fica muito abaixo de 3 MB. O modo 3D ativa apenas prédios de zonas visíveis a partir do zoom 14; não há extrusão de células de água. Em 2D não se carregam prédios. Terreno é opcional e exige 3D; DPR é limitado a 1. Não existe handler `move`; `moveend` agenda trabalho com debounce de 300 ms. Tiles vetoriais da base podem carregar ao explorar áreas novas.

## Fontes e fotos

Bombas, infraestrutura, abrigos, bloqueios, diques e prédios abrem popups com identificação, publicador e publicação quando registrados, fato/citação literal do registro, observação, fonte, distância em linha reta ao pedido e propriedades completas recolhidas. Ausências são explicitamente marcadas, sem inventar publicador ou citação. O link HTTP(S) original aparece por último. Popups usam texto, sem interpretar HTML de fonte. Trocar a data fecha o popup anterior.

`GET /api/photos?date=&lon=&lat=` lê opcionalmente `data/photos/photos.csv` com `id,lon,lat,taken_at,author,license,source_url,thumb`. Retorna até três registros mais próximos em 300 m, com tomada até o dia de replay inclusive. Datas inválidas são rejeitadas; registros malformados são ignorados. Arquivo ausente retorna `available:false` e não cria slot. Miniaturas devem usar `/v2/photos/<arquivo>`; apenas PNG/JPEG/WebP locais são servidos, com proteção contra travessia de diretórios. Cada miniatura traz autor, licença e data. Nenhuma miniatura remota é carregada.

## Fluxo de agentes

A aba Agentes e a coluna fixada usam as mesmas etapas: Intake → Critic → Revision → Location → ruas / referências / inundação / meios determinísticos → Hazard Critic → Duplicate reviewer → versão do World Model. Cada etapa informa estado, início e duração quando presentes, modelo vencedor registrado, comprovantes expansíveis e evidências completas. Todas as tentativas de chamada permanecem visíveis; falha seguida de sucesso é identificada como tentativa falha. Offline mostra regex_baseline sem inventar modelo ou recibo.

Campos propostos vêm de `agents.intake.fields` e `agents.revision.fields`. Objeções mostram autor e campo. Alterações comparam os objetos dos dois estágios. Conectores só aparecem quando uma objeção registrada aponta para um campo realmente alterado na revisão. As verificações e os pareceres abrem fatos/rule_ids e avaliações de meios. Falhas e `deterministic_only` são vermelhos; dados ausentes permanecem indisponíveis. Versões e mudanças do World Model têm evidência própria.

Execuções em andamento acompanham `/api/runs/<id>/events` via SSE, incluindo duplicate_reviewer. Uma linha por caso/papel é atualizada; eventos e recibos são expansíveis. Só chamadas abertas pulsam; os eventos externos de Location não pulsam sem a chamada aninhada. Regex offline não pulsa. Conclusão, erro, desconexão ou fechamento removem o pulso. A consulta periódica do resultado não repete a execução. Casos armazenados usam os campos e traces já retornados pela API. Os traces atuais não registram início absoluto por chamada: a UI exibe “não registrado”, sem reconstruir horário por subtração de durações. O stream não inclui os campos intermediários; eles aparecem quando o caso concluído é retornado.

## Verificação e limites desta sessão

A suíte completa passou com 144 testes; inclui o teste de timing anteriormente instável. Os 12 testes de UI cobrem rotas, disponibilidade observação/publicação, ponto de profundidade, bandas e limite inclusivo, pixels desconhecidos, fixture de duas fotos com futuro, raio, arquivo ausente, 30 moveend sem consultas em 2D, fluxo de revisão, SSE aberto/fechado e gates operacionais. JavaScript passou em node --check e git diff --check.

Contagem estática: 68 camadas da base + 14 do desk antes; agora 68 + 10 com os metadados atuais, ou 68 + 11 quando uma imagem de água tem publicação documentada e é elegível. Não é medição de GPU. Orçamento de UI sem vendor: <150000 bytes. Os tamanhos exatos e logs ficam em `out/V2E_REPORT.md` na pasta scratch indicada pelo brief.

A verificação de navegador obrigatória ficou bloqueada: Edge headless com os argumentos solicitados falhou duas vezes com `FATAL mojo/platform_channel.cc: Access is denied`, sem abrir CDP em 9333. Node 22.23.2 está disponível e o probe adaptado está no scratch, mas a conexão foi recusada. Uma tentativa com flags para desativar sandbox foi rejeitada pela revisão automática; não foi executada. Assim, console real, mapa GL visível, rAF/FPS e screenshots em 1920×1080 / 3440×1440 não foram verificados ou fabricados. O teste VM de ausência de consultas não substitui esse teste. Processos iniciados foram encerrados ao final.
