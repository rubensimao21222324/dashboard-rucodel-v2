# Segurança desta instância DEV

- **Nada vai para o Git**: `*.dpapi`, `central_config.json`, `encarregado.json`, `client_secret*.json`, bases de dados, registos, fotos e relatórios (ver `.gitignore`).
- **Credenciais** (site de gestão, contas dos setores, Google, Notion) ficam em ficheiros `*.dpapi`, cifrados pelo Windows (DPAPI) para **este** utilizador. Nunca em código, GitHub ou registos. Esta instância começa **sem** nenhuma.
- **Esta instância não herda os segredos da produção.** Para ligar ao site de gestão ou aos setores é preciso configurá-los de propósito (`ferramentas\CONFIGURAR_ACESSOS.bat`).
- **Escrita no dashboard real:** `POST /setores/api/acao` (+ − Iniciar Terminar) altera dados verdadeiros em api.rucodel.pt. Em DEV, só configurar um setor se for mesmo isso que se quer.
- **Sem exposição à internet:** Central e remoto só em 127.0.0.1; ecrãs dos setores só na rede local, com PIN. A Consulta pública só existe se o Tailscale Funnel for ligado (desligado).
- **Não executar na pasta DEV** (mexem na produção): tudo em `producao_so/` e `8_instalacao_e_updates/producao_NAO_EXECUTAR_AQUI/` (`bootstrap.py` copia para `Jarvis_Central_Pro`; `adicionar_setor.py` mata o processo da Central de produção).
- O **Vigilante** (`vigilante.py`) está preparado para a produção (porta 12396, pasta `~/Jarvis`) e **não** é arrancado pela instância DEV.

**Onde ficam os dados:** dentro do projeto, em `Documentos\dev\dashboard-rucodel-v2\execucao\` (`.venv`, `runtime`, `dados_locais` com as credenciais) e as cópias antes de cada alteração em `backups\`. As duas pastas estão no `.gitignore`: nunca entram no Git.

## Modo LEITURA / ESCRITA (nov 2026)
- A instância DEV pode usar os **mesmos dados reais** que a produção (`ferramentas\LIGAR_DADOS_REAIS.bat` copia `gestao_rucodel.dpapi` e `setores.dpapi` de `Jarvis_Central_Pro`, sem a alterar).
- Botão **Leitura / Escrita** no topo do painel. Quem decide é a Central (`3_setores_tablets/modo_escrita.py`), não o navegador.
- **LEITURA** (sempre ao arrancar): para o api.rucodel.pt só saem leituras (lista de departamentos, serviços de um setor, fotografias). `+ / −`, `Iniciar`, `Terminar` e qualquer caminho desconhecido são recusados **antes de sair do PC** — também nos tablets ligados à porta DEV 22398.
- **ESCRITA**: só depois de confirmar no painel; fica uma faixa vermelha no topo e a mudança fica em `auditoria.jsonl` (`modo_escrita` / `modo_leitura`). Volta a LEITURA quando a Central é reiniciada.
- O site de gestão continua só de leitura por construção (`ALLOWED_GET`).
- Testes: `python testes\test_modo_escrita.py`.
