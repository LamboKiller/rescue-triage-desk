# DEMO — 3-minute click path (scripted scenario, 8 messages)

Scenario: `data/demo/scenario.jsonl` — Canoas / Porto Alegre, replay day 2024-05-06, synthetic people and phones (`51 9XXXX-0000`).
The file holds inputs, timed operator/crew actions and *expected* outcomes; the desk produces every decision itself.
Everything marked **[SIMULADO]** (GPS fixes, citizen reply, demo shelter) is labelled as such on screen.

## Run
```
python tools/reset_demo.py --demo          # moves runtime state to runtime/demo_backup (nothing deleted)
python tools/demo_run.py --offline --keep  # fake client, desk on :8098 → open http://127.0.0.1:8098/v2
python tools/demo_run.py --live --url http://127.0.0.1:8080 --speed 4   # Orbit: desk started against Nightshift
python tools/demo_check.py --url http://127.0.0.1:8080                  # per-step PASS/FAIL against a running desk
```

## Click path (≈ 3 min)
| t | Screen → click | Say |
|---|---|---|
| 0:00 | Fila → caso 1 (Rua Garibaldi 210) | Endereço exato, 4 no telhado, água subindo: decisão ENVIAR; o humano confirma o local. |
| 0:25 | Caso → Meios → **Qual meio enviar** → barco | O desk lista meios com motivo; unsafe é bloqueado. Humano aprova. |
| 0:45 | Missões → rota (terra + trecho de água) → **[SIMULADO] GPS** | Posição simulada, rotulada. |
| 1:00 | Desembarque → abrigo com vagas | Ponto escolhido pelo operador; abrigo com vagas relatadas. |
| 1:15 | Fila → caso 2 (bairro Sarandi) | Local aproximado, rotulado; ligar de volta em paralelo. |
| 1:30 | Caso 3 → Retorno | CALLBACK; resposta [SIMULADO] com cruzamento → ENVIAR. |
| 1:45 | Caso 4 (REVISAR) | Injeção de instrução: revisão obrigatória, nenhum despacho. |
| 1:55 | Caso 5 → Duplicados | Repasse do grupo: ligado ao caso 1, sem nova missão. |
| 2:10 | Recursos → Voluntários | Oferta pendente; operador verifica → entra na frota. |
| 2:25 | Fila médica → caso 7 → Meios (bote com maca) → Desembarque | Acamada com oxigênio; só unidade com maca; ambulância no ponto. |
| 2:45 | Missões → **Desvio** (caso 8) | Novo P1 perto do bote: +N min para a missão atual; aguardando aprovação humana. |

Expected offline result: `8/8 PASS`. Step 8 uses Rua José Pires because the offline sample geocodes only to the street centroid:
two houses on the *same* street give +0 min (nothing to compare), a neighbouring street gives a real detour cost.
