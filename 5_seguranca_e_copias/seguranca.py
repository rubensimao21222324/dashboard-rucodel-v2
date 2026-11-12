"""Segurança do Jarvis: registo de tentativas falhadas, senha do encarregado e estado para a página «Segurança».

- seguranca.jsonl: tentativas falhadas e ações sensíveis (nunca PINs, senhas ou tokens).
- encarregado.json: só a «impressão digital» (PBKDF2) da senha do encarregado, nunca a senha.
- estado(): o que a página mostra — cópias de segurança, serviços, tentativas falhadas e avisos.
Só leitura de ficheiros locais; não abre ligações para fora.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading

ITERATIONS = 600_000
_lock = threading.Lock()
FAIL_EVENTS = {'pin_setor_errado': 'PIN de setor errado', 'encarregado_errado': 'Senha do encarregado errada',
               'bloqueado': 'Bloqueado por demasiadas tentativas', 'login_remoto_falhado': 'PIN remoto errado (telemóvel)',
               'login_remoto_bloqueado': 'Acesso remoto bloqueado'}


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def registar(root, evento, **detalhes):
    """Acrescenta uma linha a seguranca.jsonl. Nunca falha (a segurança não pode parar a oficina)."""
    entry = {'quando': now_text(), 'evento': evento}
    entry.update({k: str(v)[:80] for k, v in detalhes.items() if v not in (None, '')})
    try:
        with _lock, open(Path(root)/'seguranca.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False)+'\n')
    except OSError:
        pass


def _hash(pin, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    return '%s$%d$%s' % (salt, iterations, hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), iterations).hex())


def _check(pin, stored):
    parts = (stored or '').split('$')
    if len(parts) != 3 or not parts[1].isdigit(): return False
    return hmac.compare_digest(_hash(pin, parts[0], int(parts[1])), stored)


class Encarregado:
    """Senha do encarregado (dá acesso a todos os setores). Guardada só como impressão digital em encarregado.json."""
    def __init__(self, root):
        self.file = Path(root)/'encarregado.json'

    def load(self):
        try: return json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def stored(self):
        return self.load().get('pin') or ''

    def configured(self):
        return bool(self.stored())

    def default(self):
        return bool(self.load().get('padrao'))

    def check(self, pin):
        return self.configured() and _check(str(pin), self.stored())

    def change(self, current, new):
        new = str(new or '').strip()
        if self.configured() and not self.check(str(current or '')): raise PermissionError('A senha atual não está certa.')
        if not re.fullmatch(r'\d{6,8}', new): raise ValueError('A senha nova tem de ter 6 a 8 algarismos.')
        if len(set(new)) == 1 or new in '0123456789' or new in '9876543210': raise ValueError('Essa senha é demasiado fácil. Escolhe outra.')
        data = {'pin': _hash(new), 'padrao': False, 'mudada': now_text()}
        tmp = self.file.with_suffix('.tmp'); tmp.write_text(json.dumps(data, indent=1), encoding='utf-8'); tmp.replace(self.file)
        return {'ok': True, 'mudada': data['mudada']}


# ── estado para a página ─────────────────────────────────────────────────────

def _read_json(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _jsonl(path, since):
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try: e = json.loads(line)
                except ValueError: continue
                if str(e.get('quando', '')) >= since: out.append(e)
    except OSError:
        pass
    return out


def _zips(folder):
    try:
        files = sorted(Path(folder).glob('jarvis_*.zip'), key=lambda p: p.name, reverse=True)
        return [{'nome': p.name, 'mb': round(p.stat().st_size/1e6, 1),
                 'quando': datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')} for p in files]
    except OSError:
        return []


def _age_hours(text):
    try: return (datetime.now()-datetime.strptime(text[:16], '%Y-%m-%d %H:%M')).total_seconds()/3600
    except (TypeError, ValueError): return None


def _where(e):
    if 'remoto' in e.get('evento', ''): return 'telemóvel / fora'
    parts = ['setor %s' % e['setor'] if e.get('setor') else ('encarregado' if e.get('onde') == 'encarregado' or e.get('evento') == 'encarregado_errado' else '')]
    if e.get('ip'): parts.append(e['ip'])
    return ' · '.join(p for p in parts if p)


def estado(root, settings=None):
    root = Path(root); settings = settings or {}
    warns = []

    def warn(level, text): warns.append({'nivel': level, 'texto': text})

    # 1) Cópias de segurança
    cfg = _read_json(root/'vigilante_config.json')
    test = _read_json(root/'copias_estado.json')
    pc = _zips(root/'copias_seguranca')
    extra_dir = cfg.get('copia_extra') or ''
    extra_on = bool(extra_dir) and Path(extra_dir).is_dir()
    extra = _zips(extra_dir) if extra_on else []
    last_ok = test.get('ultima_ok') or ''
    age = _age_hours(last_ok)
    if not pc: warn('vermelho', 'Não há nenhuma cópia de segurança no PC.')
    elif test.get('teste') == 'erro': warn('vermelho', 'A última cópia de segurança falhou o teste: ' + str(test.get('motivo') or 'ver logs/vigilante.log') + '.')
    elif age is None: warn('laranja', 'As cópias ainda não foram testadas (o teste começa na próxima cópia).')
    elif age > 36: warn('vermelho', 'A última cópia válida tem mais de 36 horas.')
    if not extra_dir: warn('laranja', 'Não há cópia fora do PC configurada.')
    elif not extra_on: warn('laranja', 'O disco das cópias (%s) não está ligado: a cópia fora do PC não está a ser feita.' % extra_dir[:3])
    elif not extra: warn('laranja', 'Ainda não há cópias no disco externo.')
    else:
        a = _age_hours(extra[0]['quando'])
        if a is not None and a > 36: warn('laranja', 'A última cópia no disco externo tem mais de 36 horas.')

    # 2) Serviços (estado escrito pelo Vigilante a cada minuto)
    vig = _read_json(root/'vigilante_estado.json')
    services = vig.get('estado') or {}
    vig_age = _age_hours(vig.get('atualizado', ''))
    if vig_age is None or vig_age > 0.25: warn('vermelho', 'O Vigilante não está a correr: ninguém está a vigiar a Central nem a fazer cópias.')
    for name, st in services.items():
        if st != 'ok': warn('vermelho', '%s está em baixo.' % name.capitalize())

    # 3) Tentativas falhadas (setores + acesso remoto), últimos 7 dias
    since = (datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    fails = [e for e in _jsonl(root/'seguranca.jsonl', since) + _jsonl(root/'auditoria.jsonl', since) if e.get('evento') in FAIL_EVENTS]
    fails.sort(key=lambda e: e.get('quando', ''), reverse=True)
    day = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    last24 = sum(1 for e in fails if e.get('quando', '') >= day)
    if any(e.get('evento') in ('bloqueado', 'login_remoto_bloqueado') and e.get('quando', '') >= day for e in fails):
        warn('vermelho', 'Houve um bloqueio por demasiadas tentativas nas últimas 24 horas.')
    elif last24 >= 10: warn('laranja', '%d tentativas falhadas nas últimas 24 horas.' % last24)

    # 4) Outros avisos
    boss = Encarregado(root)
    if not boss.configured(): warn('laranja', 'A senha do encarregado não está definida: o acesso de encarregado nos tablets está desligado.')
    elif boss.default(): warn('laranja', 'A senha do encarregado ainda é a antiga (fraca). Muda-a aqui em baixo.')
    loose = [p for d in (Path.home()/'jarvis atualizacao', Path.home()/'Downloads', Path.home()/'Desktop')
             for p in (d.glob('client_secret*.json') if d.is_dir() else [])]
    if loose: warn('laranja', 'Há %d ficheiro(s) de chave do Google soltos (%s). Devem ser apagados ou guardados num sítio protegido.' % (len(loose), loose[0].parent.name))
    if (root/'consulta.json').is_file() and _read_json(root/'consulta.json').get('pin'):
        warn('info', 'A página pública de consulta (Tailscale Funnel) está ativa, protegida por PIN.')

    labels = {'central': 'Central do Jarvis', 'ollama': 'Inteligência local (Ollama)', 'tailscale': 'Acesso pelo telemóvel (Tailscale)'}
    return {
        'gerado': now_text(),
        'copias': {'ultima_valida': last_ok, 'teste': test.get('teste'), 'motivo': test.get('motivo'), 'ficheiros': test.get('ficheiros'),
                   'pc': pc[:5], 'pc_total': len(pc), 'externo': {'pasta': extra_dir, 'ligado': extra_on, 'lista': extra[:5], 'total': len(extra)}},
        'servicos': [{'nome': labels.get(k, k), 'ok': v == 'ok'} for k, v in services.items()] + [{'nome': 'Vigilante (cópias e alertas)', 'ok': vig_age is not None and vig_age <= 0.25}],
        'acesso': {'internet_direta': False, 'remoto': 'Tailscale com PIN' if settings.get('remote_pin') else 'desligado',
                   'tablets': 'só rede da oficina, PIN por setor'},
        'tentativas': {'24h': last24, '7dias': len(fails),
                       'lista': [{'quando': e.get('quando', '')[:16], 'o_que': FAIL_EVENTS.get(e.get('evento'), e.get('evento')),
                                  'onde': _where(e)} for e in fails[:25]]},
        'encarregado': {'definida': boss.configured(), 'antiga': boss.default(), 'mudada': boss.load().get('mudada')},
        'avisos': sorted(warns, key=lambda w: {'vermelho': 0, 'laranja': 1, 'info': 2}[w['nivel']]),
    }
