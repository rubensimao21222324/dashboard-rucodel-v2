# Testes da aba «Para trás» do ecrã de produção. Correr: python testes\test_para_tras.py
import sys, pathlib, unittest
from datetime import date, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
import gestao_rucodel as g

def row(i, prazo, tipo='Maquinada', q=4):
    return {'id': i, 'prazo': prazo + ' 18:00', 'tipo': tipo, 'quantidade': q, 'cliente': 'C', 'cliente_numero': str(i), 'tamanho': '19', 'cor': 'Preto',
            'criado': '2026-10-20 10:00', 'imagem': '', 'gerir': ''}

class Fake(g.GestaoRucodel):
    def __init__(self, zones): self.zones = zones
    def by_zone(self): return self.zones
    def sectors(self, rows): return {r['id']: 1 for r in rows}

class T(unittest.TestCase):
    def test_para_tras(self):
        zones = [{'zona': '13', 'nome': 'Aveiro', 'estados': {
            'aguardar': [row(1, '2026-11-02'), row(2, '2026-11-04'), row(3, '2026-11-03', 'Pintada', 2)],
            'curso': [row(4, '2026-10-30')],
            'terminado': [row(5, '2026-11-01')]}}]
        data = Fake(zones).production_overview(date(2026, 11, 4), datetime(2026, 11, 3, 23, 0))
        a = data['atras']
        self.assertTrue(a['atras'])
        self.assertEqual(sorted(i['id'] for z in a['zonas'] for i in z['lista']), [1, 3, 4])   # o terminado (5) e o de amanhã (2) ficam de fora
        self.assertEqual((a['total'], a['maquinadas'], a['pintadas']), (10, 8, 2))
        self.assertEqual(a['setor1'], 10)
        self.assertIn('prazo', a['zonas'][0]['lista'][0])
        self.assertEqual([d['dia'] for d in data['dias']], ['2026-11-04', '2026-11-05'])   # o resto não mudou
    def test_nada_atrasado(self):
        data = Fake([{'zona': '1', 'nome': 'Z', 'estados': {'aguardar': [row(1, '2026-11-05')], 'curso': [], 'terminado': []}}]).production_overview(date(2026, 11, 4))
        self.assertEqual((data['atras']['total'], data['atras']['zonas']), (0, []))
unittest.main(verbosity=1)
