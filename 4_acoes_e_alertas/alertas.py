# Alertas da produção: jantes que já deviam ter passado o torno e ainda não passaram.
# Pontos de controlo (no dia do prazo):  15:00 já passou o torno (laranja)  ·  16:00 devia estar no CNC/pintura (vermelho).
# Jantes cujo prazo já passou (para trás) e continuam antes do torno: sempre vermelho.
# Só maquinadas e pintadas (os «outros trabalhos» ficam de fora). Usa a contagem da produção (producao.json),
# que o Jarvis já atualiza de 10 em 10 minutos. A notificação vai para o iPhone pela app ntfy, uma vez por ponto de controlo.
from __future__ import annotations
import json, os, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

CHECKPOINTS = [  # (id, hora, nível, frase)
    ('torno15', 15, 'laranja', 'ainda não passaram o torno'),
    ('cnc16', 16, 'vermelho', 'deviam estar no CNC / pintura e ainda não passaram o torno'),
]


def next_working_day(day):
    day += timedelta(days=1)
    return day + timedelta(days=1) if day.weekday() == 6 else day


def items(data):
    """Every service in the production count (para trás + days on screen), once, with its zone."""
    seen, out = set(), []
    for view in ([data.get('atras')] if data.get('atras') else []) + list(data.get('dias') or []):
        for zone in view.get('zonas') or []:
            for i in zone.get('lista') or []:
                if i.get('id') in seen: continue
                seen.add(i.get('id')); out.append({**i, 'zona': zone.get('nome', '')})
    return out


def compute(data, now=None):
    """{'vermelho': [...], 'laranja': [...], 'amanha': 'AAAA-MM-DD', 'gerado': ...}: jantes antes do torno fora de horas."""
    now = now or datetime.now()
    today = now.date().isoformat(); tomorrow = next_working_day(now.date()).isoformat()
    red, orange = [], []
    for i in items(data):
        if i.get('grupo') not in ('Maquinada', 'Pintada'): continue      # outros trabalhos: fora
        if i.get('setor') == 2: continue                                  # já passou o torno
        prazo = i.get('prazo') or ''
        if not prazo: continue
        entry = {k: i.get(k) for k in ('id', 'cliente', 'quantidade', 'tamanho', 'tipo', 'cor', 'grupo', 'prazo', 'estado', 'zona', 'imagem', 'entrada', 'detalhes')}
        if prazo < today:
            entry['motivo'] = 'Prazo já passou'; red.append(entry)
        elif prazo == today and now.hour >= 16:
            entry['motivo'] = 'Prazo hoje · devia estar no CNC / pintura às 16:00'; red.append(entry)
        elif prazo == today and now.hour >= 15:
            entry['motivo'] = 'Prazo hoje · devia ter passado o torno às 15:00'; orange.append(entry)
    key = lambda e: (e['prazo'], e['zona'], e['cliente'])
    return {'vermelho': sorted(red, key=key), 'laranja': sorted(orange, key=key), 'amanha': tomorrow,
            'jantes': sum((e['quantidade'] or 1) for e in red + orange), 'gerado': now.strftime('%Y-%m-%d %H:%M')}


def short(e):
    return '%s %s %dx%s"' % (e['cliente'].split(' · ')[0], e['zona'], e['quantidade'] or 1, e['tamanho'])


def message(check, rows):
    jantes = sum((e['quantidade'] or 1) for e in rows)
    title = '⚠ %d jante%s de hoje %s' % (jantes, '' if jantes == 1 else 's', check[3])
    body = ', '.join(short(e) for e in rows[:8]) + (' e mais %d serviços.' % (len(rows)-8) if len(rows) > 8 else '.')
    return title, body


def due_notifications(data, state, now=None):
    """Checkpoints whose hour has come today and were not sent yet: [(id, title, body, rows)]. Marks them in state."""
    now = now or datetime.now(); today = now.date().isoformat(); tomorrow = next_working_day(now.date()).isoformat()
    if now.date().weekday() == 6: return []                     # domingo não há produção
    out = []
    for check in CHECKPOINTS:
        if now.hour < check[1] or state.get(check[0]) == today: continue
        state[check[0]] = today
        rows = [e for e in items(data) if e.get('grupo') in ('Maquinada', 'Pintada') and e.get('setor') != 2 and (e.get('prazo') or '') == today]
        late = [e for e in items(data) if e.get('grupo') in ('Maquinada', 'Pintada') and e.get('setor') != 2 and (e.get('prazo') or '') and e['prazo'] < today]
        if not rows and not late: continue
        title, body = message(check, rows) if rows else ('⚠ Jantes atrasadas antes do torno', '')
        if late:
            n = sum((e['quantidade'] or 1) for e in late)
            body = (body + '\n' if body else '') + '🔴 %d jante%s já fora de prazo e ainda antes do torno.' % (n, '' if n == 1 else 's')
        out.append((check[0], title, body, rows))
    return out


class ProductionAlerts:
    def __init__(self, root):
        self.root = Path(root); self.state_path = self.root/'alertas_estado.json'

    def data(self):
        path = self.root/'producao.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

    def state(self):
        try: return json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def current(self, now=None):
        return compute(self.data(), now)

    def ntfy(self):
        try: cfg = json.loads((self.root/'vigilante_config.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): return None, None
        return cfg.get('ntfy_topico'), cfg.get('ntfy_servidor', 'https://ntfy.sh').rstrip('/')

    def notify(self, now=None, send=None):
        """Called after each production refresh: sends the checkpoint message once per day (iPhone, ntfy)."""
        state = self.state(); pending = due_notifications(self.data(), state, now)
        topic, server = self.ntfy()
        for _, title, body, _rows in pending:
            if topic: (send or self.send)(server, topic, title, body)
        if pending or state != self.state():
            temp = self.state_path.with_suffix('.tmp'); temp.write_text(json.dumps(state), encoding='utf-8'); os.replace(temp, self.state_path)
        return pending

    @staticmethod
    def send(server, topic, title, body):
        payload = json.dumps({'topic': topic, 'title': title, 'message': body or title, 'priority': 4, 'tags': ['rotating_light']}).encode('utf-8')
        try: urllib.request.urlopen(urllib.request.Request(server, data=payload, method='POST', headers={'Content-Type': 'application/json'}), timeout=10).close()
        except (OSError, ValueError) as error: print('Alerta ntfy falhou: %s' % error, flush=True)
