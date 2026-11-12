"""Modo ensinar: o Simão diz, jante a jante, que operações de mão de obra direta cada uma precisa (pela ordem) e quanto
tempo leva cada uma. Os tempos são POR JANTE (unidade). Fases em lote, como a estufa, não entram aqui: no planeamento
serão uma capacidade (quantas jantes leva, quanto demora cada fornada).

Tudo fica só neste PC:
  ensino.json            — lista de operações + a última resposta para cada serviço (por id do programa de gestão)
  ensino_historico.jsonl — cada vez que algo é ensinado ou corrigido (para nunca se perder nada)
  ensino_fotos/<id>.jpg  — a fotografia do serviço no momento em que foi ensinado (para, mais tarde, aprender pela foto)

Com centenas de exemplos, isto é a base para o Jarvis sugerir o percurso e os tempos de cada jante.
"""
from __future__ import annotations
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

DEFAULT_OPS = ['Decapagem', 'Torno', 'Soldar', 'Desempenar', 'Empenada de centro', 'Bipartida', 'Tripartida',
               'Fresadora', 'Polimento à escova', 'Cromar parafusos', 'Afinar cor', 'Pó', 'Pintura']
KEEP = ('id', 'cliente', 'quantidade', 'tamanho', 'tipo', 'cor', 'grupo', 'entrada', 'prazo', 'estado', 'setor', 'zona', 'imagem')
MAX_OPS, MAX_WHEELS, MAX_MIN = 30, 200, 24 * 60


class Teaching:
    def __init__(self, root, photo=None, clock=None):
        self.root = Path(root)
        self.file = self.root / 'ensino.json'
        self.history = self.root / 'ensino_historico.jsonl'
        self.photos = self.root / 'ensino_fotos'
        self.photo = photo            # função caminho -> bytes (a mesma que mostra as fotos no ecrã)
        self.clock = clock or datetime.now
        self.lock = threading.Lock()

    def _load(self):
        try: data = json.loads(self.file.read_text(encoding='utf-8')) if self.file.is_file() else {}
        except (OSError, ValueError): data = {}
        data.setdefault('operacoes', list(DEFAULT_OPS)); data.setdefault('jantes', {})
        return data

    def _save(self, data):
        tmp = self.file.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8'); os.replace(tmp, self.file)

    def _summary(self, data):
        return {'operacoes': data['operacoes'], 'total': len(data['jantes']),
                'ensinadas': {k: {'operacoes': v['operacoes'], 'nota': v.get('nota', ''), 'quando': v['quando']} for k, v in data['jantes'].items()}}

    def state(self):
        with self.lock: return self._summary(self._load())

    def act(self, body):
        if not isinstance(body, dict): raise ValueError('Pedido inválido.')
        action = body.get('acao')
        with self.lock:
            data = self._load()
            if action == 'operacao':
                name = ' '.join(str(body.get('nome', '')).split())[:60]
                if not name: raise ValueError('Escreve o nome da operação.')
                if name.casefold() not in [o.casefold() for o in data['operacoes']]: data['operacoes'].append(name)
            elif action == 'guardar':
                ops = self._clean_ops(body.get('operacoes'), data['operacoes'])
                wheels = self._clean_wheels(body.get('jantes'))
                note = str(body.get('nota') or '').strip()[:2000]
                when = self.clock().strftime('%Y-%m-%d %H:%M')
                per_wheel = sum(o['min'] for o in ops)   # minutos de mão de obra por jante
                for w in wheels:
                    qty = w.get('quantidade') if isinstance(w.get('quantidade'), (int, float)) and w.get('quantidade') > 0 else 1
                    entry = {**w, 'operacoes': ops, 'tempo_unidade': 'jante', 'total_min_jante': per_wheel,
                             'total_min_servico': per_wheel * qty, 'nota': note, 'quando': when}
                    data['jantes'][str(w['id'])] = entry
                    self._log({'acao': 'ensinada', **entry})
                self._save(data)
                self._keep_photos(wheels)
                return self._summary(data)
            elif action == 'apagar':
                key = str(body.get('id') or '')
                if data['jantes'].pop(key, None) is not None: self._log({'acao': 'apagada', 'id': key, 'quando': self.clock().strftime('%Y-%m-%d %H:%M')})
            else:
                raise ValueError('Ação desconhecida.')
            self._save(data)
            return self._summary(data)

    @staticmethod
    def _clean_ops(ops, known):
        if not isinstance(ops, list) or not ops: raise ValueError('Escolhe pelo menos uma operação.')
        if len(ops) > MAX_OPS: raise ValueError('Demasiadas operações.')
        out = []
        for o in ops:
            if not isinstance(o, dict) or o.get('op') not in known: raise ValueError('Operação desconhecida.')
            try: minutes = int(o.get('min'))
            except (TypeError, ValueError): raise ValueError('Tempo inválido.')
            if not 0 <= minutes <= MAX_MIN: raise ValueError('Tempo inválido.')
            out.append({'op': o['op'], 'min': minutes})
        return out

    @staticmethod
    def _clean_wheels(wheels):
        if not isinstance(wheels, list) or not wheels: raise ValueError('Escolhe pelo menos uma jante.')
        if len(wheels) > MAX_WHEELS: raise ValueError('Seleção demasiado grande.')
        out = []
        for w in wheels:
            if not isinstance(w, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(w.get('id', ''))): raise ValueError('Jante inválida.')
            out.append({k: (w[k] if isinstance(w[k], (int, float)) and not isinstance(w[k], bool) else str(w[k])[:300])
                        for k in KEEP if w.get(k) is not None})
        return out

    def _log(self, item):
        with self.history.open('a', encoding='utf-8') as f: f.write(json.dumps(item, ensure_ascii=False) + '\n')

    def _keep_photos(self, wheels):
        """Copia a fotografia de cada jante ensinada (em segundo plano: não atrasa o botão Guardar)."""
        if not self.photo: return
        def run():
            self.photos.mkdir(exist_ok=True)
            for w in wheels:
                if not w.get('imagem') or any(self.photos.glob(str(w['id']) + '.*')): continue
                try:
                    raw = self.photo(w['imagem'])
                    (self.photos / (str(w['id']) + ('.png' if raw[:4] == b'\x89PNG' else '.jpg'))).write_bytes(raw)
                except Exception: pass
        threading.Thread(target=run, daemon=True).start()


def for_service(service):
    """Uma instância por Central (criada na primeira utilização)."""
    teaching = service.__dict__.get('teaching')
    if teaching is None:
        teaching = service.__dict__.setdefault('teaching', Teaching(service.root, getattr(service.gestao, 'photo', None)))
    return teaching
