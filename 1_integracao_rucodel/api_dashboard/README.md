# api_dashboard — api.rucodel.pt

A classe `DashboardAPI` (cliente da API JSON do dashboard, com token por setor) está hoje **dentro de `3_setores_tablets/setores.py`** (linhas ~106-195), porque o `setores.py` a usa diretamente.
Não foi extraída nesta fase para **não alterar código que funciona**. Quando se refatorar (num ramo de Git, com testes), é este o sítio para onde vai.
Endpoints: ver `docs/ENDPOINTS_RUCODEL.md`, secção B. **Atenção:** três deles escrevem no dashboard real.
