# Proteção LEITURA / ESCRITA da instância DEV. Correr: python testes\test_modo_escrita.py
import io, json, sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
import modo_escrita
from setores import DashboardAPI

class Contas:
    def load(self): return {'setores': {'21': {'nome': 'CNC', 'login': 'x', 'password': 'y'}}}

class Resposta(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

class T(unittest.TestCase):
    def setUp(self):
        self.pedidos = []
        def opener(req, timeout=0):
            self.pedidos.append((req.get_method(), req.full_url))
            return Resposta(json.dumps({'token': 't', 'servicos': []}).encode())
        self.api = DashboardAPI(Contas(), opener=opener)
        modo_escrita.definir('leitura')
    def tearDown(self): modo_escrita.definir('leitura')
    def escritas(self): return [u for _, u in self.pedidos if 'counter' in u or '-start/' in u or '-stop/' in u]

    def test_arranca_em_leitura(self):
        self.assertEqual(modo_escrita.modo(), 'leitura')
    def test_leitura_deixa_ler(self):
        self.api.services(21); self.api.images(21, ['a'*32])
        self.assertTrue(any('/auth/departamento/21' in u for _, u in self.pedidos))
    def test_leitura_bloqueia_contador_iniciar_terminar(self):
        for chamada in (lambda: self.api.set_counter(21, 'a'*32, 3), lambda: self.api.start(21, 5), lambda: self.api.stop(21, 5)):
            with self.assertRaises(modo_escrita.ModoLeitura): chamada()
        self.assertEqual(self.escritas(), [])
        self.assertEqual(self.pedidos, [])  # nem sequer faz login: nada sai do PC
    def test_leitura_bloqueia_caminho_desconhecido(self):
        with self.assertRaises(modo_escrita.ModoLeitura): self.api.request('/auth/outra-coisa/1', 21)
    def test_escrita_deixa_passar(self):
        modo_escrita.definir('escrita')
        self.api.set_counter(21, 'a'*32, 3); self.api.start(21, 5); self.api.stop(21, 5)
        self.assertEqual(len(self.escritas()), 3)
    def test_voltar_a_leitura_bloqueia_outra_vez(self):
        modo_escrita.definir('escrita'); modo_escrita.definir('leitura')
        with self.assertRaises(modo_escrita.ModoLeitura): self.api.set_counter(21, 'a'*32, 1)
    def test_modo_invalido(self):
        with self.assertRaises(ValueError): modo_escrita.definir('tudo')
        self.assertEqual(modo_escrita.modo(), 'leitura')
    def test_mensagem_chega_ao_ecra(self):
        self.assertTrue(issubclass(modo_escrita.ModoLeitura, ValueError))  # a Central devolve a mensagem (400)
unittest.main(verbosity=1)
