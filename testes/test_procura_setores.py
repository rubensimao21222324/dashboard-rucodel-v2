# Pesquisa por cliente num setor: jantes do cliente que estão noutros setores. Correr: python testes\test_procura_setores.py
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
from setores import SectorService

def row(chave, cliente, contador=0, prazo='2026-11-04'):
    return {'chave': chave, 'cliente': cliente, 'tipo': 'Só Desempenar / Soldar', 'cor': '', 'tamanho': '16', 'quantidade': 1,
            'contador': contador, 'prazo': prazo, 'estado': 'play', 'descricao': ''}

class T(unittest.TestCase):
    def setUp(self):
        self.s = SectorService.__new__(SectorService)
        self.s.sectors = lambda: [{'id': 27, 'nome': 'Torno'}, {'id': 32, 'nome': 'Pó'}, {'id': 40, 'nome': 'Desempeno'}]
        self.s.cache = {'27': {'rows': [row('a', '126')]}, '32': {'rows': [row('a', '126'), row('b', '126', 1)]},
                        '40': {'rows': [row('b', '126'), row('c', '126'), row('d', '999')]}}
    def test_so_o_que_nao_esta_aqui_uma_vez(self):
        out = self.s.elsewhere('27', '126')
        self.assertEqual([r['chave'] for r in out], ['b', 'c'])
        self.assertEqual([x['nome'] for x in out[0]['setores']], ['Pó', 'Desempeno'])
        self.assertEqual(out[0]['setores'][0]['contador'], 1)
    def test_outro_cliente_e_vazio(self):
        self.assertEqual(self.s.elsewhere('27', '555'), []); self.assertEqual(self.s.elsewhere('27', ''), [])
unittest.main(verbosity=1)
