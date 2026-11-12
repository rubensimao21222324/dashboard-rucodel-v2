"""Local performance log: timings and counts only, never message text or model reasoning.

One JSON object per line in desempenho.jsonl, rotated at 1 MB (one previous
file kept). Failures to write never affect the answer.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

ALLOWED = {'quando', 'rota', 'tipo', 'perfil', 'modelo', 'raciocinio', 'chamadas_modelo', 'ferramentas',
           'ms', 'tokens', 'primeira_palavra_ms', 'erro', 'ollama_reportou_tempos', 'contexto_reduzido'}
MS_KEYS = {'espera_modelo', 'carregamento', 'leitura_prompt', 'geracao', 'ferramentas', 'modelo_total', 'total'}


def percentile(values, share):
    if not values: return None
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int(round(share*(len(ordered)-1))))]


class PerformanceLog:
    def __init__(self, root, limit=1_000_000):
        self.path = Path(root)/'desempenho.jsonl'
        self.limit = limit
        self.lock = threading.Lock()

    @staticmethod
    def clean(entry):
        # Whitelist: anything not listed (text, titles, thinking) is dropped.
        row = {key: value for key, value in entry.items() if key in ALLOWED}
        row['ms'] = {key: (round(value) if isinstance(value, (int, float)) else None)
                     for key, value in (entry.get('ms') or {}).items() if key in MS_KEYS}
        row['ferramentas'] = [str(name)[:40] for name in entry.get('ferramentas') or []]
        if row.get('erro') is not None: row['erro'] = str(row['erro'])[:60]
        row['quando'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        return row

    def record(self, entry):
        row = self.clean(entry)
        try:
            with self.lock:
                if self.path.exists() and self.path.stat().st_size > self.limit:
                    self.path.replace(self.path.with_name('desempenho.1.jsonl'))
                with self.path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(row, ensure_ascii=False)+'\n')
        except OSError:
            pass
        return row

    def summary(self, last=200):
        try:
            lines = self.path.read_text(encoding='utf-8').splitlines()[-last:]
        except OSError:
            lines = []
        rows = []
        for line in lines:
            try: rows.append(json.loads(line))
            except ValueError: continue
        groups = {}
        for row in rows: groups.setdefault(row.get('rota', '?'), []).append(row)
        result = {}
        for route, items in groups.items():
            totals = [r['ms']['total'] for r in items if r.get('ms', {}).get('total') is not None]
            result[route] = {'pedidos': len(items), 'total_ms_p50': percentile(totals, .5), 'total_ms_p95': percentile(totals, .95),
                             'erros': sum(1 for r in items if r.get('erro'))}
        return {'registos': len(rows), 'por_rota': result,
                'nota': 'Tempo total até à resposta completa; sem streaming, não há tempo até à primeira palavra.'}
