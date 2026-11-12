# Testes do modo ensinar. Correr: python testes\test_ensino.py
import sys, pathlib, tempfile, unittest, json, time
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
from ensino import Teaching, DEFAULT_OPS

W = {'id': '12345', 'cliente': '2891 · MYCARCENTER', 'quantidade': 4, 'tamanho': '19', 'tipo': '447 Maquinada', 'cor': 'Preto', 'imagem': '/img/cache/a.jpg', 'lixo': 'x'}

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.d.name)
        self.t = Teaching(self.root, photo=lambda p: b'\xff\xd8jpeg', clock=lambda: datetime(2026, 11, 4, 9, 0))
    def tearDown(self): self.d.cleanup()
    def test_lista_inicial(self):
        s = self.t.state(); self.assertEqual(s['operacoes'], DEFAULT_OPS); self.assertEqual(s['total'], 0)
    def test_guardar_por_ordem_com_tempos(self):
        s = self.t.act({'acao': 'guardar', 'jantes': [W], 'nota': 'fissura 5 cm', 'operacoes': [{'op': 'Soldar', 'min': 45}, {'op': 'Torno', 'min': 30}]})
        self.assertEqual(s['total'], 1); self.assertEqual([o['op'] for o in s['ensinadas']['12345']['operacoes']], ['Soldar', 'Torno'])
        full = json.loads((self.root/'ensino.json').read_text(encoding='utf-8'))['jantes']['12345']
        self.assertEqual(full['total_min'], 75); self.assertNotIn('lixo', full); self.assertEqual(full['nota'], 'fissura 5 cm')
        self.assertEqual(len((self.root/'ensino_historico.jsonl').read_text(encoding='utf-8').splitlines()), 1)
        time.sleep(0.2); self.assertTrue((self.root/'ensino_fotos'/'12345.jpg').exists())
    def test_corrigir_substitui(self):
        self.t.act({'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Torno', 'min': 30}]})
        s = self.t.act({'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Pintura', 'min': 60}]})
        self.assertEqual(s['total'], 1); self.assertEqual(s['ensinadas']['12345']['operacoes'][0]['op'], 'Pintura')
    def test_nova_operacao_sem_duplicar(self):
        self.t.act({'acao': 'operacao', 'nome': '  Verniz '}); s = self.t.act({'acao': 'operacao', 'nome': 'verniz'})
        self.assertEqual(s['operacoes'].count('Verniz'), 1)
        s = self.t.act({'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Verniz', 'min': 20}]}); self.assertEqual(s['total'], 1)
    def test_recusas(self):
        for body in ({'acao': 'guardar', 'jantes': [W], 'operacoes': []},
                     {'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Inventada', 'min': 5}]},
                     {'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Torno', 'min': -1}]},
                     {'acao': 'guardar', 'jantes': [{'id': '../x'}], 'operacoes': [{'op': 'Torno', 'min': 5}]},
                     {'acao': 'operacao', 'nome': '   '}, {'acao': 'xpto'}):
            with self.assertRaises(ValueError): self.t.act(body)
        self.assertEqual(self.t.state()['total'], 0)
    def test_apagar(self):
        self.t.act({'acao': 'guardar', 'jantes': [W], 'operacoes': [{'op': 'Torno', 'min': 30}]})
        self.assertEqual(self.t.act({'acao': 'apagar', 'id': '12345'})['total'], 0)
unittest.main(verbosity=1)
