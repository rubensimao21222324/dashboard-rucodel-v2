# Endpoints dos serviços da Rucodel usados pelo código

Levantado por leitura do código (`gestao_rucodel.py`, `gestao_cache.py`, `setores.py`). Onde o código não mostra a resposta completa está marcado **a confirmar**.

## A) gestao.rucodel.pt — o site de gestão (HTML) — SÓ LEITURA
Ficheiros: `1_integracao_rucodel/site_gestao/gestao_rucodel.py` (cliente) e `gestao_cache.py` (cache + atualização periódica).
Cliente `urllib` com cookies, User-Agent `Jarvis-Rucodel/1.0 (leitura)`. Só faz **GET** (e um POST de login). Uma lista de caminhos permitidos (`ALLOWED_GET`) bloqueia tudo o resto: nada edita, imprime ou fatura.

| Pedido | Para quê | Onde no código |
|---|---|---|
| `GET /pt/` + `POST` ao formulário de login | entrar com o utilizador do Jarvis (credenciais em `gestao_rucodel.dpapi`) | `GestaoRucodel.login()` |
| `GET /p.acesso/Servicos.L1/servico.g/qt/prazo/pag/{n}` | serviços **fora de prazo**, página a página | `OVERDUE_PATH`, `parse_overdue()` |
| `GET /p.acesso/Servicos.L1/servico.g/qt/{aguardar\|curso\|terminado\|prazo}` | listas por **estado** | `STATES`, `state_link()` |
| `GET /p.acesso/Servicos.L1/servico.g/zona/{id}` (+ `/qt/{estado}`, `/pag/{n}`) | listas por **zona** | `zone_options()`, `LIST_PATH` |
| `GET /p.acesso/Servicos.L1/servico-tarefas-modal.g/id/{32 hex}` (cabeçalho `X-Requested-With`) | tarefas de um serviço → em que **setor** está (1 ou 2) | `parse_tasks()`, `sector()` |
| `GET /img/cache/{nome}.{jpg\|png\|gif\|webp}` | fotografias dos serviços | `thumbnail()`, `_photo()` |

Dados lidos de cada serviço (campos HTML): cliente, tipo, cor, tamanho, quantidade, prazo, **Detalhes** (o «ⓘ»), imagem, link de tarefas. Ligações `…/servico.g/edit/{id}` e `…/tarefas/{id}` aparecem só para extrair o id; **não são chamadas**.

## B) api.rucodel.pt — a API JSON do dashboard — LÊ **E ESCREVE**
Ficheiro: classe `DashboardAPI` em `3_setores_tablets/setores.py` (linhas ~106-195). Autenticação por **token Bearer, um por setor** (renovado se der 401). Base: `https://api.rucodel.pt`.

| Pedido | Método | Efeito | Função |
|---|---|---|---|
| `/authenticate` `{login,password}` | POST | devolve `token` | `token()` |
| `/auth/departamentos-lista` | GET | lê departamentos `{id,nome}` (cache 1 h) | `departments()` |
| `/auth/departamento/{setor}` | GET | lê os serviços e tarefas do setor (pode demorar até 90 s) | `services()` |
| `/auth/servico-imagens-batch` `{chaves:[…]}` | POST | lê fotografias (lotes de 20) — **só leitura**, apesar de ser POST | `images()` |
| `/auth/servico-counter/{chave}/{valor}?departamento={setor}` | GET | **ESCREVE**: define o contador (botões **+ / −**) | `set_counter()` |
| `/auth/departamento-start/{tarefa}` | GET | **ESCREVE**: inicia a tarefa («Iniciar») | `start()` |
| `/auth/departamento-stop/{tarefa}` | GET | **ESCREVE**: termina a tarefa («Terminar») | `stop()` |

> **Proteção DEV:** em modo LEITURA, `DashboardAPI.request` só deixa sair as três leituras acima (`modo_escrita.py`); as escritas são recusadas antes de sair do PC.

> **Importante:** os três últimos alteram dados reais. São chamados por `SectorService.act()` (`setores.py` ~linha 554), a partir de `POST /setores/api/acao`. Antes de escrever, o código confere com a última leitura do setor. Respostas completas: **a confirmar** (o código só usa os campos listados em `services()`: chave, cliente, tipo, cor, tamanho, quantidade, contador, prazo, data, descricao, nota, alerta, departamentos[]).

## C) Outros serviços externos (não são da Rucodel)
| Serviço | Para quê | Ficheiro |
|---|---|---|
| Google Calendar (`oauth2.googleapis.com/token`, `www.googleapis.com/calendar/v3/…`) | Agenda | `6_jarvis_central/calendar_connection.py` |
| Notion (`api.notion.com/v1/…`) | tarefas/notas | `6_jarvis_central/notion_connection.py` |
| Ollama local (`127.0.0.1:11434`) | IA local | `6_jarvis_central/local_reasoning.py` |
| ntfy (`ntfy.sh/<tópico>`) | avisos no telemóvel | `4_acoes_e_alertas/alertas.py`, `5_seguranca_e_copias/vigilante.py` |
