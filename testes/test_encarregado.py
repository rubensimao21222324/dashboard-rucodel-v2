# Testes do acesso de encarregado (ecrã dos setores). Correr: python testes\test_encarregado.py
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent/'backend'))
import json, http.client, threading, time, unittest, http.server, setores

class Accounts:
    data = {'setores': {'21': {'pin': setores.pin_hash('1234')}, '19': {'pin': setores.pin_hash('9999')}}}
    def load(self): return self.data
class FakeService:
    accounts = Accounts(); idle_minutes = 15; acts = []
    def secret(self): return b'x'*32
    def sectors(self): return [{'id': 21, 'nome': 'CNC', 'pin': True}, {'id': 19, 'nome': 'Torno', 'pin': True}]
    def list(self, s, c, f): return []
    def read_time(self, s): return '10:00:00'
    def check_sector(self, s): return str(int(s))
    def team(self, s): return ['Torres', 'Bruno'] if str(s) == '21' else []
    def totals(self, s=None): return {}
    def act(self, sector, action, chave, device='', worker=None, admin=False, boss=False):
        team = self.team(sector); worker = worker or None
        if worker and worker not in team and not (boss and worker == setores.ENCARREGADO_NOME): raise ValueError('Colaborador desconhecido neste setor.')
        if team and not worker and not admin and not boss: raise ValueError('Escolhe primeiro quem és.')
        self.acts.append((sector, worker)); return {'ok': 1}

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = setores.serve_sectors(FakeService(), port=0, host='127.0.0.1'); cls.port = cls.srv.server_address[1]
    def req(self, method, path, body=None, cookie=''):
        c = http.client.HTTPConnection('127.0.0.1', self.port)
        h = {'Host': 'localhost', 'Cookie': cookie}
        if body is not None: h.update({'Content-Type': 'application/json', 'X-Jarvis-Setor': '1'}); body = json.dumps(body)
        c.request(method, path, body, h); r = c.getresponse(); data = json.loads(r.read() or b'{}')
        return r.status, data, r.getheader('Set-Cookie') or ''
    def setUp(self): self.srv.RequestHandlerClass.attempts.clear()
    def boss_cookie(self):
        s, d, ck = self.req('POST', '/api/encarregado', {'pin': '5555'}); self.assertEqual(s, 200, d); return ck.split(';')[0]
    def test_senha_certa_da_acesso_a_todos_os_setores(self):
        ck = self.boss_cookie()
        for sec in ('21', '19'):
            s, d, _ = self.req('GET', '/api/servicos?setor=' + sec, cookie=ck); self.assertEqual(s, 200, d)
    def test_sem_cookie_pede_pin(self):
        s, d, _ = self.req('GET', '/api/servicos?setor=21'); self.assertEqual(s, 401)
    def test_senha_errada(self):
        s, d, _ = self.req('POST', '/api/encarregado', {'pin': '1111'}); self.assertEqual((s, d['erro']), (403, 'Senha incorreta.'))
    def test_bloqueio_apos_5_erros(self):
        for _ in range(5): self.req('POST', '/api/encarregado', {'pin': '0000'})
        s, d, _ = self.req('POST', '/api/encarregado', {'pin': '5555'}); self.assertEqual(s, 429)
    def test_cookie_falso_recusado(self):
        s, d, _ = self.req('GET', '/api/servicos?setor=21', cookie='encarregado=' + 'a'*64); self.assertEqual(s, 401)
    def test_acao_como_encarregado(self):
        ck = self.boss_cookie(); chave = 'a'*32
        s, d, _ = self.req('POST', '/api/acao', {'setor': 21, 'acao': 'mais', 'chave': chave, 'colaborador': 'Encarregado'}, cookie=ck); self.assertEqual(s, 200, d)
    def test_encarregado_sem_senha_nao_pode_agir(self):
        _, _, ck = self.req('POST', '/api/entrar', {'setor': 21, 'pin': '1234'}); ck = ck.split(';')[0]
        s, d, _ = self.req('POST', '/api/acao', {'setor': 21, 'acao': 'mais', 'chave': 'a'*32, 'colaborador': 'Encarregado'}, cookie=ck); self.assertEqual(s, 400, d)
    def test_sair_apaga_cookie(self):
        s, d, ck = self.req('POST', '/api/sair_encarregado', {}); self.assertIn('Max-Age=0', ck)
unittest.main(verbosity=2)
