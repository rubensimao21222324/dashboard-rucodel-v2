"""Configura os acessos da instância DEV (credenciais ficam só neste PC, protegidas pelo Windows - DPAPI).

Menu:  1) acesso ao site de gestão (gestao.rucodel.pt)   2) acrescentar um setor do dashboard (api.rucodel.pt)
NOTA: ao contrário do adicionar_setor.py de produção, este script NÃO reinicia nem fecha nenhuma Central.
Escreve na pasta «execucao\\runtime» desta instância, nunca em C:\\Users\\...\\Jarvis_Central_Pro.
"""
import getpass, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUNTIME = RAIZ/'execucao'/'runtime'
sys.path.insert(0, str(RUNTIME/'backend'))
from notion_connection import protect_bytes          # noqa: E402
from gestao_rucodel import GestaoRucodel             # noqa: E402
from setores import SectorAccounts, DashboardAPI, pin_hash   # noqa: E402


def gestao() -> None:
    g = GestaoRucodel(RUNTIME, {}, protect_bytes)
    print('\nAcesso ao site de gestão (leitura). Estado atual: %s' % ('configurado' if g.configured() else 'por configurar'))
    user = input('Utilizador (Enter = cancelar): ').strip()
    if not user:
        return
    password = getpass.getpass('Palavra-passe (não aparece ao escrever): ')
    if not password:
        print('Nada foi alterado.'); return
    g.save_credentials(user, password)
    try:
        g.login()
        print('Feito: o site aceitou o acesso.')
    except Exception as e:                            # noqa: BLE001
        print('Guardado, mas o teste de login falhou: %s' % e)


def setor() -> None:
    print('\n!! ATENÇÃO !! Com a conta de um setor, os botões + / - / Iniciar / Terminar dos ecrãs dos setores ESCREVEM no dashboard REAL da Rucodel.')
    print('   Numa instância de testes, só configures um setor se aceitares que mexer aí altera dados verdadeiros.')
    if input('   Escreve SIM para continuar: ').strip() != 'SIM':
        print('Cancelado.'); return
    accounts = SectorAccounts(RUNTIME, protect_bytes)
    data = accounts.load()
    have = data.get('setores', {})
    if not have:
        print('\nAinda não há nenhum setor. Para ler a lista de departamentos é preciso uma conta; vou pedir já a primeira.')
        login = input('Utilizador do dashboard (Enter = cancelar): ').strip()
        if not login:
            return
        password = getpass.getpass('Palavra-passe: ')
        sid = input('Número (id) do departamento dessa conta: ').strip()
        nome = input('Nome do setor (ex.: Torno): ').strip() or sid
        if not sid.isdigit() or not password:
            print('Dados inválidos. Nada foi alterado.'); return
        data['setores'] = {sid: {'nome': nome, 'login': login, 'password': password}}
        test = DashboardAPI(type('Mem', (), {'load': staticmethod(lambda: data)})())
        try:
            test.token(sid)
        except Exception as e:                        # noqa: BLE001
            print('O dashboard não aceitou esta conta: %s\nNada foi alterado.' % e); return
        pin = getpass.getpass('PIN para abrir este setor nos ecrãs (Enter = sem PIN): ').strip()
        if pin:
            data['setores'][sid]['pin'] = pin_hash(pin)
        accounts.save(data); print('Feito.'); return
    api = DashboardAPI(accounts)
    departments = api.departments()
    free = [d for d in departments if str(d['id']) not in have]
    print('\nJá configurados: ' + ', '.join(v.get('nome', k) for k, v in have.items()))
    if not free:
        print('Todos os departamentos já estão configurados.'); return
    for i, d in enumerate(free, 1):
        print('  %d) %s' % (i, d['nome']))
    c = input('Número a acrescentar (Enter = nenhum): ').strip()
    if not c.isdigit() or not 1 <= int(c) <= len(free):
        return
    d = free[int(c)-1]; sid = str(d['id'])
    login = input('Utilizador do dashboard para «%s»: ' % d['nome']).strip()
    password = getpass.getpass('Palavra-passe: ')
    if not login or not password:
        print('Nada foi alterado.'); return
    data['setores'][sid] = {'nome': d['nome'], 'login': login, 'password': password}
    test = DashboardAPI(type('Mem', (), {'load': staticmethod(lambda: data)})())
    try:
        test.token(sid)
    except Exception as e:                            # noqa: BLE001
        print('O dashboard não aceitou esta conta: %s\nNada foi alterado.' % e); return
    pin = getpass.getpass('PIN para abrir este setor nos ecrãs (Enter = sem PIN): ').strip()
    if pin:
        data['setores'][sid]['pin'] = pin_hash(pin)
    accounts.save(data); print('Feito: «%s» acrescentado.' % d['nome'])


def main() -> None:
    if not (RUNTIME/'backend'/'setores.py').is_file():
        raise SystemExit('Corre primeiro ARRANCAR_DASHBOARD_2.0.bat.')
    while True:
        print('\n=== Configurar acessos (instância DEV) ===\n 1) Site de gestão (gestao.rucodel.pt)\n 2) Acrescentar um setor (dashboard)\n 0) Sair')
        c = input('Escolha: ').strip()
        if c == '1': gestao()
        elif c == '2': setor()
        elif c == '0': return


if __name__ == '__main__':
    main()
