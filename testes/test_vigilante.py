# Testes do vigilante. Correr: python testes\test_vigilante.py
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import vigilante as v
REAL_DUE = v.backup_due

class T(unittest.TestCase):
    def setUp(self):
        self.sent = []; self.started = 0; self.up = {'central': True, 'ollama': True, 'ts': True}; self.busy = False
        v.notify = lambda cfg, t, m, urgent=False: self.sent.append(t)
        v.log = lambda *a: None; v.write_state = lambda c: None; v.remote_hosts = lambda: ['x.ts.net']
        v.port_busy = lambda p: self.busy
        v.backup_due = lambda now=None: False
        def ok(url, timeout=5):
            if '12396' in url: return self.up['central']
            if '11434' in url: return self.up['ollama']
            return self.up['ts']
        v.http_ok = ok
        def start(): self.started += 1; self.up['central'] = True; return True
        v.start_central = start
        self.c = {n: v.Check(n) for n in ('central', 'ollama', 'tailscale')}
    def run_once(self, n=1):
        for _ in range(n): v.once(self.c, {})
    def test_tudo_bem_sem_avisos(self):
        self.run_once(5); self.assertEqual((self.sent, self.started), ([], 0))
    def test_central_cai_e_e_reiniciada_a_segunda_falha(self):
        self.up['central'] = False; self.run_once(1); self.assertEqual(self.started, 0)
        self.run_once(1); self.assertEqual(self.started, 1); self.assertEqual(self.sent, ['Jarvis reiniciado'])
    def test_central_bloqueada_nao_mexe_e_avisa_uma_vez(self):
        self.up['central'] = False; self.busy = True; self.run_once(6)
        self.assertEqual(self.started, 0); self.assertEqual(self.sent, ['Jarvis: problema'])
    def test_tailscale_cai_e_volta(self):
        self.up['ts'] = False; self.run_once(1); self.assertEqual(self.sent, [])
        self.run_once(3); self.assertEqual(self.sent, ['Jarvis: problema'])
        self.up['ts'] = True; self.run_once(2); self.assertEqual(self.sent, ['Jarvis: problema', 'Jarvis: resolvido'])
    def test_falha_isolada_nao_avisa(self):
        self.up['ollama'] = False; self.run_once(1); self.up['ollama'] = True; self.run_once(3); self.assertEqual(self.sent, [])

import tempfile, sqlite3, zipfile
from datetime import datetime
from pathlib import Path
class Copias(unittest.TestCase):
    def test_copia_diaria(self):
        v.backup_due = REAL_DUE
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); dest = d/'Jarvis_Central_Pro'; proj = d/'Jarvis'
            (dest/'backend').mkdir(parents=True); (dest/'.venv').mkdir(); (dest/'fotos_setores').mkdir(); (proj/'jarvis_data').mkdir(parents=True)
            (dest/'backend'/'central.py').write_text('x'); (dest/'notas_producao.json').write_text('{}'); (dest/'.venv'/'grande.bin').write_text('y'); (dest/'fotos_setores'/'a.jpg').write_text('z')
            with sqlite3.connect(proj/'jarvis_data'/'memoria.sqlite3') as c: c.execute('create table tasks(title)'); c.execute("insert into tasks values('Falar com X')")
            v.DEST, v.PROJECT, v.BACKUPS = dest, proj, dest/'copias_seguranca'
            for i in range(16): (v.BACKUPS).mkdir(exist_ok=True); (v.BACKUPS/('jarvis_2026-01-%02d.zip' % (i+1))).write_text('')
            path = v.make_backup({})
            names = zipfile.ZipFile(path).namelist()
            self.assertIn('Jarvis_Central_Pro/backend/central.py', names); self.assertIn('Jarvis_Central_Pro/notas_producao.json', names)
            self.assertIn('bases/memoria.sqlite3', names)
            self.assertFalse(any('.venv' in n or 'fotos_setores' in n for n in names))
            self.assertEqual(len(list(v.BACKUPS.glob('jarvis_*.zip'))), 14)
            self.assertFalse(v.backup_due(datetime.now().replace(hour=4)))
            self.assertFalse(v.backup_due(datetime.now().replace(hour=2)))
            raw = zipfile.ZipFile(path).read('bases/memoria.sqlite3'); (d/'r.db').write_bytes(raw)
            with sqlite3.connect(d/'r.db') as c: self.assertEqual(c.execute('select title from tasks').fetchone()[0], 'Falar com X')
unittest.main(verbosity=1)
