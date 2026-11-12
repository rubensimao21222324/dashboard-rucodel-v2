# Rotas que o Jarvis expõe

Há **quatro servidores** no mesmo processo (portas de produção → portas desta instância DEV).

| Servidor | Produção | DEV | Quem acede | Ficheiro |
|---|---|---|---|---|
| Central (painel) | 127.0.0.1:12396 | 22396 | só este PC, cookie de sessão | `6_jarvis_central/central.py` |
| Acesso remoto (Tailscale) | 127.0.0.1:12397 | 22397 | telemóvel, PIN | `central.py` (`RemoteHandler`) |
| Ecrãs dos setores | 0.0.0.0:12398 | 22398 | tablets na rede da oficina, PIN por setor | `3_setores_tablets/setores.py` |
| Consulta pública | 127.0.0.1:12399 | 22399 | Tailscale Funnel (desligado), PIN | `2_producao/consulta.py` |

## 1. Central — páginas (GET)
`/` painel · `/screens` ecrãs · `/producao/ecra` produção · `/fluxo` · `/acoes` · `/seguranca` · `/avaliacoes` · `/setores` · ficheiros estáticos `/app.js /style.css /avatar.js /screens.js /screens.css /assets/* /vendor/* /licencas/*`

## 2. Central — dados e ações
| Rota | Método | O que faz | Módulo |
|---|---|---|---|
| `/health` | GET | estado da Central | 6 |
| `/producao`, `/producao/notas`, `/producao/alertas`, `/producao/ensino`, `/producao/foto` | GET | produção, notas, alertas, ensino, fotografia | 2/4 |
| `/producao/atualizar` · `/producao/notas` · `/producao/ensino` | POST | atualizar do site; notas; ensinar tempos | 1/2 |
| `/jantes/foto` · `/jantes/foto/{identificar,atualizar,confirmar}` | GET/POST | identificar serviço por foto | 2 |
| `/acoes`, `/acoes/lista` | GET/POST | «Ações a corrigir» | 4 |
| `/seguranca/estado` · `/seguranca/encarregado` · `/seguranca/copia_agora` | GET/POST | painel de segurança, mudar senha, cópia já | 5 |
| `/setores/api/{setores,servicos,avaliacoes,perguntas,onde,procura,percurso,foto,colaboradores,resumo}` | GET | visão do administrador sobre os setores | 3 |
| `/setores/api/{acao,avaliar,carga,entrar}` | POST | **acao escreve no dashboard real** | 3 |
| `/status`, `/performance`, `/intelligence`, `/intelligence/tests/{id}` | GET | estado, desempenho, IA | 6 |
| `/v1/models`, `/v1/chat/completions`, `/v1/audio/voices`, `/v1/audio/speech`, `/preview`, `/voice`, `/voice/status`, `/voice/listen` | GET/POST | compatível com OpenAI; voz | 6 |
| `/panel/chat`, `/chats`, `/chats/{id}` | GET/POST | conversas do painel | 6 |
| `/memories`, `/memories/{id}/history`, `/tasks`, `/documents`, `/backup`, `/daily` | GET/POST | memórias, tarefas, documentos, cópia da memória | 6 |
| `/connections/{google,notion}`, `/google/calendars`, `/google/events`, `/google/events/list`, `/notion/tasks`, `/oauth/google/callback` | GET/POST | Agenda e Notion | 6 |
| `/screens/layouts`, `/screens/data` | GET/POST | painéis de ecrãs | 6 |
| `/relatorios/jantes_….{pdf,xlsx}` | GET | listas geradas | 1 |
| `/remote/{status,login,sair,revogar}` | GET/POST | sessões do acesso remoto | 6 |

## 3. Ecrãs dos setores (tablets)
GET: `/` `/setor` · `/api/setores` `/api/servicos` `/api/onde` `/api/procura` `/api/percurso` `/api/perguntas` `/api/colaboradores` `/api/foto`
POST (cabeçalho `X-Jarvis-Setor: 1` + JSON): `/api/entrar` (PIN do setor) · `/api/encarregado` · `/api/sair_encarregado` · `/api/acao` (**escreve no dashboard real**) · `/api/carga` e `/api/avaliar` (só administrador)

## 4. Consulta pública
GET `/` `/consulta` (página), `/dados` (só contagens), `/robots.txt` (bloqueia indexação). POST: login por PIN.

## Modo LEITURA / ESCRITA (instância DEV)
| Rota | Método | O que faz |
|---|---|---|
| `/modo` | GET | `{modo: "leitura"\|"escrita", desde, bloqueados}` |
| `/modo` | POST `{modo}` | muda o modo (fica em `auditoria.jsonl`); arranca sempre em `leitura` |
