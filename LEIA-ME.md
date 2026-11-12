# Dashboard Rucodel 2.0

Linha de **desenvolvimento** do Jarvis/Dashboard da Rucodel, organizada por módulos e pronta para Git.
É uma **cópia**: o Jarvis de produção (`C:\Users\simao\Jarvis_Central_Pro`) não é tocado por nada desta pasta.

## Como arrancar (Windows)
1. Duplo clique em **`INSTALAR_DASHBOARD_2.0.bat`** (instala o que falta, monta e arranca; abre o painel).
2. Painel DEV: <http://127.0.0.1:22396/> (a produção continua em 12396; as duas podem correr ao mesmo tempo).
3. Opcional, para ligar ao site de gestão e aos setores: `ferramentas\CONFIGURAR_ACESSOS.bat` (lê o aviso: os setores escrevem no dashboard real).
4. Dia a dia: `ARRANCAR_DASHBOARD_2.0.bat` e `PARAR_DASHBOARD_2.0.bat`.
5. Git: `ferramentas\INICIAR_GIT.bat` (cria o repositório local e o primeiro commit; GitHub fica para depois).

## Como está organizado

| Pasta | O que tem | Fala com |
|---|---|---|
| `1_integracao_rucodel/site_gestao` | leitura do site de gestão (login, listas, fotos) | **gestao.rucodel.pt** (HTML, só leitura) |
| `1_integracao_rucodel/api_dashboard` | ver `README.md`: a classe `DashboardAPI` vive em `3_setores_tablets/setores.py` | **api.rucodel.pt** (JSON, lê e escreve) |
| `2_producao` | ensino de tempos, fotografia→serviço, página pública de consulta | cache do site, Tailscale Funnel |
| `3_setores_tablets` | ecrãs dos setores (tablets), contas por setor, PIN, avaliações | api.rucodel.pt, rede da oficina |
| `4_acoes_e_alertas` | «Ações a corrigir», alertas 15h/16h | ntfy (telemóvel) |
| `5_seguranca_e_copias` | senha do encarregado, registo de falhas, vigilante e backups | disco local / externo |
| `6_jarvis_central` | a Central (servidor, IA local, voz, memória, Agenda, Notion) | Ollama, Google Calendar, Notion |
| `7_painel_web` | páginas HTML/JS/CSS do painel | a Central |
| `8_instalacao_e_updates` | o que existia para instalar/atualizar **produção** (referência) | — |
| `futuro` | fases 2–7 do plano (n8n, Aurelio, trading simulado, CAD) | — |
| `testes` | testes automáticos existentes | — |
| `docs` | endpoints, mapa de páginas, segurança, Git | — |
| `ferramentas` | scripts de montagem e configuração | — |

**Porque há uma pasta `runtime/`?** O código importa os ficheiros uns dos outros «à solta» e procura o painel em `<raiz>/painel`.
Em vez de reescrever imports (risco), `ferramentas/montar_runtime.py` junta os módulos no formato clássico em `runtime/` (ignorada pelo Git).
**Edita sempre nas pastas numeradas, nunca em `runtime/`.**

**Tudo numa só pasta** (`Documents\dev\dashboard-rucodel-v2`):
- `execucao/` — gerado ao arrancar: ambiente Python (`.venv`), código montado (`runtime/`), dados e credenciais (`dados_locais/`, `runtime/*.dpapi`). Fora do Git.
- `backups/` — cópia dos ficheiros antes de cada alteração (uma subpasta por data e tema). Fora do Git.

## Documentação
- [docs/ENDPOINTS_RUCODEL.md](docs/ENDPOINTS_RUCODEL.md) — o que usamos nos serviços da Rucodel
- [docs/ENDPOINTS_JARVIS.md](docs/ENDPOINTS_JARVIS.md) — as rotas que o Jarvis expõe
- [docs/MAPA_PAGINAS.md](docs/MAPA_PAGINAS.md) — página/ecrã ↔ ficheiro Python ↔ endpoint
- [docs/SEGURANCA.md](docs/SEGURANCA.md) — o que lê, o que escreve, onde ficam os segredos
- [docs/GIT_E_RAMOS.md](docs/GIT_E_RAMOS.md) — fluxo de branches e como promover para produção
