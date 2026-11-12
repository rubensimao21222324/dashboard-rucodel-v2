# Testes do botão ⓘ (por onde já passou a jante). Correr: python testes\test_percurso.py
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
import setores

K = 'a'*32
class Api:
    def departments(self): return [{'id': 19, 'nome': 'Torno'}, {'id': 20, 'nome': 'Pó'}, {'id': 22, 'nome': 'Pintura'}, {'id': 21, 'nome': 'cnc'}]
    def services(self, sector):
        return {'servicos': []}
class Acc:
    def load(self): return {'setores': {'19': {}, '20': {}, '22': {}, '21': {}}}

def svc(rows_by_sector):
    s = setores.SectorService.__new__(setores.SectorService)
    s.api = Api(); s.accounts = Acc(); s.cache = {k: {'t': 0, 'rows': v} for k, v in rows_by_sector.items()}
    s.check_sector = lambda x: str(int(x))
    return s

class T(unittest.TestCase):
    def test_rota_completa(self):
        row = {'chave': K, 'quantidade': 3, 'contador': 0, 'estado': 'play',
               'rota': [{'id': 19, 'estado': 'ok', 'contador': None}, {'id': 20, 'estado': 'stop', 'contador': None}, {'id': 21, 'estado': 'play', 'contador': None}]}
        pod = {'chave': K, 'quantidade': 3, 'contador': 2, 'estado': 'stop'}
        d = svc({'21': [row], '20': [pod]}).route('21', K)
        self.assertTrue(d['completo'])
        self.assertEqual([(p['nome'], p['estado'], p['contador'], p['este']) for p in d['percurso']],
                         [('Torno', 'ok', None, False), ('Pó', 'stop', 2, False), ('CNC', 'play', 0, True)])
    def test_leitura_antiga_sem_rota(self):
        row = {'chave': K, 'quantidade': 4, 'contador': 1, 'estado': 'play'}
        tor = {'chave': K, 'quantidade': 4, 'contador': 4, 'estado': 'stop'}
        d = svc({'21': [row], '19': [tor]}).route('21', K)
        self.assertFalse(d['completo']); self.assertEqual([p['nome'] for p in d['percurso']], ['Torno', 'CNC'])
    def test_servico_que_ja_saiu(self):
        with self.assertRaises(ValueError): svc({'21': []}).route('21', K)
    def test_chave_invalida(self):
        with self.assertRaises(ValueError): svc({'21': []}).route('21', '../x')
    def test_leitura_guarda_rota(self):
        api = setores.DashboardAPI.__new__(setores.DashboardAPI)
        api.request = lambda *a, **k: {'servicos': [{'chave': K, 'cliente': '2891', 'quantidade': 3, 'contador': 0,
            'departamentos': [{'departamento_id': 19, 'id': 5, 'estado': 'ok'}, {'departamento_id': 21, 'id': 7, 'estado': 'play'}]}]}
        r = api.services(21)[0]
        self.assertEqual((r['tarefa'], r['estado']), (7, 'play'))
        self.assertEqual(r['rota'], [{'id': 19, 'estado': 'ok', 'contador': None}, {'id': 21, 'estado': 'play', 'contador': None}])
unittest.main(verbosity=1)
