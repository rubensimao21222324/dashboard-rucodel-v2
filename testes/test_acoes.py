# Testes das «Ações a corrigir» (criar, editar, marcar feita, apagar). Correr: python testes\test_acoes.py
import sys, pathlib, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
from acoes import CorrectiveActions

class T(unittest.TestCase):
    def setUp(self): self.dir = tempfile.TemporaryDirectory(); self.a = CorrectiveActions(self.dir.name)
    def tearDown(self): self.dir.cleanup()
    def criar(self, texto): return self.a.handle({'acao': 'criar', 'texto': texto})['acoes'][0]
    def test_lista_vazia(self): self.assertEqual(self.a.handle(), {'acoes': []})
    def test_criar_mais_recente_primeiro(self):
        self.criar('Arrumar o torno'); x = self.criar('  Trocar lâmpada da pintura  ')
        self.assertEqual(x['texto'], 'Trocar lâmpada da pintura'); self.assertFalse(x['feita'])
        self.assertEqual([i['texto'] for i in self.a.handle()['acoes']], ['Trocar lâmpada da pintura', 'Arrumar o torno'])
    def test_vazio_recusado(self):
        with self.assertRaises(ValueError): self.a.handle({'acao': 'criar', 'texto': '   '})
    def test_editar(self):
        x = self.criar('A'); self.a.handle({'acao': 'editar', 'id': x['id'], 'texto': 'B'})
        self.assertEqual(self.a.handle()['acoes'][0]['texto'], 'B')
    def test_feita_e_desfazer(self):
        x = self.criar('C'); r = self.a.handle({'acao': 'feita', 'id': x['id'], 'feita': True})['acoes'][0]
        self.assertTrue(r['feita']); self.assertTrue(r['feita_em'])
        r = self.a.handle({'acao': 'feita', 'id': x['id'], 'feita': False})['acoes'][0]
        self.assertFalse(r['feita']); self.assertEqual(r['feita_em'], '')
    def test_apagar_e_inexistente(self):
        x = self.criar('D'); self.a.handle({'acao': 'apagar', 'id': x['id']}); self.assertEqual(self.a.handle()['acoes'], [])
        with self.assertRaises(ValueError): self.a.handle({'acao': 'apagar', 'id': 'nada'})
    def test_persiste_no_disco(self):
        self.criar('E'); self.assertEqual(CorrectiveActions(self.dir.name).handle()['acoes'][0]['texto'], 'E')
unittest.main(verbosity=1)
