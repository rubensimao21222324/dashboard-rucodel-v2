# Mapa: página / ecrã ↔ ficheiro ↔ endpoint

Legenda: **Antigo** = página do serviço Rucodel já existente; **Jarvis** = ecrã do painel novo.

## Do serviço antigo para o código
| Antigo (pedido) | Ficheiro Python | O que dá ao Jarvis |
|---|---|---|
| gestao · lista Serviços, filtro **prazo** `/p.acesso/Servicos.L1/servico.g/qt/prazo/pag/N` | `1_integracao_rucodel/site_gestao/gestao_rucodel.py` (`parse_overdue`) | serviços fora de prazo |
| gestao · Serviços por **zona** `…/servico.g/zona/{id}` | idem (`zone_options`, `zone_*`) | lista por zona |
| gestao · Serviços por **estado** `…/qt/{aguardar,curso,terminado}` | idem (`STATES`) | A aguardar / Em curso / Terminados |
| gestao · **tarefas** do serviço (modal) | idem (`parse_tasks`, `sector`) | setor 1 ou 2 de cada jante |
| gestao · fotografias `/img/cache/…` | idem (`thumbnail`) + `2_producao/jante_foto.py` | miniaturas e identificação por foto |
| dashboard (api) · departamento `/auth/departamento/{n}` | `3_setores_tablets/setores.py` (`DashboardAPI.services`) | ecrã de cada setor |
| dashboard (api) · contador / iniciar / terminar | `setores.py` (`set_counter`, `start`, `stop`) | botões + − Iniciar Terminar |
| (cache periódica do site) | `1_integracao_rucodel/site_gestao/gestao_cache.py` | atualiza de 10 em 10 min |

## Do Jarvis para o código
| Ecrã Jarvis (URL) | HTML | Backend | Módulo |
|---|---|---|---|
| Painel inicial `/` | `7_painel_web/index.html`, `app.js` | `6_jarvis_central/central.py` | 6/7 |
| Produção `/producao/ecra` | `producao.html` | `gestao_rucodel.py` + `alertas.py` | 1/4/7 |
| Fluxo de produção `/fluxo` (modo teste) | `fluxo.html` | `central.py` | 7 |
| Setores `/setores` (admin) e tablets `:12398` | `setor.html` | `setores.py` | 3/7 |
| Avaliações `/avaliacoes` | `avaliacoes.html` | `setores.py` (`assess`, `board`) | 3/7 |
| Ações a corrigir `/acoes` | `acoes.html` | `4_acoes_e_alertas/acoes.py` | 4/7 |
| Segurança `/seguranca` | `seguranca.html` | `5_seguranca_e_copias/seguranca.py` | 5/7 |
| Consulta pública `:12399` | `consulta.html` | `2_producao/consulta.py` | 2/7 |
| Ecrãs/painéis `/screens` | `screens.html/js/css` | `display_panels.py` | 6/7 |
| Avatar e voz | `avatar.js`, `assets/`, `vendor/three` | `voice_local.py`, `central.py` | 6/7 |

## Ficheiros por módulo (resumo)
- **1** `gestao_rucodel.py`, `gestao_cache.py`
- **2** `ensino.py`, `jante_foto.py`, `consulta.py`
- **3** `setores.py` (+ `dados_iniciais/avaliacao_perguntas.json`; `producao_so/` = só para produção)
- **4** `acoes.py`, `alertas.py`
- **5** `seguranca.py`, `vigilante.py` (+ `producao_so/` scripts do Vigilante)
- **6** `central.py`, `action_requests.py`, `calendar_connection.py`, `display_panels.py`, `jarvis_memoria.py`, `jarvis_tools.py`, `local_reasoning.py`, `memory_catalog.py`, `notion_connection.py`, `panel_history.py`, `performance_log.py`, `voice_local.py`
