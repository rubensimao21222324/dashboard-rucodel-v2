# Alertas da produção (jantes que já deviam ter passado o torno). Correr: python testes\test_alertas.py
import sys, pathlib, tempfile, json, unittest
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
from alertas import compute, due_notifications, ProductionAlerts

def item(i, prazo, setor=1, grupo='Maquinada', q=4):
    return {'id': i, 'cliente': '400 · CLIENTE', 'quantidade': q, 'tamanho': '20', 'tipo': 't', 'cor': 'c', 'grupo': grupo, 'prazo': prazo, 'estado': 'A aguardar', 'setor': setor, 'imagem': ''}
DATA = {'atras': {'zonas': [{'nome': 'MV-Minho', 'lista': [item('a', '2026-11-03'), item('b', '2026-11-03', setor=2)]}]},
        'dias': [{'zonas': [{'nome': 'P', 'lista': [item('c', '2026-11-04'), item('d', '2026-11-04', grupo='Outro'), item('e', '2026-11-04', setor=2), item('f', '2026-11-05'), item('a', '2026-11-03')]}]}]}

class T(unittest.TestCase):
    def test_antes_das_15_so_atrasadas(self):
        r = compute(DATA, datetime(2026, 11, 4, 10, 0))
        self.assertEqual([e['id'] for e in r['vermelho']], ['a']); self.assertEqual(r['laranja'], [])
    def test_15h_laranja_16h_vermelho(self):
        self.assertEqual([e['id'] for e in compute(DATA, datetime(2026, 11, 4, 15, 5))['laranja']], ['c'])
        r = compute(DATA, datetime(2026, 11, 4, 16, 5)); self.assertEqual([e['id'] for e in r['vermelho']], ['a', 'c']); self.assertEqual(r['jantes'], 8)
    def test_amanha_nunca_entra(self):
        r = compute(DATA, datetime(2026, 11, 4, 21, 0)); self.assertNotIn('f', [e['id'] for e in r['vermelho'] + r['laranja']])
    def test_notificacao_uma_vez(self):
        state = {}
        first = due_notifications(DATA, state, datetime(2026, 11, 4, 15, 10))
        self.assertEqual([x[0] for x in first], ['torno15']); self.assertIn('400 P 4x20"', first[0][2]); self.assertIn('fora de prazo', first[0][2])
        self.assertEqual(due_notifications(DATA, state, datetime(2026, 11, 4, 15, 40)), [])
        self.assertEqual([x[0] for x in due_notifications(DATA, state, datetime(2026, 11, 4, 16, 2))], ['cnc16'])
    def test_envia_pelo_ntfy(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d); (p/'producao.json').write_text(json.dumps(DATA)); (p/'vigilante_config.json').write_text('{"ntfy_topico": "t"}')
            sent = []; ProductionAlerts(d).notify(datetime(2026, 11, 4, 15, 1), send=lambda *a: sent.append(a))
            self.assertEqual(len(sent), 1); self.assertTrue(sent[0][2].startswith('⚠ 4 jantes de hoje'))
            ProductionAlerts(d).notify(datetime(2026, 11, 4, 15, 20), send=lambda *a: sent.append(a)); self.assertEqual(len(sent), 1)
unittest.main(verbosity=1)
