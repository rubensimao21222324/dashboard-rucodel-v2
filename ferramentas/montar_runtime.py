"""Monta a pasta `runtime/` (o formato clássico que o Jarvis espera) a partir dos módulos organizados.

O código do Jarvis importa os ficheiros uns dos outros «à solta» (from setores import ...) e procura o
painel em <raiz>/painel. Para não mexer no código, os módulos são organizados aqui por tema e este
script junta-os no formato original, dentro de `runtime/`. Pode correr-se as vezes que se quiser (o ARRANCAR corre-o sempre):
só substitui código e painel; NUNCA toca em dados, credenciais nem na configuração já existente.

Uso:  python ferramentas/montar_runtime.py
"""
from __future__ import annotations
import json, secrets, shutil, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Tudo o que é gerado (ambiente Python, código montado, dados e credenciais) fica DENTRO da pasta do projeto,
# na subpasta  execucao/  (ignorada pelo Git: ver .gitignore).
EXEC = RAIZ/'execucao'
RUNTIME = EXEC/'runtime'
DADOS = EXEC/'dados_locais'           # dados e credenciais desta instância DEV
PROJETO = DADOS/'projeto'             # «projeto Jarvis» (memória SQLite) da instância DEV

# pasta do módulo -> (destino dentro de runtime, padrão)
MAPA = [
    ('1_integracao_rucodel/site_gestao', 'backend', '*.py'),
    ('2_producao',                       'backend', '*.py'),
    ('3_setores_tablets',                'backend', '*.py'),
    ('4_acoes_e_alertas',                'backend', '*.py'),
    ('5_seguranca_e_copias',             'backend', 'seguranca.py'),
    ('5_seguranca_e_copias',             '.',       'vigilante.py'),
    ('6_jarvis_central',                 'backend', '*.py'),
    ('3_setores_tablets/dados_iniciais', '.',       'avaliacao_perguntas.json'),
    ('testes',                           'testes',  '*.py'),
]
PAINEL = '7_painel_web'

# Portas da instância DEV: diferentes das de produção (12396-12399) para poderem correr ao mesmo tempo.
PORTAS = {'central': 22396, 'remoto': 22397, 'setores': 22398, 'consulta': 22399}


def copiar(origem: Path, destino: Path) -> int:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)
    return 1


def montar() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    n = 0
    for pasta, destino, padrao in MAPA:
        for f in sorted((RAIZ/pasta).glob(padrao)):
            if f.is_file():
                n += copiar(f, RUNTIME/destino/f.name)
    painel = RUNTIME/'painel'
    if painel.exists():
        shutil.rmtree(painel)
    shutil.copytree(RAIZ/PAINEL, painel)
    n += sum(1 for p in painel.rglob('*') if p.is_file())
    print('Runtime montado: %d ficheiros em %s' % (n, RUNTIME))
    erros = 0
    for f in sorted((RUNTIME/'backend').glob('*.py')) + [RUNTIME/'vigilante.py']:
        try:                                  # só verifica a sintaxe; não escreve ficheiros .pyc
            compile(f.read_bytes(), str(f), 'exec')
        except SyntaxError as e:
            erros += 1; print('ERRO de sintaxe em %s (linha %s): %s' % (f.name, e.lineno, e.msg))
    if erros:
        raise SystemExit('Corrige os erros de sintaxe acima antes de arrancar.')


def preparar_dados() -> None:
    """Cria (só se não existirem) as pastas de dados e a configuração DEV. Nunca sobrescreve."""
    (PROJETO/'jarvis_data').mkdir(parents=True, exist_ok=True)
    cfg = RUNTIME/'central_config.json'
    if cfg.exists():
        print('Configuração já existe (mantida): %s' % cfg.name)
        return
    base = json.loads((RAIZ/'config_exemplo'/'central_config.exemplo.json').read_text(encoding='utf-8'))
    base['token'] = secrets.token_urlsafe(36)
    base['setores_porta'] = PORTAS['setores']
    base['consulta_porta'] = PORTAS['consulta']
    cfg.write_text(json.dumps(base, indent=1, ensure_ascii=False), encoding='utf-8')
    print('Configuração DEV criada (token novo, portas %d-%d).' % (PORTAS['central'], PORTAS['consulta']))


if __name__ == '__main__':
    montar()
    preparar_dados()
