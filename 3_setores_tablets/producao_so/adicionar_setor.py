# Acrescenta um setor do dashboard (ex.: Soldar / Desempenar) aos ecrãs dos setores do Jarvis e, no fim, reinicia a Central
# (ativa também todas as atualizações já copiadas). Enter na escolha = não acrescentar nada, só reiniciar.
# A palavra-passe é escrita por ti aqui, nesta janela, e fica guardada só neste PC (protegida pelo Windows, setores.dpapi).
import getpass, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent/'backend'))
from notion_connection import protect_bytes
from setores import SectorAccounts, DashboardAPI, pin_hash

ROOT = Path(__file__).resolve().parent


def main():
    accounts = SectorAccounts(ROOT, protect_bytes)
    data = accounts.load()
    have = data.get('setores', {})
    api = DashboardAPI(accounts)
    print('A ler os departamentos do dashboard…')
    try:
        departments = api.departments()
    except Exception as error:
        print('Não consegui ler a lista de departamentos: %s' % error); return
    print('\nJá configurados: ' + (', '.join(d['nome'] for d in departments if str(d['id']) in have) or 'nenhum'))
    free = [d for d in departments if str(d['id']) not in have]
    if not free:
        print('Todos os departamentos já estão configurados.'); return
    print('\nDepartamentos que ainda não estão no Jarvis:')
    for i, d in enumerate(free, 1): print('  %d) %s' % (i, d['nome']))
    choice = input('\nNúmero do departamento a acrescentar (ex.: o de Soldar / Desempenar) · Enter = nenhum, só reiniciar: ').strip()
    if not choice: return
    if not choice.isdigit() or not 1 <= int(choice) <= len(free):
        print('Escolha inválida. Nada foi alterado.'); return
    dept = free[int(choice)-1]; sid = str(dept['id'])
    print('\nConta do dashboard para «%s» (a mesma que usas no PC desse setor).' % dept['nome'])
    login = input('Utilizador: ').strip()
    password = getpass.getpass('Palavra-passe (não aparece ao escrever): ')
    if not login or not password:
        print('Utilizador e palavra-passe são precisos. Nada foi alterado.'); return
    # Test the account before saving it.
    data['setores'][sid] = {'nome': dept['nome'], 'login': login, 'password': password}
    test = DashboardAPI(type('Mem', (), {'load': staticmethod(lambda: data)})())
    try:
        test.token(sid); test.request('/auth/departamento/%d' % int(sid), sid, timeout=90)
    except Exception as error:
        print('\nO dashboard não aceitou esta conta: %s\nNada foi alterado.' % error); return
    pin = getpass.getpass('PIN para abrir este setor nos ecrãs (Enter = sem PIN): ').strip()
    if pin: data['setores'][sid]['pin'] = pin_hash(pin)
    accounts.save(data)
    print('\nFeito: «%s» acrescentado.' % dept['nome'])


def restart_central():
    """Pára a Central que está a correr e arranca-a de novo (como o vigilante faz), para ativar tudo."""
    print('\nA reiniciar a Central do Jarvis…')
    stop = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
            "($_.CommandLine -like '*backend*central.py*' -or $_.CommandLine -like '*bootstrap.py*start*') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(['powershell', '-NoProfile', '-Command', stop], capture_output=True)
    import vigilante
    for _ in range(15):
        if not vigilante.port_busy(12396): break
        time.sleep(1)
    print('Central a funcionar outra vez. Atualiza as páginas no tablet.' if vigilante.start_central()
          else 'A Central ainda não respondeu; o vigilante volta a tentar sozinho dentro de 2 minutos.')


if __name__ == '__main__':
    try:
        try: main()
        except Exception as error: print('\nO setor não foi acrescentado: %s' % error)
        restart_central()
    finally: input('\nCarrega em Enter para fechar.')
