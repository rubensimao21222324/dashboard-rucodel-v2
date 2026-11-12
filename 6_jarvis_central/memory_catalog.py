"""Typed user memories in the existing SQLite database, with explicit writes.

No automatic extraction from conversations or model-generated facts. Metadata,
corrections and seed markers share the existing backup and transaction boundary.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import re
import sqlite3
import threading

from jarvis_memoria import MAX_FACTS, normalise, tokens

KINDS = {'fact': 'Facto', 'preference': 'Preferência', 'rule': 'Regra de trabalho'}
SEED_FLAG = 'memory_base_rucodel_v12'
# Small, reviewable transfer of this project's context, not the user's complete
# ChatGPT memory. No health, financial, family, account or credential data.
SEED = [
    ('empresa', 'fact', 'Rucodel', 'A Rucodel dedica-se à reparação de jantes, com atividade em Portugal e no Luxemburgo.'),
    ('setores', 'fact', 'Rucodel produção', 'Os setores da Rucodel incluem decapagem, reparação, pintura e CNC/diamantagem. O percurso varia com o trabalho.'),
    ('faturacao', 'fact', 'Rucodel software Excel', 'O software de faturação referido é o elaboraGestão e permite exportar Excel. Falta confirmar qual é o programa usado para acompanhar a produção.'),
    ('objetivo', 'fact', 'Jarvis planeamento Rucodel', 'O objetivo do Jarvis é ajudar no planeamento diário e ao longo do dia: prioridades das jantes, prazos, atrasos e risco de incumprimento.'),
    ('local', 'preference', 'Jarvis privacidade', 'O utilizador quer executar a inteligência no seu computador. As ligações ao Notion e à Google Agenda continuam a usar esses serviços externos.'),
    ('conversa', 'preference', 'Jarvis comunicação', 'Responder em português de Portugal, por tu, com clareza e concisão; pode usar meu rei. Evitar dirigir-se ao utilizador pelo nome.'),
    ('natural', 'preference', 'Jarvis organização', 'O utilizador prefere pedidos naturais e pouco trabalho manual. Fazer perguntas curtas apenas quando falta informação necessária.'),
    ('hardware', 'fact', 'Jarvis computador GPU memória', 'Equipamento comunicado em 31/10/2026: Ryzen 5 7600, 32 GB de RAM e NVIDIA RTX 4060 com 8 GB de VRAM.'),
    ('sem_compras', 'fact', 'Jarvis computador GPU', 'Até 31/10/2026 foram discutidas novas gráficas e motherboards; nenhuma compra foi confirmada nesta conversa.'),
    ('etapas', 'rule', 'produção carga viagem entrega horários', 'Ao calcular uma entrega, incluir todas as etapas indicadas: produção, carga, esperas e viagem. Respeitar se são consecutivas ou simultâneas.'),
    ('correcoes', 'rule', 'planeamento correção viagem carga horários', 'Quando muda apenas uma condição de um plano, conservar as restantes quantidades, durações, etapas e prazos, salvo indicação contrária.'),
    ('recursos', 'rule', 'Rucodel produção planeamento recursos', 'Ao propor um plano de produção, considerar ordem das operações, capacidade de máquinas e pessoas, lotes, esperas e prazos; pedir os dados que faltam.'),
    ('estado', 'rule', 'Rucodel produção atrasos prioridades', 'As prioridades devem usar o estado atualizado dos trabalhos e a data da última atualização. Distinguir atraso confirmado de risco de atraso.'),
    ('antecipacao', 'rule', 'Rucodel produção prioridades prazos', 'Considerar antecipar trabalhos demorados para evitar incumprimentos, explicando a prioridade e respeitando recursos e dependências.'),
]


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class MemoryCatalog:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.last_selection = []
        with closing(store.connect()) as con, con:
            con.execute('CREATE TABLE IF NOT EXISTS central_memory_meta(memory_id INTEGER PRIMARY KEY,kind TEXT NOT NULL,topic TEXT NOT NULL,source TEXT NOT NULL,valid_until TEXT NOT NULL,revision INTEGER NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS central_memory_revisions(id INTEGER PRIMARY KEY AUTOINCREMENT,memory_id INTEGER NOT NULL,payload TEXT NOT NULL,changed_at TEXT NOT NULL)')
            con.execute('CREATE INDEX IF NOT EXISTS central_memory_revision_lookup ON central_memory_revisions(memory_id,id)')
            con.execute('CREATE TABLE IF NOT EXISTS central_memory_seed(seed_key TEXT PRIMARY KEY,memory_id INTEGER)')
        if store.get_state(SEED_FLAG) == 'pending':
            self.install_seed()

    @staticmethod
    def rows(con):
        return [dict(row) for row in con.execute('''SELECT m.id,m.content,m.pinned,m.created_at,m.updated_at,
            COALESCE(k.kind,'fact') AS kind,COALESCE(k.topic,'') AS topic,
            COALESCE(k.source,'Memória anterior') AS source,COALESCE(k.valid_until,'') AS valid_until,
            COALESCE(k.revision,0) AS revision FROM memories m LEFT JOIN central_memory_meta k ON k.memory_id=m.id
            ORDER BY m.pinned DESC,m.updated_at DESC,m.id DESC''')]

    def list(self):
        with closing(self.store.connect()) as con:
            return self.rows(con)

    @staticmethod
    def active(row, today):
        return not row['valid_until'] or row['valid_until'] >= today.isoformat()

    @staticmethod
    def check_revision(row, expected):
        if expected is not None and (type(expected) is not int or expected != row['revision']):
            raise ValueError('Esta memória foi alterada entretanto. Atualiza a lista antes de guardar.')

    def save(self, content, *, fact_id=None, pinned=None, kind=None, topic=None,
             valid_until=None, source=None, expected_revision=None):
        content = self.store.validate(content)
        if fact_id is not None and (type(fact_id) is not int or fact_id < 1): raise ValueError('Número de memória inválido.')
        if pinned is not None and type(pinned) is not bool: raise ValueError('Estado de memória fixa inválido.')
        if kind is not None and kind not in KINDS: raise ValueError('Tipo de memória inválido.')
        for value, size in [(topic, 120), (source, 180)]:
            if value is not None and (not isinstance(value, str) or len(value) > size or '\x00' in value):
                raise ValueError('Tema ou origem da memória inválidos.')
        if valid_until is not None:
            if not isinstance(valid_until, str): raise ValueError('Validade inválida.')
            if valid_until and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', valid_until) or date.fromisoformat(valid_until).isoformat() != valid_until):
                raise ValueError('Usa uma data de validade AAAA-MM-DD ou deixa em branco.')
        with self.lock, closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            rows = self.rows(con)
            previous = next((row for row in rows if row['id'] == fact_id), None)
            if fact_id is not None and previous is None: raise ValueError('Essa memória já não existe.')
            if previous: self.check_revision(previous, expected_revision)
            duplicate = con.execute('SELECT id FROM memories WHERE normalised=?', (normalise(content),)).fetchone()
            if duplicate and (previous is None or duplicate['id'] != fact_id):
                if fact_id is not None: raise ValueError('Já existe outra memória com esse texto.')
                return next(row for row in rows if row['id'] == duplicate['id']), False
            if previous is None and len(rows) >= MAX_FACTS: raise ValueError('Limite de 5000 memórias. Revê as que já estão guardadas.')
            changed = stamp()
            if previous:
                con.execute('INSERT INTO central_memory_revisions(memory_id,payload,changed_at) VALUES(?,?,?)',
                    (fact_id, json.dumps(previous, ensure_ascii=False), changed))
                con.execute('DELETE FROM central_memory_revisions WHERE memory_id=? AND id NOT IN (SELECT id FROM central_memory_revisions WHERE memory_id=? ORDER BY id DESC LIMIT 20)', (fact_id, fact_id))
                pin = previous['pinned'] if pinned is None else int(pinned)
                con.execute('UPDATE memories SET content=?,normalised=?,pinned=?,updated_at=? WHERE id=?', (content, normalise(content), pin, changed, fact_id))
            else:
                pin = int(bool(pinned))
                fact_id = con.execute('INSERT INTO memories(content,normalised,pinned,created_at,updated_at) VALUES(?,?,?,?,?)', (content, normalise(content), pin, changed, changed)).lastrowid
            values = {key: value if value is not None else (previous[key] if previous else default)
                      for key, value, default in [('kind', kind, 'fact'), ('topic', topic, ''), ('source', source, 'Guardada pelo utilizador'), ('valid_until', valid_until, '')]}
            revision = previous['revision']+1 if previous else 1
            con.execute('INSERT INTO central_memory_meta VALUES(?,?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET kind=excluded.kind,topic=excluded.topic,source=excluded.source,valid_until=excluded.valid_until,revision=excluded.revision',
                        (fact_id, values['kind'], values['topic'].strip(), values['source'].strip(), values['valid_until'], revision))
            return next(row for row in self.rows(con) if row['id'] == fact_id), True

    def delete(self, fact_id, expected_revision=None):
        if type(fact_id) is not int or fact_id < 1: raise ValueError('Número de memória inválido.')
        with self.lock, closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            row = next((row for row in self.rows(con) if row['id'] == fact_id), None)
            if row is None: return False
            self.check_revision(row, expected_revision)
            con.execute('DELETE FROM central_memory_revisions WHERE memory_id=?', (fact_id,))
            con.execute('DELETE FROM central_memory_meta WHERE memory_id=?', (fact_id,))
            # Keep a seed tombstone so reinstalling never resurrects this memory.
            con.execute('UPDATE central_memory_seed SET memory_id=NULL WHERE memory_id=?', (fact_id,))
            return con.execute('DELETE FROM memories WHERE id=?', (fact_id,)).rowcount > 0

    def history(self, fact_id):
        with closing(self.store.connect()) as con:
            if not con.execute('SELECT 1 FROM memories WHERE id=?', (fact_id,)).fetchone(): raise ValueError('Essa memória já não existe.')
            return [dict(json.loads(row['payload']), changed_at=row['changed_at']) for row in con.execute('SELECT payload,changed_at FROM central_memory_revisions WHERE memory_id=? ORDER BY id DESC LIMIT 20', (fact_id,))]

    def search(self, query, today, limit=8):
        if not isinstance(query, str) or len(query) > 1500: raise ValueError('Pesquisa de memória demasiado longa.')
        terms = tokens(query)
        if not terms: return []
        def score(row):
            words = tokens(row['content']+' '+row['topic'])
            return sum(1 for q in terms if any(q == word or min(len(q), len(word)) >= 4 and (q.startswith(word) or word.startswith(q)) for word in words))
        matches = [(score(row), row) for row in self.list() if self.active(row, today)]
        return [row for value, row in sorted(matches, key=lambda pair:(pair[0], pair[1]['updated_at'], pair[1]['id']), reverse=True) if value > 0][:limit]

    def context(self, query, today, budget=1200):
        matches = self.search(query, today, limit=12)
        pinned = [row for row in self.list() if row['pinned'] and self.active(row, today)]
        preferences = [row for row in pinned if row['kind'] == 'preference'][:1]
        candidates = preferences+matches+pinned[:3]
        selected, seen, used = [], set(), 0
        for row in candidates:
            if row['id'] in seen: continue
            item = {'id': row['id'], 'tipo': KINDS[row['kind']], 'texto': row['content'], 'atualizada': row['updated_at'][:10]}
            if row['valid_until']: item['valida_ate'] = row['valid_until']
            size = len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
            if used+size > budget: continue
            selected.append(item);seen.add(row['id']);used += size
        with self.lock: self.last_selection = [row['id'] for row in selected]
        return {'total_guardadas': self.store.count(), 'selecao': selected,
                'selecao_parcial': len(selected) < len({row['id'] for row in candidates})}

    def lookup(self, query, today):
        rows = self.search(query, today, limit=4)
        with self.lock:
            self.last_selection = list(dict.fromkeys(self.last_selection+[row['id'] for row in rows]))[-24:]
        # Bounded full facts for follow-up retrieval; never invent missing facts.
        return {'memorias': [{key: row[key] for key in ['id','content','kind','topic','source','valid_until','updated_at']} for row in rows],
                'resposta': '\n'.join('#'+str(row['id'])+' · '+KINDS[row['kind']]+': '+row['content'] for row in rows) if rows else 'Não encontrei memórias válidas que correspondam à pesquisa.',
                'consulta_limitada': True}

    def info(self):
        rows = self.list()
        with self.lock: selection = list(self.last_selection)
        return {'kinds': KINDS, 'counts': {kind: sum(row['kind'] == kind for row in rows) for kind in KINDS},
                'last_selection': selection, 'writes': 'Só por pedido explícito ou edição no painel.'}

    def install_seed(self):
        # One atomic batch; edited or deleted seeds are never re-imported.
        with self.lock, closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            for key, kind, topic, text in SEED:
                if con.execute('SELECT 1 FROM central_memory_seed WHERE seed_key=?', (key,)).fetchone(): continue
                duplicate = con.execute('SELECT id FROM memories WHERE normalised=?', (normalise(text),)).fetchone()
                uid = duplicate['id'] if duplicate else None
                if uid is None and con.execute('SELECT COUNT(*) FROM memories').fetchone()[0] < MAX_FACTS:
                    changed = stamp()
                    uid = con.execute('INSERT INTO memories(content,normalised,pinned,created_at,updated_at) VALUES(?,?,?,?,?)', (text, normalise(text), int(key == 'conversa'), changed, changed)).lastrowid
                    source = 'Base preparada do projeto Jarvis · 31/10/2026'
                    con.execute('INSERT INTO central_memory_meta VALUES(?,?,?,?,?,1)', (uid, kind, topic, source, ''))
                con.execute('INSERT INTO central_memory_seed VALUES(?,?)', (key, uid))
            con.execute('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SEED_FLAG, 'installed'))

    def command(self, text, today):
        original = re.sub(r'^\s*jarvis(?:\s*[,!:]\s*|\s+)', '', text, flags=re.I).strip()
        patterns = [
            ('rule', r'^(?:guarda|memoriza|aprende)\s+(?:esta|uma|a)\s+regra\s*:\s*(.+)$'),
            ('preference', r'^(?:guarda|memoriza|aprende)\s+(?:esta|uma|a)\s+prefer[eê]ncia\s*:\s*(.+)$'),
            ('fact', r'^aprende\s+(?:isto\s*:\s*|que\s+)(.+)$'),
            ('fact', r'^guarda\s+isto(?:\s*[:,-]\s*|\s+)(.+)$'),
            ('fact', r'^guarda(?:\s+na\s+mem[oó]ria)?\s+que\s+(.+)$'),
            ('fact', r'^lembra[-\s]te\s+de\s+que\s+(.+)$'),
            ('fact', r'^memoriza\s*:\s*(.+)$'),
        ]
        for kind, pattern in patterns:
            match = re.fullmatch(pattern, original, re.I|re.S)
            if match:
                row, created = self.save(match.group(1), kind=kind)
                return ('Guardei a memória número ' if created else 'Essa informação já está guardada na memória número ')+str(row['id'])+': '+row['content']
        match = re.fullmatch(r'^(?:corrige|atualiza)\s+(?:a\s+)?(?:mem[oó]ria|regra|prefer[eê]ncia)\s+(?:n[uú]mero\s+|n[ºo]\s*)?#?(\d+)\s*:\s*(.+)$', original, re.I|re.S)
        if match:
            row, _ = self.save(match.group(2), fact_id=int(match.group(1)))
            return 'Corrigi a memória número '+str(row['id'])+': '+row['content']
        match = re.fullmatch(r'^(?:apaga|esquece|retira)\s+(?:a\s+)?(?:mem[oó]ria|regra|prefer[eê]ncia)\s+(?:n[uú]mero\s+|n[ºo]\s*)?#?(\d+)[.!]?$', original, re.I)
        if match:
            uid = int(match.group(1))
            return ('Retirei a memória número '+str(uid)+'.') if self.delete(uid) else ('Não existe uma memória com o número '+str(uid)+'.')
        query = normalise(original).rstrip(' .!?')
        if query in ['o que aprendeste', 'mostra as regras', 'que regras tens']:
            rows = self.list()
            if query != 'o que aprendeste': rows = [row for row in rows if row['kind'] == 'rule']
            return self.describe(rows[:20], len(rows))
        match = re.fullmatch(r'(?:o que (?:tens guardado|aprendeste)|que memorias tens)\s+sobre\s+(.+)', query)
        if match:
            rows = self.search(match.group(1), today, limit=20)
            return self.describe(rows, len(rows))
        return None

    @staticmethod
    def describe(rows, total):
        if not rows: return 'Não encontrei memórias para esta consulta. Podes guardar um facto, uma preferência ou uma regra no painel Memória.'
        return 'Memórias guardadas nesta consulta ('+str(total)+'):\n'+'\n'.join('#'+str(row['id'])+' · '+KINDS[row['kind']]+': '+row['content'] for row in rows)
