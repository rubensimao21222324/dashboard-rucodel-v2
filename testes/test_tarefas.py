# Testes das tarefas importantes (acrescentar, editar, concluir, apagar). Correr: python testes\test_tarefas.py
import sys, pathlib, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
from jarvis_tools import Tools

class T(unittest.TestCase):
    def setUp(self): self.dir = tempfile.TemporaryDirectory(); self.t = Tools(self.dir.name)
    def tearDown(self): self.dir.cleanup()
    def add(self, title): return [x for x in self.t.action({'action': 'task_add', 'title': title})['tasks'] if x['title'] == title][0]
    def test_editar(self):
        x = self.add('Falar com X'); r = self.t.action({'action': 'task_edit', 'id': x['id'], 'title': '  Falar com X e Y  '})
        self.assertEqual(r['tasks'][0]['title'], 'Falar com X e Y')
    def test_editar_vazio_recusado(self):
        x = self.add('A')
        with self.assertRaises(ValueError): self.t.action({'action': 'task_edit', 'id': x['id'], 'title': '   '})
        self.assertEqual(self.t.tasks()[0]['title'], 'A')
    def test_editar_inexistente(self):
        with self.assertRaises(ValueError): self.t.action({'action': 'task_edit', 'id': 999, 'title': 'B'})
    def test_concluir_e_apagar_continuam(self):
        x = self.add('C'); self.t.action({'action': 'task_done', 'id': x['id'], 'done': True}); self.assertEqual(self.t.tasks()[0]['done'], 1)
        self.t.action({'action': 'task_delete', 'id': x['id']}); self.assertEqual(self.t.tasks(), [])
unittest.main(verbosity=1)
