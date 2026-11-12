"""Sector screen for the workshop: search by client number, big photos, + / − and the sector button.

Talks to the same API the Rucodel dashboard uses (https://api.rucodel.pt), with each sector's own
account, so the program records the actions per sector exactly as today. Only these actions exist:
  - contador + / −     -> /auth/servico-counter/<chave>/<n>?departamento=<id>   (0 <= n <= quantidade)
  - iniciar / terminar -> /auth/departamento-start|stop/<tarefa>                 (only in the right state)
Nothing else of the program can be changed from here. Every action is logged on this PC.

The screen is served on the workshop network only (private addresses), on its own port, and shows
nothing else of Jarvis. Each sector can have a short PIN, asked once per device.
"""
from __future__ import annotations
import base64
from datetime import date, datetime, timedelta
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from seguranca import registar, Encarregado
import modo_escrita  # DEV: LEITURA / ESCRITA (bloqueia escritas no programa real em LEITURA)

API = 'https://api.rucodel.pt'
PORT = 12398
CHAVE = re.compile(r'^[a-f0-9]{32}$')
DEFAULT_TEAMS = {'21': ['Torres', 'Bruno', 'João', 'Bruno Urrice', 'Nuno']}  # CNC; edit colaboradores.json to change


def job_group(tipo):
    folded = (tipo or '').lower()
    return 'Maquinada' if 'maquinad' in folded else 'Pintada' if 'pintad' in folded else 'Outro'
# Clients that write their own reference at the start of the note. ADS JANTES (5): zone in France (1, 2 or 3) + their client number.
SUBCLIENTS = {'5': re.compile(r'^\s*([123])\s+(\d{1,4})(?!\d)')}
# Quick questions of the damage assessment (edit avaliacao_perguntas.json to change). The answers are kept on this PC only,
# to teach the route planning later; nothing is sent to the program.
FIRST_QUESTIONS_ESTADO = {'id': 'estado', 'texto': 'Estado geral', 'opcoes': ['Bom', 'Riscos / toques', 'Muito danificada']}
DEFAULT_QUESTIONS = [
    {'id': 'dano', 'texto': 'Nível de dano (1 = quase nada · 5 = muito estragada)', 'obrigatoria': True, 'opcoes': ['1', '2', '3', '4', '5']},
    {'id': 'empeno', 'texto': 'Empeno', 'opcoes': ['Não', 'Pouco', 'Muito']},
    {'id': 'fissura', 'texto': 'Partida / fissura (soldar)', 'opcoes': ['Não', 'Sim']},
    {'id': 'rebarbas', 'texto': 'Rebarbas (torno)', 'opcoes': ['Não', 'Sim']},
    {'id': 'lavar', 'texto': 'Precisa lavar', 'opcoes': ['Não', 'Sim']},
    {'id': 'pintura', 'texto': 'Pintura', 'opcoes': ['Não precisa', 'Retoque', 'Pintar tudo', 'Decapar']},
    {'id': 'decisao', 'texto': 'Próximo passo', 'obrigatoria': True,
     'opcoes': ['Torno (rebarbas)', 'Lavar', 'Soldar', 'Desempenar', 'Pintar direto', 'Orçamento / não reparável']},
]


def sub_reference(client, *texts):
    pattern = SUBCLIENTS.get(client)
    for text in texts if pattern else ():
        match = pattern.match(text or '')
        if match: return {'zona': match.group(1), 'num': match.group(2)}
    return None


HERE = Path(__file__).resolve().parent


# --- accounts ---------------------------------------------------------------
class SectorAccounts:
    """{departamento_id: {nome, login, password, pin_hash}} protected by Windows (DPAPI) in setores.dpapi."""
    def __init__(self, root, protect):
        self.file, self.protect = Path(root)/'setores.dpapi', protect
        self.lock = threading.Lock()

    def load(self):
        if not self.file.is_file(): return {'setores': {}, 'segredo': None}
        return json.loads(self.protect(self.file.read_bytes(), decrypt=True))

    def save(self, data):
        with self.lock:
            temp = self.file.with_suffix('.tmp'); temp.write_bytes(self.protect(json.dumps(data).encode())); temp.replace(self.file)

    def configured(self):
        return bool(self.load().get('setores')) if self.file.is_file() else False


PIN_ITERATIONS = 600_000  # PBKDF2-SHA256 (Python standard library); older PINs (120 000) keep working


def pin_hash(pin, salt=None, iterations=PIN_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), iterations).hex()
    return salt+'$'+digest if iterations == 120_000 else '%s$%d$%s' % (salt, iterations, digest)


def pin_ok(pin, stored):
    if not stored: return True
    parts = stored.split('$')
    if len(parts) == 2: return hmac.compare_digest(pin_hash(pin, parts[0], 120_000), stored)  # first format
    if len(parts) == 3 and parts[1].isdigit(): return hmac.compare_digest(pin_hash(pin, parts[0], int(parts[1])), stored)
    return False


# --- API client ---------------------------------------------------------------
class DashboardAPI:
    """Same requests as the dashboard. One token per sector account, renewed when it expires."""
    def __init__(self, accounts, base=API, opener=None):
        self.accounts, self.base = accounts, base.rstrip('/')
        self.opener = opener or urllib.request.urlopen
        self.tokens, self.lock = {}, threading.Lock()
        self._departments = (0, None)

    def request(self, path, sector, method='GET', body=None, params=None, retry=True, timeout=20):
        modo_escrita.verificar(method, path)  # em LEITURA, nada que escreva sai deste PC
        url = self.base+path+('?'+urllib.parse.urlencode(params) if params else '')
        token = self.token(sector)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={'Authorization': 'Bearer '+token,
                                     'Accept': 'application/json', **({'Content-Type': 'application/json'} if data else {})})
        try:
            with self.opener(req, timeout=timeout) as response:
                raw = response.read(20_000_000)
        except urllib.error.HTTPError as error:
            if error.code == 401 and retry:
                with self.lock: self.tokens.pop(str(sector), None)
                return self.request(path, sector, method, body, params, retry=False, timeout=timeout)
            raise RuntimeError('O programa respondeu com erro %d.' % error.code) from error
        except TimeoutError as error:
            raise RuntimeError('O programa demorou mais de %d segundos a responder.' % timeout) from error
        except (OSError, ValueError) as error:
            if 'timed out' in str(error): raise RuntimeError('O programa demorou mais de %d segundos a responder.' % timeout) from error
            raise RuntimeError('Não consegui falar com o programa (sem internet?).') from error
        try: return json.loads(raw) if raw.strip() else {}
        except ValueError: return {}

    def token(self, sector):
        sector = str(sector)
        with self.lock:
            if sector in self.tokens: return self.tokens[sector]
        account = self.accounts.load()['setores'].get(sector)
        if not account: raise RuntimeError('Este setor ainda não está configurado no PC do Jarvis (CONFIGURAR_SETORES.cmd).')
        req = urllib.request.Request(self.base+'/authenticate', method='POST',
                                     data=json.dumps({'login': account['login'], 'password': account['password']}).encode(),
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.opener(req, timeout=20) as response: data = json.loads(response.read(1_000_000))
        except urllib.error.HTTPError as error:
            raise RuntimeError('O programa não aceitou a conta do setor %s. Corre CONFIGURAR_SETORES.cmd.' % account.get('nome', sector)) from error
        except (OSError, ValueError) as error:
            raise RuntimeError('Não consegui entrar no programa (sem internet?).') from error
        token = data.get('token')
        if not token: raise RuntimeError('O programa não devolveu sessão para o setor.')
        with self.lock: self.tokens[sector] = token
        return token

    def any_sector(self):
        sectors = self.accounts.load()['setores']
        if not sectors: raise RuntimeError('Nenhum setor configurado (CONFIGURAR_SETORES.cmd no PC do Jarvis).')
        return next(iter(sectors))

    def departments(self):
        stamp, cached = self._departments
        if cached is None or time.time()-stamp > 3600:
            rows = self.request('/auth/departamentos-lista', self.any_sector())
            cached = [{'id': int(r['id']), 'nome': str(r['nome']).strip()} for r in rows if isinstance(r, dict) and 'id' in r]
            self._departments = (time.time(), cached)
        return cached

    def services(self, sector):
        data = self.request('/auth/departamento/%d' % int(sector), sector, timeout=90)  # big sectors take a while on their server
        out = []
        for s in data.get('servicos', []):
            task = next((d for d in s.get('departamentos', []) if int(d.get('departamento_id', 0)) == int(sector)), None)
            out.append({'chave': s.get('chave'), 'cliente': str(s.get('cliente') or '').strip(), 'tipo': s.get('tipo') or '',
                        'cor': (s.get('cor') or '').strip(), 'tamanho': re.sub(r'\.0+$', '', str(s.get('tamanho') or '')),
                        'quantidade': int(s.get('quantidade') or 0), 'contador': int(s.get('contador') or 0),
                        'prazo': (s.get('prazo') or '')[:10], 'entrada': (s.get('data') or '')[:10], 'entrada_hora': str(s.get('data') or '').replace('T', ' ')[:16],
                        'descricao': (s.get('descricao') or '').strip(), 'nota': (s.get('nota') or '').strip(),
                        'alerta': s.get('alerta') or 0, 'tarefa': task and task.get('id'), 'estado': task and task.get('estado'),
                        # every department on this wheel's route, with its state there (play = por fazer, stop = em curso, ok = feito)
                        'rota': [{'id': int(d.get('departamento_id') or 0), 'estado': d.get('estado'), 'contador': d.get('contador')}
                                 for d in s.get('departamentos', []) if isinstance(d, dict) and d.get('departamento_id')]})
        return out

    def images(self, sector, chaves):
        return self.request('/auth/servico-imagens-batch', sector, method='POST', body={'chaves': list(chaves)})

    def set_counter(self, sector, chave, value):
        return self.request('/auth/servico-counter/%s/%d' % (chave, value), sector, params={'departamento': int(sector)})

    def start(self, sector, task): return self.request('/auth/departamento-start/%d' % int(task), sector)
    def stop(self, sector, task): return self.request('/auth/departamento-stop/%d' % int(task), sector)


# --- service used by the screen -----------------------------------------------
class SectorService:
    def __init__(self, root, protect, api=None, names=None, zones=None):
        self.root = Path(root)
        self.accounts = SectorAccounts(root, protect)
        self.api = api or DashboardAPI(self.accounts)
        self.names = names or (lambda: {})  # client number -> name (from the management site reading)
        self.zones = zones or (lambda: {})  # service code / client number -> zone name (same reading)
        self.photos = self.root/'fotos_setores'
        self.log = self.root/'acoes_setores.jsonl'
        self.cache, self.cache_lock = {}, threading.Lock()
        self.action_lock = threading.Lock()
        self.refreshing, self.viewed, self.watcher, self.touched = set(), {}, None, {}
        self.team_file = self.root/'colaboradores.json'
        self.errors = {}  # sector -> (time, message, failures in a row) of the last failed reading
        self.reading = threading.BoundedSemaphore(3)  # at most 3 sector lists asked to the program at the same time
        self.cache_file = self.root/'setores_cache.json'
        self.load_cache()
        self.idle_minutes = 15  # shared tablet: the collaborator leaves after 15 min without touching (0 = never)

    # --- collaborators (who did the work; the program keeps recording the sector account) ---
    def teams(self):
        if not self.team_file.is_file():
            self.team_file.write_text(json.dumps(DEFAULT_TEAMS, ensure_ascii=False, indent=1), encoding='utf-8')
        try: data = json.loads(self.team_file.read_text(encoding='utf-8'))
        except (OSError, ValueError): data = {}
        return {str(k): [str(n).strip() for n in v if str(n).strip()] for k, v in data.items() if isinstance(v, list)}

    def team(self, sector): return self.teams().get(str(int(sector)), [])

    def totals(self, sector=None, first=None, last=None):
        """{sector: {name: {total, Maquinada, Pintada, Outro}}} from the action log: each + is one jante, each − takes one back."""
        first = first or date.today(); last = last or first
        out = {}
        if not self.log.is_file(): return out
        for line in self.log.read_text(encoding='utf-8').splitlines():
            try: item = json.loads(line)
            except ValueError: continue
            who = item.get('colaborador')
            if not who or item.get('acao') not in ('mais', 'menos'): continue
            if sector is not None and str(item.get('setor')) != str(int(sector)): continue
            day = (item.get('quando') or '')[:10]
            if not (first.isoformat() <= day <= last.isoformat()): continue
            step = 1 if item['acao'] == 'mais' else -1
            mine = out.setdefault(str(item['setor']), {}).setdefault(who, {'total': 0, 'Maquinada': 0, 'Pintada': 0, 'Outro': 0})
            mine['total'] += step; mine[item.get('grupo') or 'Outro'] = mine.get(item.get('grupo') or 'Outro', 0)+step
        return out

    def secret(self):
        data = self.accounts.load()
        if not data.get('segredo'):
            data['segredo'] = secrets.token_hex(32); self.accounts.save(data)
        return bytes.fromhex(data['segredo'])

    def sectors(self):
        configured = self.accounts.load()['setores']
        names = {str(d['id']): d['nome'] for d in self.api.departments()} if configured else {}
        pretty = lambda n: n.upper() if n.islower() and n.isascii() and len(n) <= 3 else n  # «cnc» -> «CNC»
        return [{'id': int(k), 'nome': pretty(names.get(k, v.get('nome', k))), 'pin': bool(v.get('pin'))} for k, v in configured.items()]

    def check_sector(self, sector):
        sector = str(int(sector))
        if sector not in self.accounts.load()['setores']: raise ValueError('Setor não configurado.')
        return sector

    # The program takes 5-8 s to return a sector's list, so the screen never waits for it: Jarvis keeps
    # each sector that is being looked at fresh in the background and answers from memory at once.
    REFRESH = 12      # seconds between background readings of a sector on screen
    WATCH = 600       # keep refreshing a sector for 10 min after the last time a screen asked for it

    # The last list of each sector is kept on disk: after a restart the screens open at once with it
    # (showing when it was read) while the new reading arrives.
    def load_cache(self):
        try: data = json.loads(self.cache_file.read_text(encoding='utf-8'))
        except (OSError, ValueError): return
        for sector, hit in (data or {}).items():
            if isinstance(hit, dict) and isinstance(hit.get('rows'), list) and time.time()-float(hit.get('t', 0)) < 36*3600:
                self.cache[str(sector)] = {'t': float(hit['t']), 'rows': hit['rows']}

    def save_cache(self):
        with self.cache_lock: data = json.dumps(self.cache, ensure_ascii=False)
        try:
            temp = self.cache_file.with_suffix('.tmp'); temp.write_text(data, encoding='utf-8'); os.replace(temp, self.cache_file)
        except OSError: pass

    def backoff(self, sector):
        err = self.errors.get(sector)
        return err and time.time()-err[0] < min(300, 15*2**(err[2]-1))

    def read_time(self, sector):
        hit = self.cache.get(str(int(sector)))
        return datetime.fromtimestamp(hit['t']).strftime('%H:%M:%S') if hit else None

    def refresh(self, sector):
        """One reading of the sector from the program (slow), then the missing photos in batches (fast)."""
        with self.cache_lock:
            if sector in self.refreshing: return False
            self.refreshing.add(sector)
        try:
            started = time.time()
            try:
                with self.reading: rows = self.api.services(sector)
            except Exception as error:
                old = self.errors.get(sector)
                self.errors[sector] = (time.time(), str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__, (old[2] if old else 0)+1)
                print('Setor %s: leitura do programa falhou: %s' % (sector, self.errors[sector][1]), flush=True)
                raise
            self.errors.pop(sector, None)
            with self.cache_lock:
                # A + / − made while this (slow) reading was on its way is newer than what the program returned.
                old = {r['chave']: r for r in (self.cache.get(sector) or {}).get('rows', [])}
                for row in rows:
                    if self.touched.get(row['chave'], 0) > started and row['chave'] in old:
                        row['contador'], row['estado'] = old[row['chave']]['contador'], old[row['chave']]['estado']
                self.cache[sector] = {'t': time.time(), 'rows': rows}
            self.save_cache()
            self.photos.mkdir(exist_ok=True)
            missing = [r['chave'] for r in rows if r['chave'] and CHAVE.match(r['chave']) and not (self.photos/(r['chave']+'.jpg')).is_file()]
            for start in range(0, len(missing), 20):
                try:
                    batch = self.api.images(sector, missing[start:start+20]) or {}
                    for key, item in batch.items():
                        raw = base64.b64decode((item or {}).get('imagem') or '')
                        if raw and CHAVE.match(key): (self.photos/(key+'.jpg')).write_bytes(raw)
                except (RuntimeError, ValueError): break
            return True
        finally:
            with self.cache_lock: self.refreshing.discard(sector)

    def _try_refresh(self, sector):
        try: return self.refresh(sector)
        except Exception: return False

    def refresh_later(self, sector):
        threading.Thread(target=self._quiet_refresh, args=(sector,), daemon=True).start()

    def _quiet_refresh(self, sector):
        try: self.refresh(sector)
        except Exception: pass  # the next reading will try again; the screen keeps the last list

    def _watch(self):
        while True:
            now = time.time()
            for sector, seen in list(self.viewed.items()):
                hit = self.cache.get(sector)
                if now-seen < self.WATCH and (not hit or now-hit['t'] >= self.REFRESH) and sector not in self.refreshing and not self.backoff(sector):
                    self.refresh_later(sector)
            time.sleep(2)

    def warm(self):
        """At start: read every configured sector in the background, so the first screen opens at once."""
        for sector in self.accounts.load().get('setores', {}): self.viewed[sector] = time.time()
        if self.watcher is None and self.viewed:
            self.watcher = threading.Thread(target=self._watch, daemon=True); self.watcher.start()

    def list(self, sector, client=None, fresh=False):
        sector = self.check_sector(sector)
        self.viewed[sector] = time.time()
        if self.watcher is None:
            self.watcher = threading.Thread(target=self._watch, daemon=True); self.watcher.start()
        if sector not in self.cache and (sector in self.refreshing or self.backoff(sector) or not self._try_refresh(sector)):
            for _ in range(250):  # a background reading is already on its way: wait for it (up to 25 s)
                if sector in self.cache or sector not in self.refreshing: break
                time.sleep(0.1)
        elif fresh: self.refresh_later(sector)
        hit = self.cache.get(sector)
        if not hit:
            err = self.errors.get(sector)
            raise RuntimeError('Ainda a ler este setor no programa (pode demorar até um minuto).' +
                               (' Última tentativa: %s' % err[1] if err else ''))
        rows = hit['rows']
        names = self.names() or {}
        client = re.sub(r'\D', '', str(client or ''))
        if client:
            exact = [r for r in rows if r['cliente'] == client]
            rows = exact or [r for r in rows if r['cliente'].startswith(client)]
        zones = self.zones() or {}
        marks = self.assessments(); held = self.next_load()
        return [{**r, 'nome': names.get(r['cliente'], ''), 'zona': zones.get(r['chave']) or zones.get('cliente:'+r['cliente']) or '',
                 'sub': sub_reference(r['cliente'], r['descricao'], r['nota']), 'avaliacao': marks.get(r['chave']),
                 'proxima_carga': r['chave'] in held}
                for r in sorted(rows, key=lambda r: (r['prazo'], r['cliente']))]

    def where(self, client):
        """Configured sectors (from the last readings) where this client has services: [{id, nome, servicos, jantes}]."""
        client = re.sub(r'\D', '', str(client or ''))
        if not client: return []
        names = {str(s['id']): s['nome'] for s in self.sectors()}
        out = []
        for sector, name in names.items():
            rows = [r for r in (self.cache.get(sector) or {}).get('rows', []) if r['cliente'] == client]
            if rows: out.append({'id': int(sector), 'nome': name, 'servicos': len(rows), 'jantes': sum(r['quantidade'] for r in rows)})
        return out

    def elsewhere(self, sector, client):
        """The client's services that are NOT in this sector, from the other configured sectors (last readings).
        One entry per service, with every sector where it is: [{chave, tipo, ..., setores: [{id, nome, contador}]}]."""
        client = re.sub(r'\D', '', str(client or ''))
        if not client: return []
        here = str(int(sector)); names = {str(s['id']): s['nome'] for s in self.sectors()}
        mine = {r['chave'] for r in (self.cache.get(here) or {}).get('rows', [])}
        out = {}
        for sid, name in names.items():
            if sid == here: continue
            for r in (self.cache.get(sid) or {}).get('rows', []):
                if r['cliente'] != client or r['chave'] in mine: continue
                item = out.setdefault(r['chave'], {**{k: r.get(k) for k in ('chave', 'tipo', 'cor', 'tamanho', 'quantidade', 'prazo', 'descricao')}, 'setores': []})
                item['setores'].append({'id': int(sid), 'nome': name, 'contador': r.get('contador') or 0, 'estado': r.get('estado')})
        return sorted(out.values(), key=lambda r: r['prazo'] or '')

    def route(self, sector, chave):
        """Where this wheel is on its route: state in each department (from the same reading as this sector's list)."""
        sector = self.check_sector(sector)
        if not CHAVE.match(chave or ''): raise ValueError('Serviço inválido.')
        find = lambda sid: next((r for r in (self.cache.get(sid) or {}).get('rows', []) if r['chave'] == chave), None)
        row = find(sector)
        if not row: raise ValueError('Este serviço já não está neste setor. Atualiza o ecrã.')
        try: names = {str(d['id']): d['nome'] for d in self.api.departments()}
        except Exception: names = {}
        pretty = lambda n: n.upper() if n.islower() and n.isascii() and len(n) <= 3 else n
        complete = bool(row.get('rota'))
        steps = row.get('rota') or [{'id': int(k)} for k in self.accounts.load()['setores']]
        out = []
        for d in steps:
            sid = str(int(d['id'])); here = sid == sector; other = row if here else find(sid)
            if not complete and not other: continue  # older reading without the route: only what this PC has seen
            estado = row['estado'] if here else (d['estado'] if 'estado' in d else other.get('estado'))
            contador = other['contador'] if other else d.get('contador')
            out.append({'id': int(sid), 'nome': pretty(names.get(sid, 'Departamento ' + sid)), 'estado': estado,
                        'contador': contador, 'quantidade': row['quantidade'], 'este': here})
        return {'percurso': out, 'completo': complete}

    # --- damage assessment (kept on this PC only) ---
    def questions(self):
        path = self.root/'avaliacao_perguntas.json'
        if not path.is_file(): path.write_text(json.dumps(DEFAULT_QUESTIONS, ensure_ascii=False, indent=1), encoding='utf-8')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, list) and data and data[0] == FIRST_QUESTIONS_ESTADO and len(data) == len(DEFAULT_QUESTIONS):
                path.write_text(json.dumps(DEFAULT_QUESTIONS, ensure_ascii=False, indent=1), encoding='utf-8')  # first version: damage level 1-5
                return DEFAULT_QUESTIONS
            if isinstance(data, list) and all(q.get('id') and q.get('opcoes') for q in data): return data
        except (OSError, ValueError, AttributeError): pass
        return DEFAULT_QUESTIONS

    def assessments(self):
        """Latest assessment per service: {chave: {quando, decisao, respostas, colaborador}}."""
        path = self.root/'avaliacoes.jsonl'
        try: stamp = path.stat().st_mtime
        except OSError: return {}
        if getattr(self, '_marks', None) and self._marks[0] == stamp: return self._marks[1]
        marks = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            try: entry = json.loads(line)
            except ValueError: continue
            marks[entry.get('servico')] = {'quando': entry.get('quando'), 'decisao': (entry.get('respostas') or {}).get('decisao'),
                                           'respostas': entry.get('respostas') or {}, 'colaborador': entry.get('colaborador')}
        self._marks = (stamp, marks)
        return marks

    # --- ADS: wheels too damaged for this load stay for the next one (kept on this PC only) ---
    def next_load(self):
        try: return json.loads((self.root/'ads_proxima_carga.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def hold(self, sector, chave, value, worker=None):
        sector = self.check_sector(sector)
        if not CHAVE.match(chave or ''): raise ValueError('Serviço inválido.')
        current = next((r for r in (self.cache.get(sector) or {}).get('rows', []) if r['chave'] == chave), None)
        if not current: raise ValueError('Este serviço já não está neste setor. Atualiza o ecrã.')
        if current['cliente'] not in SUBCLIENTS: raise ValueError('Só para os clientes com cargas (ADS).')
        with self.action_lock:
            data = self.next_load()
            if value:
                data[chave] = {'quando': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'setor': int(sector), 'cliente': current['cliente'],
                               'sub': sub_reference(current['cliente'], current['descricao'], current['nota']), 'tipo': current['tipo'],
                               'cor': current['cor'], 'tamanho': current['tamanho'], 'quantidade': current['quantidade'],
                               'nota': current['nota'] or current['descricao'], 'entrada': current.get('entrada_hora') or current.get('entrada') or '', 'colaborador': (worker or '').strip() or None}
            else: data.pop(chave, None)
            with open(self.root/'auditoria.jsonl', 'a', encoding='utf-8') as log:
                log.write(json.dumps({'quando': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'evento': 'proxima_carga_marcada' if value else 'proxima_carga_anulada',
                                      'servico': chave, 'cliente': current['cliente'], 'setor': int(sector), 'colaborador': (worker or '').strip() or None},
                                     ensure_ascii=False)+'\n')
            path = self.root/'ads_proxima_carga.json'; temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8'); os.replace(temp, path)
        return bool(value)

    def board(self, days=None):
        """Assessments for the panel table (latest per service) plus the ADS wheels held for the next load."""
        path = self.root/'avaliacoes.jsonl'; latest = {}
        try: lines = path.read_text(encoding='utf-8').splitlines()
        except OSError: lines = []
        limit = (datetime.now()-timedelta(days=days-1)).strftime('%Y-%m-%d') if days else ''
        for line in lines:
            try: entry = json.loads(line)
            except ValueError: continue
            if entry.get('quando', '') >= limit: latest[entry.get('servico')] = entry
        names = {}
        try: names = {str(sec['id']): sec['nome'] for sec in self.sectors()}
        except Exception: pass
        held = self.next_load()
        rows = sorted(latest.values(), key=lambda e: e.get('quando', ''), reverse=True)
        known = {}
        with self.cache_lock:
            for sector, hit in self.cache.items():
                for row in hit.get('rows', []): known.setdefault(row['chave'], (sector, row))
        for r in rows:
            r['setor_nome'] = names.get(str(r.get('setor')), str(r.get('setor'))); r['proxima_carga'] = r.get('servico') in held
            found = known.get(r.get('servico'))
            if found and not r.get('entrada'): r['entrada'] = found[1].get('entrada_hora') or found[1].get('entrada') or ''
            r['foto_setor'] = int(found[0]) if found else r.get('setor')  # a sector that still has it (the photo is cached on this PC)
        hold = []
        for k, v in held.items():
            found = known.get(k)
            hold.append({**v, 'servico': k, 'setor_nome': names.get(str(v.get('setor')), str(v.get('setor'))),
                         'entrada': v.get('entrada') or (found[1].get('entrada_hora') or found[1].get('entrada') if found else ''),
                         'foto_setor': int(found[0]) if found else v.get('setor')})
        hold.sort(key=lambda e: e.get('quando', ''), reverse=True)
        return {'avaliacoes': rows, 'proxima_carga': hold, 'perguntas': self.questions()}

    def assess(self, sector, chave, answers, device='', worker=None):
        sector = self.check_sector(sector)
        if not CHAVE.match(chave or ''): raise ValueError('Serviço inválido.')
        current = next((r for r in (self.cache.get(sector) or {}).get('rows', []) if r['chave'] == chave), None)
        if not current: raise ValueError('Este serviço já não está neste setor. Atualiza o ecrã.')
        worker = (worker or '').strip() or None
        if worker and worker not in self.team(sector): raise ValueError('Colaborador desconhecido neste setor.')
        clean = {}
        for q in self.questions():
            value = str((answers or {}).get(q['id']) or '')
            if value and value not in q['opcoes']: raise ValueError('Resposta inválida em «%s».' % q['texto'])
            if not value and q.get('obrigatoria'): raise ValueError('Falta responder «%s».' % q['texto'])
            if value: clean[q['id']] = value
        entry = {'quando': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'setor': int(sector), 'servico': chave, 'cliente': current['cliente'],
                 'sub': sub_reference(current['cliente'], current['descricao'], current['nota']), 'tipo': current['tipo'],
                 'cor': current['cor'], 'tamanho': current['tamanho'], 'quantidade': current['quantidade'], 'prazo': current['prazo'],
                 'entrada': current.get('entrada_hora') or current.get('entrada') or '', 'respostas': clean, 'colaborador': worker, 'aparelho': device}
        with self.action_lock:
            with open(self.root/'avaliacoes.jsonl', 'a', encoding='utf-8') as log: log.write(json.dumps(entry, ensure_ascii=False)+'\n')
        return entry

    def photo(self, sector, chave, strict=True):
        """strict (workshop screens): only services of that sector. The administrator also sees photos already on this PC."""
        if not CHAVE.match(chave or ''): raise ValueError('Foto inválida.')
        self.photos.mkdir(exist_ok=True)
        target = self.photos/(chave+'.jpg')
        sector = self.check_sector(sector)
        inside = any(r['chave'] == chave for r in (self.cache.get(sector) or {}).get('rows', []))
        if strict and not inside: raise ValueError('Esta jante não está neste setor.')  # no photos of other services by code
        if target.is_file(): return target.read_bytes()
        if not inside: raise ValueError('Esta jante não está neste setor.')
        data = self.api.images(sector, [chave]).get(chave) or {}
        raw = base64.b64decode(data.get('imagem') or '')
        if not raw: raise RuntimeError('Sem fotografia.')
        target.write_bytes(raw)
        return raw

    def act(self, sector, action, chave, device='', worker=None, admin=False, boss=False):
        """+ / − / iniciar / terminar on one service. Checked against Jarvis's reading of the sector (at most a few
        seconds old) so the person does not wait for the program's slow list; the action itself is a quick request."""
        modo_escrita.exigir_escrita()  # DEV: só com o painel em ESCRITA
        sector = self.check_sector(sector)
        if action not in ('mais', 'menos', 'iniciar', 'terminar'): raise ValueError('Ação desconhecida.')
        if not CHAVE.match(chave or ''): raise ValueError('Serviço inválido.')
        team = self.team(sector)
        worker = (worker or '').strip() or None
        if worker and worker not in team and not (boss and worker == ENCARREGADO_NOME): raise ValueError('Colaborador desconhecido neste setor.')
        if team and not worker and not admin and not boss: raise ValueError('Escolhe primeiro quem és.')
        with self.action_lock:
            hit = self.cache.get(sector)
            if not hit or time.time()-hit['t'] > 120: self.refresh(sector); hit = self.cache.get(sector)
            current = next((r for r in (hit or {}).get('rows', []) if r['chave'] == chave), None)
            if not current: raise ValueError('Este serviço já não está neste setor. Atualiza o ecrã.')
            before = {'contador': current['contador'], 'estado': current['estado']}
            if action in ('mais', 'menos'):
                value = current['contador']+(1 if action == 'mais' else -1)
                if value > current['quantidade']: raise ValueError('O contador não pode passar da quantidade (%d).' % current['quantidade'])
                if value < 0: raise ValueError('O contador não pode ser negativo.')
                self.api.set_counter(sector, chave, value); after = {'contador': value}
                current['contador'] = value
            else:
                want = 'play' if action == 'iniciar' else 'stop'
                if current['estado'] != want or not current['tarefa'] or int(current['tarefa']) <= 0:
                    raise ValueError('O estado mudou entretanto. Atualiza o ecrã.')
                if current['contador'] != current['quantidade']:  # same rule as the dashboard
                    raise ValueError('Conta primeiro as jantes até %d/%d.' % (current['quantidade'], current['quantidade']))
                (self.api.start if action == 'iniciar' else self.api.stop)(sector, current['tarefa'])
                after = {'estado': 'stop' if action == 'iniciar' else 'terminado'}
                current['estado'] = after['estado']
            self.touched[chave] = time.time()
            self.refresh_later(sector)  # confirm with the program in the background
            entry = {'quando': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'setor': int(sector), 'acao': action, 'servico': chave,
                     'cliente': current['cliente'], 'tipo': current['tipo'], 'grupo': job_group(current['tipo']), 'tamanho': current['tamanho'],
                     'antes': before, 'depois': after, 'aparelho': device, 'colaborador': worker, 'administrador': bool(admin)}
            with open(self.log, 'a', encoding='utf-8') as log: log.write(json.dumps(entry, ensure_ascii=False)+'\n')
            return entry


# --- workshop network screen ---------------------------------------------------
def private(address):
    try:
        ip = ipaddress.ip_address(address.split('%')[0])
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def host_ok(host):
    """Only an IP address of the local network (or this PC's own name) in the address bar."""
    name = (host or '').strip().lower()
    name = name[1:name.index(']')] if name.startswith('[') and ']' in name else name.rsplit(':', 1)[0] if name.count(':') == 1 else name
    name = name.rstrip('.')
    if not name or '%' in name or name in ('0.0.0.0', '::'): return False
    if name in ('localhost', socket.gethostname().lower(), socket.gethostname().lower()+'.local'): return True
    return private(name)


ENCARREGADO_NOME = 'Encarregado'
# A senha do encarregado (dá acesso a qualquer setor) já não está no código: só a impressão digital, em encarregado.json.
ENCARREGADO_HORAS = 12    # depois disto volta a pedir a senha


class SectorHandler(http.server.BaseHTTPRequestHandler):
    service = None
    attempts = {}
    pin_lock = threading.Lock()
    server_version = 'JarvisSetores/1.0'

    def log_message(self, *args): pass

    def send(self, body, mime='application/json; charset=utf-8', status=200, headers=None):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY'); self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def cookie_name(self, sector): return 'setor_%d' % int(sector)

    def sign(self, sector):
        # Bound to the sector's current PIN: changing the PIN logs every device of that sector out.
        stored = self.service.accounts.load()['setores'].get(str(int(sector)), {}).get('pin') or ''
        return hmac.new(self.service.secret(), ('setor:%d:%s' % (int(sector), stored)).encode(), 'sha256').hexdigest()

    def boss(self): return Encarregado(self.service.root)

    def boss_sign(self):
        # Bound to the stored fingerprint: changing the password logs every boss device out.
        return hmac.new(self.service.secret(), ('encarregado:%s' % self.boss().stored()).encode(), 'sha256').hexdigest()

    def is_boss(self):
        if not self.boss().configured(): return False
        match = re.search(r'(?:^|;\s*)encarregado=([a-f0-9]{64})', self.headers.get('Cookie', ''))
        return bool(match) and hmac.compare_digest(match.group(1), self.boss_sign())

    def allowed(self, sector):
        if self.is_boss(): return True
        stored = self.service.accounts.load()['setores'].get(str(int(sector)), {}).get('pin')
        if not stored: return True
        match = re.search(r'(?:^|;\s*)%s=([a-f0-9]{64})' % self.cookie_name(sector), self.headers.get('Cookie', ''))
        return bool(match) and hmac.compare_digest(match.group(1), self.sign(sector))

    def guard(self):
        if not private(self.client_address[0]):
            self.send({'erro': 'Só disponível na rede da oficina.'}, status=403); return False
        if not host_ok(self.headers.get('Host', '')):
            # A page from the internet pointing its own name at this PC (DNS rebinding) is refused.
            self.send({'erro': 'Endereço não permitido. Usa o endereço IP deste PC.'}, status=403); return False
        return True

    def do_HEAD(self): self.send({'erro': 'Método não permitido.'}, status=405)

    def do_GET(self):
        if not self.guard(): return
        url = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(url.query)
        try:
            if url.path in ('/', '/setor'):
                return self.send((HERE.parent/'painel'/'setor.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/setores': return self.send({'setores': self.service.sectors()})
            sector = q.get('setor', ['0'])[0]
            if url.path == '/api/servicos':
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                rows = self.service.list(sector, q.get('cliente', [''])[0], q.get('atualizar', ['0'])[0] == '1')
                return self.send({'servicos': rows, 'hoje': date.today().isoformat(), 'lido': self.service.read_time(sector) or datetime.now().strftime('%H:%M:%S')})
            if url.path == '/api/onde':
                self.service.check_sector(sector)
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                # only sectors this device may open (no PIN, or its PIN already entered here)
                return self.send({'setores': [x for x in self.service.where(q.get('cliente', [''])[0]) if self.allowed(x['id'])]})
            if url.path == '/api/procura':
                # search by client: also the services in other sectors (read only, no buttons)
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                return self.send({'servicos': self.service.elsewhere(self.service.check_sector(sector), q.get('cliente', [''])[0])})
            if url.path == '/api/percurso':
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                return self.send(self.service.route(sector, q.get('chave', [''])[0]))
            if url.path == '/api/perguntas': return self.send({'perguntas': self.service.questions()})
            if url.path == '/api/colaboradores':
                if not self.allowed(sector): return self.send({'erro': 'PIN'}, status=401)
                return self.send({'nomes': self.service.team(sector), 'hoje': self.service.totals(sector).get(str(int(sector)), {}),
                                  'sair_min': self.service.idle_minutes})
            if url.path == '/api/foto':
                if not self.allowed(sector): return self.send({'erro': 'PIN'}, status=401)
                data = self.service.photo(sector, q.get('chave', [''])[0])
                return self.send(data, 'image/jpeg', headers={'Cache-Control': 'max-age=86400'})
            self.send({'erro': 'Página não encontrada.'}, status=404)
        except ValueError as error: self.send({'erro': str(error)}, status=400)
        except RuntimeError as error: self.send({'erro': str(error)}, status=503)
        except Exception: self.send({'erro': 'O pedido falhou.'}, status=500)

    def do_POST(self):
        if not self.guard(): return
        # JSON + custom header: a page from another site cannot send this without the browser blocking it.
        if self.headers.get('X-Jarvis-Setor') != '1' or not self.headers.get('Content-Type', '').startswith('application/json'):
            return self.send({'erro': 'Pedido inválido.'}, status=400)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4000: raise ValueError('Pedido inválido.')
            body = json.loads(self.rfile.read(size))
            path = urllib.parse.urlparse(self.path).path
            sector = str(int(body.get('setor', 0)))
            if path == '/api/encarregado':
                with self.pin_lock:  # same limit as the sector PINs
                    ip = self.client_address[0]; now = time.time()
                    fails = [t for t in self.attempts.get(ip, []) if now-t < 300]
                    if len(fails) >= 5:
                        registar(self.service.root, 'bloqueado', onde='encarregado', ip=ip)
                        return self.send({'erro': 'Demasiadas tentativas. Espera 5 minutos.'}, status=429)
                    if not self.boss().configured():
                        return self.send({'erro': 'A senha do encarregado ainda não está definida (painel do Jarvis → Segurança).'}, status=403)
                    if not self.boss().check(str(body.get('pin', ''))):
                        self.attempts[ip] = fails+[now]; registar(self.service.root, 'encarregado_errado', ip=ip)
                        return self.send({'erro': 'Senha incorreta.'}, status=403)
                cookie = 'encarregado=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d' % (self.boss_sign(), ENCARREGADO_HORAS*3600)
                return self.send({'ok': True}, headers={'Set-Cookie': cookie})
            if path == '/api/sair_encarregado':
                return self.send({'ok': True}, headers={'Set-Cookie': 'encarregado=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
            if path == '/api/entrar':
                with self.pin_lock:  # one PIN check at a time: guesses sent together cannot pass the limit
                    ip = self.client_address[0]; now = time.time()
                    fails = [t for t in self.attempts.get(ip, []) if now-t < 300]
                    if len(fails) >= 5:
                        registar(self.service.root, 'bloqueado', setor=sector, ip=ip)
                        return self.send({'erro': 'Demasiadas tentativas. Espera 5 minutos.'}, status=429)
                    stored = self.service.accounts.load()['setores'].get(sector, {}).get('pin')
                    if stored and not pin_ok(str(body.get('pin', '')), stored):
                        self.attempts[ip] = fails+[now]; registar(self.service.root, 'pin_setor_errado', setor=sector, ip=ip)
                        return self.send({'erro': 'PIN incorreto.'}, status=403)
                cookie = '%s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000' % (self.cookie_name(sector), self.sign(sector))
                return self.send({'ok': True}, headers={'Set-Cookie': cookie})
            if path == '/api/acao':
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                entry = self.service.act(sector, str(body.get('acao', '')), str(body.get('chave', '')), self.client_address[0], str(body.get('colaborador') or ''), boss=self.is_boss())
                return self.send({'ok': True, 'acao': entry})
            if path in ('/api/carga', '/api/avaliar'):  # administrator only (Jarvis panel), not the workshop screens
                return self.send({'erro': 'Só o administrador pode fazer isto (no painel do Jarvis).'}, status=403)
            if path == '/api/carga':
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                return self.send({'ok': True, 'proxima_carga': self.service.hold(sector, str(body.get('chave', '')), bool(body.get('valor')), str(body.get('colaborador') or ''))})
            if path == '/api/avaliar':
                if not self.allowed(sector): return self.send({'erro': 'PIN do setor necessário.', 'pin': True}, status=401)
                entry = self.service.assess(sector, str(body.get('chave', '')), body.get('respostas') or {}, self.client_address[0], str(body.get('colaborador') or ''))
                return self.send({'ok': True, 'avaliacao': entry})
            self.send({'erro': 'Página não encontrada.'}, status=404)
        except ValueError as error: self.send({'erro': str(error)}, status=400)
        except RuntimeError as error: self.send({'erro': str(error)}, status=503)
        except Exception: self.send({'erro': 'O pedido falhou.'}, status=500)


def serve_sectors(service, port=PORT, host='0.0.0.0'):
    """Listener for the workshop network. Returns the server (already running in a thread)."""
    handler = type('Handler', (SectorHandler,), {'service': service, 'attempts': {}, 'pin_lock': threading.Lock()})
    server = http.server.ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def lan_addresses():
    import socket
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9)); found.add(s.getsockname()[0])  # no packet is sent
    except OSError: pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET): found.add(info[4][0])
    except OSError: pass
    return sorted(a for a in found if private(a) and not a.startswith('127.') and not a.startswith('100.'))
