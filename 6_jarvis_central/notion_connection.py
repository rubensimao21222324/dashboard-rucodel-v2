"""Notion diary connector. Credentials stay in a Windows DPAPI protected file."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INDEX = '4033eeaf-07f5-80dd-81f6-cba201fd8327'
SOURCE = '1409b278-a32a-480e-8d9d-40649ba69c4c'
VERSION = '2025-09-03'

def today_lisbon():
    try:
        return datetime.now(ZoneInfo('Europe/Lisbon')).date()
    except ZoneInfoNotFoundError:
        # Windows may not ship IANA data. EU DST changes at 01:00 UTC.
        from datetime import timezone
        now = datetime.now(timezone.utc)
        def change(month):
            last = date(now.year, month, 31)
            return datetime(now.year, month, 31 - (last.weekday() + 1) % 7, 1, tzinfo=timezone.utc)
        return (now + timedelta(hours=int(change(3) <= now < change(10)))).date()


def protect_bytes(value, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('A ligação com credenciais deve ser configurada no teu Windows.')
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    incoming = Blob(len(value), buffer)
    outgoing = Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(incoming), 'Jarvis Notion', None, None, None, 1, ctypes.byref(outgoing))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise RuntimeError('O Windows não conseguiu proteger/abrir a credencial. Usa o mesmo utilizador Windows.')
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


class NotionConnection:
    def __init__(self, root):
        self.file = Path(root) / 'notion_credential.dpapi'
        self.lock = threading.RLock()
        self.rate_lock = threading.Lock()
        self.last_request = 0.0

    def status(self):
        return {'configured': self.file.is_file(), 'destination': 'Índice → Diário → Registos do diário',
                'calendar_connected': False}

    def token(self):
        if not self.file.is_file():
            raise ValueError('Liga primeiro o Notion nas Definições → Ligar Notion.')
        return protect_bytes(self.file.read_bytes(), decrypt=True).decode('utf-8')

    def request(self, method, path, body=None, token=None):
        credential = token if token is not None else self.token()
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request('https://api.notion.com/v1/' + path, data=data, method=method,
              headers={'Authorization': 'Bearer ' + credential, 'Notion-Version': VERSION,
                       'Content-Type': 'application/json'})
        # Keep a single local connection below Notion's average request limit.
        with self.rate_lock:
            delay = .36 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            messages = {401: 'Token do Notion inválido ou revogado.',
                        403: 'A conexão não tem as permissões necessárias no Notion.',
                        404: 'Não encontrei o Índice ou o Diário. Confirma o acesso a conteúdo da conexão.',
                        429: 'O Notion está a limitar pedidos. Aguarda um pouco antes de tentar de novo.'}
            raise RuntimeError(messages.get(error.code, 'O Notion recusou o pedido (HTTP ' + str(error.code) + ').')) from None
        except (OSError, ValueError):
            if method in ('PATCH', 'POST') and path != 'search' and not path.endswith('/query'):
                raise RuntimeError('A ligação ao Notion foi interrompida. A escrita pode ter sido recebida: verifica o Diário antes de repetir.') from None
            raise RuntimeError('Não consegui consultar o Notion. Verifica a internet e tenta novamente.') from None

    def verify(self, token=None):
        self.request('GET', 'pages/' + INDEX, token=token)
        source = self.request('GET', 'data_sources/' + SOURCE, token=token)
        fields = source.get('properties', {})
        if fields.get('Dia', {}).get('type') != 'title' or fields.get('Data', {}).get('type') != 'date':
            raise ValueError('O Diário mudou: preciso dos campos Dia (título) e Data (data). Nenhuma estrutura foi alterada.')
        self.request('POST', 'data_sources/' + SOURCE + '/query', {'page_size': 1}, token=token)
        return {'ok': True, **self.status(), 'verified': True}

    def configure(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_\-]{20,300}', token.strip()):
            raise ValueError('Cola apenas o token de API do Notion, sem espaços nem aspas.')
        token = token.strip()
        with self.lock:
            self.verify(token)
            encrypted = protect_bytes(token.encode())
            temporary = self.file.with_suffix('.tmp')
            temporary.write_bytes(encrypted)
            os.replace(temporary, self.file)
            return {'ok': True, **self.status(), 'verified': True}

    def disconnect(self):
        with self.lock:
            self.file.unlink(missing_ok=True)
        return {'ok': True, **self.status()}

    @staticmethod
    def rich(text):
        return [{'type': 'text', 'text': {'content': text}}]

    def create_task(self, title, day):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 1500:
            raise ValueError('Escreve uma tarefa com 1 a 1500 caracteres.')
        day = date.fromisoformat(day).isoformat()
        title = title.strip()
        child = {'object': 'block', 'type': 'to_do', 'to_do': {'rich_text': self.rich(title), 'checked': False}}
        with self.lock:
            rows = self.request('POST', 'data_sources/' + SOURCE + '/query',
                       {'filter': {'property': 'Data', 'date': {'equals': day}}, 'page_size': 2})
            if len(rows.get('results', [])) > 1 or rows.get('has_more'):
                raise ValueError('Há vários registos do Diário para esse dia. Resolve a duplicação no Notion antes de adicionar a tarefa.')
            if rows.get('results'):
                page = rows['results'][0]
                # Natural requests may be repeated after a slow response. Check
                # existing direct tasks while holding the same write lock.
                cursor = None
                wanted = ' '.join(title.casefold().split())
                for _ in range(5):
                    path = 'blocks/' + page['id'] + '/children?page_size=100'
                    if cursor: path += '&start_cursor=' + quote(cursor, safe='')
                    existing = self.request('GET', path)
                    for block in existing.get('results', []):
                        if block.get('type') != 'to_do': continue
                        text = ''.join(r.get('plain_text', r.get('text', {}).get('content', ''))
                                       for r in block.get('to_do', {}).get('rich_text', []))
                        if ' '.join(text.casefold().split()) == wanted:
                            return {'ok': True, 'created': False, 'title': text, 'date': day,
                                    'url': 'https://www.notion.so/' + page['id'].replace('-', '')}
                    if not existing.get('has_more'): break
                    cursor = existing.get('next_cursor')
                    if not cursor: raise ValueError('Não consegui verificar se a tarefa já existe. Não criei outra.')
                else:
                    raise ValueError('Este dia tem demasiados blocos para confirmar duplicados. Não criei outra tarefa.')
                self.request('PATCH', 'blocks/' + page['id'] + '/children', {'children': [child]})
            else:
                page = self.request('POST', 'pages', {'parent': {'type': 'data_source_id', 'data_source_id': SOURCE},
                     'properties': {'Dia': {'title': self.rich('Diário · ' + day)}, 'Data': {'date': {'start': day}}},
                     'children': [child]})
        return {'ok': True, 'created': True, 'title': title, 'date': day, 'url': 'https://www.notion.so/' + page['id'].replace('-', '')}

    def pending(self):
        """Bounded on-purpose: latest 30 dated records, at most 1500 blocks."""
        rows = self.request('POST', 'data_sources/' + SOURCE + '/query',
                   {'filter': {'property': 'Data', 'date': {'on_or_before': today_lisbon().isoformat()}},
                    'sorts': [{'property': 'Data', 'direction': 'descending'}], 'page_size': 30})
        tasks, count, partial = [], 0, bool(rows.get('has_more'))
        deadline = time.monotonic() + 40
        def scan(block_id, day, url, depth=0):
            nonlocal count, partial
            cursor = None
            while True:
                if count >= 1500 or time.monotonic() >= deadline or depth > 6:
                    partial = True
                    return
                query = {'page_size': 100}
                if cursor:
                    query['start_cursor'] = cursor
                blocks = self.request('GET', 'blocks/' + block_id + '/children?' + urlencode(query))
                for block in blocks.get('results', []):
                    count += 1
                    if count > 1500 or time.monotonic() >= deadline:
                        partial = True
                        return
                    content = block.get(block.get('type', ''), {})
                    if block.get('type') == 'to_do' and not content.get('checked'):
                        title = ''.join(t.get('plain_text', t.get('text', {}).get('content', '')) for t in content.get('rich_text', []))
                        tasks.append({'id': block['id'], 'title': title, 'date': day, 'url': url})
                    if block.get('has_children') and block.get('type') not in ('child_page', 'child_database'):
                        scan(block['id'], day, url, depth + 1)
                if not blocks.get('has_more'):
                    return
                cursor = blocks.get('next_cursor')
                if not cursor:
                    partial = True
                    return
        for page in rows.get('results', []):
            day = (page.get('properties', {}).get('Data', {}).get('date') or {}).get('start', '')
            scan(page['id'], day, 'https://www.notion.so/' + page['id'].replace('-', ''))
        return {'tasks': tasks, 'partial': partial, 'records': len(rows.get('results', [])),
                'scope': 'Caixas de tarefas dos últimos 30 registos do Diário até hoje; não inclui texto livre nem páginas de projetos.'}
