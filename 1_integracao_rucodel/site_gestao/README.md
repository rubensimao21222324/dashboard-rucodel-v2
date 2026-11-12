# site_gestao — gestao.rucodel.pt (só leitura)
`gestao_rucodel.py` lê o site de gestão (login + listas HTML + fotografias) e gera as listas PDF/Excel. `gestao_cache.py` guarda a leitura e atualiza de 10 em 10 minutos.
Só faz GET a caminhos permitidos (`ALLOWED_GET`). Endpoints: `docs/ENDPOINTS_RUCODEL.md`, secção A.
