"""Read-only production page reachable from anywhere (car screen, any browser), protected by a PIN.

- Listens only on 127.0.0.1:12399; Tailscale Funnel publishes it as https://<this-pc>.ts.net:8443/.
- Shows COUNTS ONLY: per sector how many jantes are left (late / today / tomorrow / by zone), what each
  collaborator did today, and the production count. No client names, no buttons, nothing else of Jarvis.
- PIN of 6-8 digits (only its PBKDF2 fingerprint is stored), signed cookie for 30 days, and a lock after
  5 wrong PINs from one address or 15 in total within 15 minutes.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

PORT = 12399
HERE = Path(__file__).resolve().parent


class ConsultaConfig:
    def __init__(self, root):
        self.file = Path(root)/'consulta.json'

    def load(self):
        try: return json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def enabled(self): return bool(self.load().get('pin'))

    def set_pin(self, pin):
        if not re.fullmatch(r'\d{6,8}', str(pin)): raise ValueError('O PIN tem de ter 6 a 8 algarismos.')
        salt = secrets.token_hex(16)
        data = {'pin': {'salt': salt, 'iterations': 600000,
                        'hash': hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), 600000).hex()},
                'segredo': secrets.token_hex(32)}  # new secret: every old session stops working
        temp = self.file.with_suffix('.tmp'); temp.write_text(json.dumps(data), encoding='utf-8'); os.replace(temp, self.file)

    def check(self, pin):
        conf = self.load().get('pin') or {}
        if not conf or not re.fullmatch(r'\d{6,8}', str(pin or '')): return False
        digest = hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(conf['salt']), conf['iterations']).hex()
        return hmac.compare_digest(digest, conf['hash'])

    def sign(self, expiry):
        return hmac.new(bytes.fromhex(self.load()['segredo']), ('consulta:%d' % expiry).encode(), 'sha256').hexdigest()

    def new_cookie(self, days=30):
        expiry = int(time.time())+days*86400
        return '%d.%s' % (expiry, self.sign(expiry))

    def valid(self, header):
        match = re.search(r'(?:^|;\s*)jarvis_consulta=(\d{10})\.([0-9a-f]{64})(?:;|$)', header or '')
        if not match or not self.enabled(): return False
        return int(match.group(1)) > time.time() and hmac.compare_digest(match.group(2), self.sign(int(match.group(1))))


def summary(service, today=None):
    """Counts only, for every configured sector, plus the production panel count."""
    today = today or date.today()
    out = {'gerado': datetime.now().strftime('%H:%M'), 'dia': today.isoformat(), 'setores': []}
    sectors = service.setores.sectors() if service.setores.accounts.configured() else []
    totals = service.setores.totals(None, today, today)
    for sector in sectors:
        item = {'nome': sector['nome'], 'erro': None}
        try:
            rows = service.setores.list(sector['id'])
        except Exception as error:
            item['erro'] = str(error) if isinstance(error, (RuntimeError, ValueError)) else 'Sem dados agora.'
            out['setores'].append(item); continue
        def left(rs): return sum(max(0, r['quantidade']-r['contador']) for r in rs)
        def day(r):
            try: return (date.fromisoformat(r['prazo'])-today).days
            except ValueError: return None
        zones = {}
        for r in rows:
            zones[r.get('zona') or 'Sem zona'] = zones.get(r.get('zona') or 'Sem zona', 0)+max(0, r['quantidade']-r['contador'])
        item.update({
            'total': sum(r['quantidade'] for r in rows), 'faltam': left(rows), 'servicos': len(rows),
            'atrasadas': left([r for r in rows if (day(r) or 0) < 0]),
            'hoje': left([r for r in rows if day(r) == 0]), 'amanha': left([r for r in rows if day(r) == 1]),
            'a_decorrer': sum(1 for r in rows if r.get('estado') == 'stop'),
            'zonas': sorted(({'zona': z, 'faltam': n} for z, n in zones.items() if n), key=lambda x: -x['faltam']),
            'colaboradores': sorted(({'nome': n, **v} for n, v in totals.get(str(sector['id']), {}).items()), key=lambda x: -x['total']),
        })
        out['setores'].append(item)
    try:
        prod = service.production_state()
        out['producao'] = [{k: d.get(k) for k in ('rotulo', 'total', 'maquinadas', 'pintadas', 'outros', 'setor1', 'setor2', 'servicos')}
                           for d in (prod.get('dias') or [])]
        out['producao_lida'] = prod.get('gerado')
    except Exception:
        out['producao'] = []
    return out


class ConsultaHandler(http.server.BaseHTTPRequestHandler):
    service = None
    config = None
    failures = {}
    lock = threading.Lock()
    checking = threading.Lock()
    server_version = 'JarvisConsulta/1.0'

    def log_message(self, *args): pass

    def send(self, body, mime='application/json; charset=utf-8', status=200, headers=None):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        for k, v in {'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                     'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow',
                     'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:",
                     **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def client(self):
        # The proxy (Tailscale Funnel) appends the real address at the END; the first entries can be written by anyone.
        return (self.headers.get('X-Forwarded-For') or self.client_address[0]).split(',')[-1].strip()

    def do_HEAD(self): self.send({'erro': 'Método não permitido.'}, status=405)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/consulta'):
            return self.send((HERE.parent/'painel'/'consulta.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/dados':
            if not self.config.valid(self.headers.get('Cookie', '')): return self.send({'erro': 'PIN necessário.', 'pin': True}, status=401)
            try: return self.send(summary(self.service))
            except Exception: return self.send({'erro': 'Sem dados agora. Tenta daqui a pouco.'}, status=503)
        if path == '/robots.txt': return self.send(b'User-agent: *\nDisallow: /\n', 'text/plain')
        self.send({'erro': 'Não encontrado.'}, status=404)

    def do_POST(self):
        if self.path.split('?')[0] != '/entrar': return self.send({'erro': 'Não encontrado.'}, status=404)
        if self.headers.get('X-Jarvis-Consulta') != '1': return self.send({'erro': 'Pedido inválido.'}, status=400)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(size)) if 0 < size <= 200 else {}
        except (ValueError, TypeError): body = {}
        with self.checking:  # one PIN check at a time: guesses sent all together cannot slip past the limit
            ip, now = self.client(), time.time()
            with self.lock:
                for key in list(self.failures): self.failures[key] = [t for t in self.failures[key] if now-t < 900]
                if len(self.failures.get(ip, [])) >= 5 or sum(len(v) for v in self.failures.values()) >= 15:
                    return self.send({'erro': 'Demasiadas tentativas. Espera 15 minutos.'}, status=429)
            if not self.config.check(str(body.get('pin', ''))):
                with self.lock: self.failures.setdefault(ip, []).append(now)
                time.sleep(1)  # slows down guessing
                return self.send({'erro': 'PIN incorreto.'}, status=403)
        cookie = 'jarvis_consulta=%s; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=%d' % (self.config.new_cookie(), 30*86400)
        self.send({'ok': True}, headers={'Set-Cookie': cookie})


def serve_consulta(service, root, port=PORT):
    config = ConsultaConfig(root)
    handler = type('Handler', (ConsultaHandler,), {'service': service, 'config': config, 'failures': {}, 'lock': threading.Lock(), 'checking': threading.Lock()})
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)  # local only: Tailscale Funnel publishes it
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
