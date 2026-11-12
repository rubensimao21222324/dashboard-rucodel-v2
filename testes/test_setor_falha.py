# Setor de um serviço quando a janela «Gerir Tarefas» falha a leitura. Correr: python testes\test_setor_falha.py
import sys, pathlib, threading, unittest
from datetime import datetime, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
import gestao_cache
from gestao_cache import CachedGestao, SiteCache
from gestao_rucodel import GestaoRucodel

class FakeCache(SiteCache):
    def __init__(self): self.lock = threading.Lock(); self.data = {'setores': {}}; self.settings = {'gestao_intervalo_min': 10}

class T(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache(); self.g = CachedGestao.__new__(CachedGestao); self.g.cache = self.cache
        self.g.login_lock = threading.Lock(); self.g.ensure_login = lambda: None; self.g.login = lambda: None
        self.answers = []; self.orig = GestaoRucodel.sectors
        GestaoRucodel.sectors = lambda _self, rows: self.answers.pop(0)(rows)
    def tearDown(self): GestaoRucodel.sectors = self.orig
    def rows(self, *ids): return [{'id': i} for i in ids]
    def test_tenta_outra_vez(self):
        self.answers = [lambda r: {'a': 1, 'b': 2, 'c': None}, lambda r: {'c': 1}]
        self.assertEqual(self.g.sectors(self.rows('a', 'b', 'c')), {'a': 1, 'b': 2, 'c': 1})
    def test_usa_ultimo_setor_conhecido(self):
        old = (datetime.now()-timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        self.cache.data['setores'] = {'c': [1, old]}
        self.answers = [lambda r: {'a': 2, 'b': 2, 'c': None}, lambda r: {'c': None}]
        self.assertEqual(self.g.sectors(self.rows('a', 'b', 'c')), {'a': 2, 'b': 2, 'c': 1})
        self.assertEqual(self.cache.data['setores']['c'][1], old)  # não fica a parecer leitura nova
    def test_sem_nada_marcado_fica_antes_do_torno(self):
        self.answers = [lambda r: {'a': 2, 'b': 2, 'c': None}, lambda r: {'c': None}]
        self.assertEqual(self.g.sectors(self.rows('a', 'b', 'c'))['c'], 1)
        self.assertNotIn('c', self.cache.data['setores'])  # a regra não é guardada como leitura
    def test_contagem_nunca_sem_info(self):
        from gestao_rucodel import sector_counts, sector
        rows = [{'id': 'a', 'quantidade': 4}, {'id': 'b', 'quantidade': 2}, {'id': 'c', 'quantidade': 1}]
        self.assertEqual(sector_counts(rows, {'a': None, 'b': 2}), {'setor1': 5, 'setor2': 2, 'sem_info': 0})
        self.assertEqual(sector([('Torno', 'amarelo'), ('Pintura', 'amarelo')]), 1)
        self.assertEqual(sector([('Torno', 'verde'), ('Pintura', 'amarelo')]), 2)
unittest.main(verbosity=1)
