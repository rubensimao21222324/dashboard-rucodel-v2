"""Vigilante do Jarvis: corre escondido no PC, de minuto a minuto.

- Se a Central (porta 12396) não responder e a porta estiver livre, volta a arrancá-la sozinha.
- Verifica o Ollama (inteligência local) e o endereço privado do Tailscale (acesso do tablet/iPhone).
- Quando algo cai ou volta, avisa no telemóvel pela app ntfy (só a mudança, nunca repetido).
  As mensagens não levam dados da empresa: só «caiu» / «voltou».

Configuração em vigilante_config.json (na pasta da Central). Registo em logs/vigilante.log.
Arranca com o Windows através do atalho criado por ATIVAR_VIGILANTE.cmd.
"""
from __future__ import annotations
import json
import os
import sqlite3
import zipfile
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEST = Path(__file__).resolve().parent
PROJECT = Path.home() / 'Jarvis'
CONFIG = DEST / 'vigilante_config.json'
STATE = DEST / 'vigilante_estado.json'
LOG = DEST / 'logs' / 'vigilante.log'
MUTEX_PORT = 12395          # só um vigilante de cada vez
INTERVAL = 60               # segundos entre verificações
FAILS_BEFORE_ACTION = 2     # 2 falhas seguidas (≈2 min) antes de reiniciar/avisar
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
BACKUPS = DEST / 'copias_seguranca'
BACKUP_HOUR = 3             # cópia diária às 3h (ou logo que o PC esteja ligado depois disso)
BACKUP_KEEP = 14            # dias guardados
# Fica de fora o que é grande e se volta a obter (fotos, programa instalado, relatórios já enviados).
SKIP_DIRS = {'.venv', 'copias_seguranca', 'fotos_gestao', 'fotos_setores', 'jantes_fotos', 'relatorios', 'logs',
             'importacao', 'backups_atualizacao', 'backups_visual', '__pycache__', 'dados_openwebui'}


def log(text):
    LOG.parent.mkdir(exist_ok=True)
    try:
        if LOG.exists() and LOG.stat().st_size > 1_000_000:  # guarda só o último ~1 MB
            LOG.replace(LOG.with_suffix('.log.1'))
        with LOG.open('a', encoding='utf-8') as f: f.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
    except OSError: pass


def load_config():
    try: return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def http_ok(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r: return 200 <= r.status < 500
    except urllib.error.HTTPError as e: return e.code < 500   # respondeu (p.ex. 401 sem PIN): está vivo
    except (OSError, ValueError): return False


def port_busy(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1): return True
    except OSError: return False


def python_exe():
    return DEST / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def start_central():
    """Arranca a Central exatamente como o Iniciar_Central.cmd faz, mas sem janela."""
    (DEST / 'logs').mkdir(exist_ok=True)
    with (DEST / 'logs' / 'voz_e_ferramentas.log').open('a', encoding='utf-8') as out:
        subprocess.Popen([str(python_exe()), '-u', str(DEST / 'backend' / 'central.py'), '--project', str(PROJECT)],
                         cwd=DEST, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    for _ in range(40):
        if http_ok('http://127.0.0.1:12396/health', 2): return True
        time.sleep(1)
    return False


def central_pid():
    """PID do programa que está a ouvir na porta 12396 (Windows: netstat), ou None."""
    try:
        out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError): return None
    for line in out.splitlines():
        parts = line.split()
        # «a escutar» = endereço externo :0 (o nome do estado muda com a língua do Windows)
        if len(parts) >= 5 and parts[0].upper() == 'TCP' and parts[1].endswith(':12396') and parts[2].endswith(':0') and parts[-1].isdigit():
            return int(parts[-1])
    return None


def is_jarvis_central():
    try:
        with urllib.request.urlopen('http://127.0.0.1:12396/health', timeout=4) as r: return json.load(r).get('app') == 'jarvis-central-pro'
    except (OSError, ValueError): return False


def restart_central():
    """Pedido de reinício (ficheiro «reiniciar_central»): fecha a Central — só se for mesmo a do Jarvis — e volta a arrancá-la."""
    pid = central_pid()
    if pid and is_jarvis_central():
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, timeout=20, creationflags=NO_WINDOW)
        for _ in range(20):
            if not port_busy(12396): break
            time.sleep(0.5)
    elif pid:
        log('Porta 12396 ocupada por outro programa (PID %s): não mexo.' % pid); return False
    ok = start_central()
    log('Central reiniciada a pedido.' if ok else 'Reinício pedido: a Central não voltou a arrancar (ver logs/voz_e_ferramentas.log).')
    return ok


def remote_hosts():
    try: return json.loads((DEST / 'central_config.json').read_text(encoding='utf-8')).get('remote_hosts', [])
    except (OSError, ValueError): return []


def notify(cfg, title, text, urgent=False):
    topic = cfg.get('ntfy_topico')
    if not topic: return
    server = cfg.get('ntfy_servidor', 'https://ntfy.sh').rstrip('/')
    hour = datetime.now().hour
    night = hour >= 23 or hour < 7   # de noite chega na mesma, mas sem som (não acorda ninguém)
    try:
        req = urllib.request.Request(server + '/' + topic, data=text.encode('utf-8'), method='POST',
                                     headers={'Title': title,
                                              'Priority': 'low' if night else ('high' if urgent else 'default'), 'Tags': 'warning' if urgent else 'white_check_mark'})
        urllib.request.urlopen(req, timeout=10).close()
    except (OSError, ValueError) as e: log('aviso ntfy falhou: %s' % e)


def make_backup(cfg):
    """Um .zip por dia com os dados e o código do Jarvis; as bases SQLite são copiadas de forma segura (com a Central a correr)."""
    BACKUPS.mkdir(exist_ok=True)
    day = datetime.now().strftime('%Y-%m-%d')
    target = BACKUPS / ('jarvis_%s.zip' % day); tmp = target.with_suffix('.parcial')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(DEST):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                f = Path(root) / name
                if f.suffix in ('.parcial', '.pyc') or f.stat().st_size > 50_000_000: continue
                z.write(f, Path('Jarvis_Central_Pro') / f.relative_to(DEST))
        openwebui = DEST / 'dados_openwebui' / 'webui.db'   # conversas antigas: só a base, sem modelos/cache
        dbs = [openwebui] if openwebui.is_file() else []
        dbs += sorted((PROJECT / 'jarvis_data').glob('*.sqlite3')) if (PROJECT / 'jarvis_data').is_dir() else []
        for db in dbs:
            snap = BACKUPS / (db.name + '.tmp')
            src = out = None
            try:
                # No Windows, um ficheiro aberto não se pode apagar: fechar sempre as duas ligações antes de o apagar.
                src = sqlite3.connect('file:%s?mode=ro' % db.as_posix(), uri=True); out = sqlite3.connect(snap)
                src.backup(out)
            finally:
                for con in (src, out):
                    if con is not None: con.close()
            try: z.write(snap, Path('bases') / db.name)
            finally:
                try: snap.unlink(missing_ok=True)
                except OSError: pass
    tmp.replace(target)
    for old in sorted(BACKUPS.glob('jarvis_*.zip'))[:-BACKUP_KEEP]: old.unlink(missing_ok=True)
    for left in BACKUPS.glob('*.parcial'):  # restos de tentativas falhadas
        try: left.unlink()
        except OSError: pass
    extra = cfg.get('copia_extra')  # p.ex. uma pasta do Google Drive / OneDrive / disco externo, quando existir
    if extra and Path(extra).is_dir():
        import shutil; shutil.copy2(target, Path(extra) / target.name)
        for old in sorted(Path(extra).glob('jarvis_*.zip'))[:-BACKUP_KEEP]: old.unlink(missing_ok=True)
    return target


REQUIRED = ('Jarvis_Central_Pro/backend/central.py', 'Jarvis_Central_Pro/central_config.json', 'Jarvis_Central_Pro/vigilante.py')
TEST_STATE = DEST / 'copias_estado.json'


def save_test(data):
    try: TEST_STATE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError: pass


def verify_backup(path, cfg):
    """Abre a cópia e confirma que está inteira (CRC de todos os ficheiros) e tem o essencial. Falha = exceção."""
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad: raise RuntimeError('ficheiro estragado dentro da cópia: %s' % bad)
        names = {n.replace('\\', '/') for n in z.namelist()}
    missing = [r for r in REQUIRED if r not in names]
    if missing: raise RuntimeError('faltam ficheiros essenciais na cópia: %s' % ', '.join(missing))
    data = {'teste': 'ok', 'ultima_ok': datetime.now().strftime('%Y-%m-%d %H:%M'), 'ficheiro': path.name,
            'mb': round(path.stat().st_size / 1e6, 1), 'ficheiros': len(names)}
    data['externo'] = sync_extra(cfg, path)
    save_test(data)
    return data


def sync_extra(cfg, path=None):
    """Garante que a cópia mais recente também está no disco externo (se estiver ligado). Devolve o estado."""
    extra = cfg.get('copia_extra')
    if not extra: return {'estado': 'sem destino'}
    if not Path(extra).is_dir(): return {'estado': 'desligado', 'pasta': extra}
    path = path or max(BACKUPS.glob('jarvis_*.zip'), default=None, key=lambda p: p.name)
    if not path: return {'estado': 'sem copias'}
    dest = Path(extra) / path.name
    try:
        if not dest.exists() or dest.stat().st_size != path.stat().st_size:
            import shutil; shutil.copy2(path, dest)
            for old in sorted(Path(extra).glob('jarvis_*.zip'))[:-BACKUP_KEEP]: old.unlink(missing_ok=True)
            log('cópia posta no disco externo: %s' % dest)
        if dest.stat().st_size != path.stat().st_size: raise OSError('tamanho diferente')
        return {'estado': 'ok', 'pasta': extra, 'ficheiro': dest.name}
    except OSError as e:
        log('cópia para o disco externo FALHOU: %r' % e)
        return {'estado': 'erro', 'pasta': extra}


def backup_due(now=None):
    now = now or datetime.now()
    if now.hour < BACKUP_HOUR: return False
    return not (BACKUPS / ('jarvis_%s.zip' % now.strftime('%Y-%m-%d'))).exists()


class Check:
    """Conta falhas seguidas e só muda de estado (e avisa) depois de FAILS_BEFORE_ACTION."""
    def __init__(self, name): self.name, self.fails, self.down, self.since = name, 0, False, None

    def update(self, ok):
        """Devolve 'caiu', 'voltou' ou None."""
        if ok:
            self.fails = 0
            if self.down: self.down, self.since = False, None; return 'voltou'
            return None
        self.fails += 1
        if not self.down and self.fails >= FAILS_BEFORE_ACTION: self.down, self.since = True, time.time(); return 'caiu'
        return None


def write_state(checks):
    data = {'atualizado': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'estado': {c.name: ('em baixo' if c.down else 'ok') for c in checks.values()}}
    try: STATE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError: pass


LABELS = {'central': 'A Central do Jarvis', 'ollama': 'A inteligência local (Ollama)', 'tailscale': 'O acesso de fora (Tailscale)'}


def once(checks, cfg):
    flag = DEST / 'reiniciar_central'
    if flag.exists():
        try: flag.unlink()
        except OSError: pass
        if not restart_central():
            notify(cfg, 'Jarvis: reinicio falhou', 'Pedi para reiniciar a Central e ela nao voltou. Ver logs no PC.', urgent=True)
    # 1) Central
    central_ok = http_ok('http://127.0.0.1:12396/health', 4)
    if not central_ok and checks['central'].fails + 1 >= FAILS_BEFORE_ACTION:
        if port_busy(12396):
            log('Central não responde mas a porta 12396 está ocupada (bloqueada?) — não mexo, só aviso.')
        else:
            log('Central em baixo — a arrancar.')
            central_ok = start_central()
            log('Central arrancada.' if central_ok else 'A Central não arrancou: ver logs/voz_e_ferramentas.log')
            if central_ok and not checks['central'].down:
                notify(cfg, 'Jarvis reiniciado', 'A Central tinha parado e o vigilante voltou a arrancá-la sozinho.')
    # 2) Ollama
    ollama_ok = http_ok('http://127.0.0.1:11434/api/tags', 4)
    # 3) Tailscale: o endereço privado tem de chegar à Central (página que responde mesmo sem PIN)
    hosts = remote_hosts()
    ts_ok = True if not hosts else any(http_ok('https://%s/remote/status' % h, 8) for h in hosts)

    for name, ok in (('central', central_ok), ('ollama', ollama_ok), ('tailscale', ts_ok)):
        change = checks[name].update(ok)
        if change == 'caiu':
            log('%s: EM BAIXO' % name)
            extra = {'central': ' O vigilante tentou arrancá-la; se a porta estiver bloqueada, reinicia o PC ou a Central.',
                     'ollama': ' O Jarvis responde mais devagar ou não responde na conversa.',
                     'tailscale': ' O tablet e o iPhone não conseguem entrar de fora. Confirma o Tailscale no PC (ícone junto ao relógio).'}[name]
            notify(cfg, 'Jarvis: problema', LABELS[name] + ' deixou de responder.' + extra, urgent=True)
        elif change == 'voltou':
            log('%s: voltou' % name)
            notify(cfg, 'Jarvis: resolvido', LABELS[name] + ' voltou a funcionar.')
    # 4) cópia de segurança diária (ou já, se existir o ficheiro «copia_agora» na pasta da Central)
    now_flag = DEST / 'copia_agora'
    if now_flag.exists() or backup_due():
        try: now_flag.unlink(missing_ok=True)
        except OSError: pass
        try:
            path = make_backup(cfg)
            info = verify_backup(path, cfg)
            log('cópia de segurança feita e testada: %s (%.1f MB, %d ficheiros, externo: %s)' % (path.name, info['mb'], info['ficheiros'], info['externo'].get('estado')))
            checks['_backup_falhou'] = False
        except Exception as e:
            log('cópia de segurança FALHOU: %r' % e)
            save_test({'teste': 'erro', 'motivo': str(e)[:200], 'quando': datetime.now().strftime('%Y-%m-%d %H:%M'),
                       'ultima_ok': (json.loads(TEST_STATE.read_text(encoding='utf-8')).get('ultima_ok') if TEST_STATE.exists() else '')})
            if not checks.get('_backup_falhou'):
                notify(cfg, 'Jarvis: copia falhou', 'A copia de seguranca de hoje falhou. Ver logs/vigilante.log no PC.', urgent=True)
            checks['_backup_falhou'] = True
    # 5) disco externo ligado mais tarde: põe lá a cópia de hoje (uma verificação por cada 10 minutos)
    if time.time() - checks.get('_extra_visto', 0) > 600:
        checks['_extra_visto'] = time.time()
        try:
            ext = sync_extra(cfg)
            if TEST_STATE.exists():
                st = json.loads(TEST_STATE.read_text(encoding='utf-8')); st['externo'] = ext; save_test(st)
        except Exception as e: log('verificação do disco externo falhou: %r' % e)
    write_state({k: c for k, c in checks.items() if isinstance(c, Check)})


def main():
    try:
        mutex = socket.socket(); mutex.bind(('127.0.0.1', MUTEX_PORT))
    except OSError:
        return  # já há um vigilante a correr
    cfg = load_config()
    log('Vigilante iniciado.')
    if '--teste' in sys.argv:
        notify(cfg, 'Jarvis: teste', 'Os avisos do vigilante estão a funcionar.'); log('aviso de teste enviado')
    checks = {n: Check(n) for n in ('central', 'ollama', 'tailscale')}
    me = Path(__file__).resolve(); version = me.stat().st_mtime
    time.sleep(20)  # deixa o Windows e a Central arrancarem primeiro
    while True:
        try: once(checks, load_config())
        except Exception as e: log('erro inesperado: %r' % e)
        time.sleep(INTERVAL)
        try:
            if me.stat().st_mtime != version:  # atualizado: recomeça com o código novo, sem ninguém tocar no PC
                compile(me.read_text(encoding='utf-8'), str(me), 'exec')  # só se o ficheiro novo estiver correto
                log('vigilante atualizado — a recomeçar.'); mutex.close()
                os.execv(sys.executable, [sys.executable, str(me)])
        except (OSError, SyntaxError) as e: log('atualização do vigilante ignorada: %r' % e)


if __name__ == '__main__':
    main()
