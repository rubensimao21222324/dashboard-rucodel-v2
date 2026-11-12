"""Google Calendar desktop OAuth with PKCE, loopback callback and DPAPI storage."""
from __future__ import annotations
import base64
from datetime import date, datetime, time as day_time, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from notion_connection import protect_bytes, today_lisbon

SCOPES = 'https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.calendarlist.readonly'
REDIRECT = 'http://127.0.0.1:12396/oauth/google/callback'
# IANA time-zone data is public domain. Embedded fallback for Windows without tzdata.
LISBON_TZIF = 'VFppZjIAAAAAAAAAAAAAAAAAAAAAAAANAAAADQAAAAAAAADhAAAADQAAABuAAAAAkuaOgJtLbXCb/seAnJz7gJ3Jg3Cefi8An6q28KBfYoChi+pwokHngKNub3CkIxsApU+i8KoF73Cq51/wrcmn8K6nI/CvoE9wsIcF8LGJa/CycCJws3KIcLRQBHC3MkxwuA/IcLj/uXC576pwvMi38L24qPC+n19wv5iK8MCa8PDBeGzwwmhd8MNYTvDEPwVwxTgw8MY6lvDHWKxwx9nfcMkD0nDJ8SBwyuJi8Mu1UvDL7KPgzIBL4MzcovDNlTTwzcNLYM5youDOxb9wz3UW8M+sZ+DQUoTg0KWhcNFU+PDRjEng0jJm4NKFg3DTWcTw1Em18NU50SDWKcIg1xmzINgJpCDY+ZUg2emGINrZdyDbyWgg3LlZIN2yhKDeonWg35JmoOCCV6Dhckig4mI5oONSKqDkQhug5TIMoOYh/aDnGykg6AsaIOj7CyDp6vwg6trtIOvK3iDsus8g7arAIO6asSDviqIg8HqTIPFqhCDyY6+g81OgoPRDkaD1M4Kg9iNzoPcTZKD4A1Wg+PNGoPnjN6AMqyoADZsbAA6LDAAPhEWQEHQ2kBFkJ5ASVBiQE01EEBQz+pAVI92AFhPOgBcDv4AX87CAGOOhgBnTkoAaw4OAG7yvABysoAAdnJEAHoyQEB98gRAgbHIQIVxjECJMVBAjPEUQJCw2ECUcJxAmDBgQJwVDkCf1NJAo5SWQKdUWkCrFB5ArtPiQLKTpkC2U2pAuhMuQL3S8kDBkrZAxXdkQMnK0EDM9uxA0UpYQNR2dEDYyeBA2/X8QOBuUkDjdYRA5+3aQOr1DEDvbWJA8pl+QPbs6kD6GQZA/mxyQQGYjkEGEORBCRgWQQ2QbEEQl55BFQ/0QRgXJkEcj3xBH7uYQSQPBEEnOyBBK46MQS66qEEzMv5BNjowQTqyhkE9ubhBQjIOQUVeKkFJsZZBTN2yQVExHkFUXTpBWLCmQVvcwkFgVRhBY1xKQWfUoEFq29JBb1QoQXKAREF207BBef/MQX5TOEGBf1RBhfeqQYj+3EGNdzJBkH5kQZT2ukGYItZBnHZCQZ+iXkGj9cpBpyHmQat1UkGuoW5BsxnEQbYg9kG6mUxBvaB+QcIY1EHFRPBByZhcQczEeEHRF+RB1EQAQdi8VkHbw4hB4DveQeNDEEHnu2ZB6sKYQe867kHyZwpB9rp2QfnmkkH+Of5AABgECAQIBAgECAQIBAgMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMFAwQDBQMEAwUDBAMFAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwcCAwQDBAMEAwQDBAMEAwQDBAMECAYIBggGCAYIBggGCAkKCQoJCgkIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAb///djAAAAAA4QAQQAAAAAAAkAAA4QAQQAAAAAAAkAABwgAQ0AAAAAAAkAAA4QABIAAA4QAQQAAA4QABIAABwgARYAAA4QAQQAAAAAAAlMTVQAV0VTVABXRVQAV0VNVABDRVQAQ0VTVAAAAAABAQEBAQEBAQEBAAAAAAAAAQABAQEBAVRaaWYyAAAAAAAAAAAAAAAAAAAAAAAADQAAAA0AAAAAAAAA4QAAAA0AAAAb/////149DB3/////kuaOgP////+bS21w/////5v+x4D/////nJz7gP////+dyYNw/////55+LwD/////n6q28P////+gX2KA/////6GL6nD/////okHngP////+jbm9w/////6QjGwD/////pU+i8P////+qBe9w/////6rnX/D/////rcmn8P////+upyPw/////6+gT3D/////sIcF8P////+xiWvw/////7JwInD/////s3KIcP////+0UARw/////7cyTHD/////uA/IcP////+4/7lw/////7nvqnD/////vMi38P////+9uKjw/////76fX3D/////v5iK8P/////AmvDw/////8F4bPD/////wmhd8P/////DWE7w/////8Q/BXD/////xTgw8P/////GOpbw/////8dYrHD/////x9nfcP/////JA9Jw/////8nxIHD/////yuJi8P/////LtVLw/////8vso+D/////zIBL4P/////M3KLw/////82VNPD/////zcNLYP/////OcqLg/////87Fv3D/////z3UW8P/////PrGfg/////9BShOD/////0KWhcP/////RVPjw/////9GMSeD/////0jJm4P/////ShYNw/////9NZxPD/////1Em18P/////VOdEg/////9YpwiD/////1xmzIP/////YCaQg/////9j5lSD/////2emGIP/////a2Xcg/////9vJaCD/////3LlZIP/////dsoSg/////96idaD/////35JmoP/////ggleg/////+FySKD/////4mI5oP/////jUiqg/////+RCG6D/////5TIMoP/////mIf2g/////+cbKSD/////6AsaIP/////o+wsg/////+nq/CD/////6trtIP/////ryt4g/////+y6zyD/////7arAIP/////umrEg/////++KoiD/////8HqTIP/////xaoQg//////Jjr6D/////81OgoP/////0Q5Gg//////UzgqD/////9iNzoP/////3E2Sg//////gDVaD/////+PNGoP/////54zegAAAAAAyrKgAAAAAADZsbAAAAAAAOiwwAAAAAAA+ERZAAAAAAEHQ2kAAAAAARZCeQAAAAABJUGJAAAAAAE01EEAAAAAAUM/qQAAAAABUj3YAAAAAAFhPOgAAAAAAXA7+AAAAAABfzsIAAAAAAGOOhgAAAAAAZ05KAAAAAABrDg4AAAAAAG7yvAAAAAAAcrKAAAAAAAB2ckQAAAAAAHoyQEAAAAAAffIEQAAAAACBschAAAAAAIVxjEAAAAAAiTFQQAAAAACM8RRAAAAAAJCw2EAAAAAAlHCcQAAAAACYMGBAAAAAAJwVDkAAAAAAn9TSQAAAAACjlJZAAAAAAKdUWkAAAAAAqxQeQAAAAACu0+JAAAAAALKTpkAAAAAAtlNqQAAAAAC6Ey5AAAAAAL3S8kAAAAAAwZK2QAAAAADFd2RAAAAAAMnK0EAAAAAAzPbsQAAAAADRSlhAAAAAANR2dEAAAAAA2MngQAAAAADb9fxAAAAAAOBuUkAAAAAA43WEQAAAAADn7dpAAAAAAOr1DEAAAAAA721iQAAAAADymX5AAAAAAPbs6kAAAAAA+hkGQAAAAAD+bHJAAAAAAQGYjkAAAAABBhDkQAAAAAEJGBZAAAAAAQ2QbEAAAAABEJeeQAAAAAEVD/RAAAAAARgXJkAAAAABHI98QAAAAAEfu5hAAAAAASQPBEAAAAABJzsgQAAAAAErjoxAAAAAAS66qEAAAAABMzL+QAAAAAE2OjBAAAAAATqyhkAAAAABPbm4QAAAAAFCMg5AAAAAAUVeKkAAAAABSbGWQAAAAAFM3bJAAAAAAVExHkAAAAABVF06QAAAAAFYsKZAAAAAAVvcwkAAAAABYFUYQAAAAAFjXEpAAAAAAWfUoEAAAAABatvSQAAAAAFvVChAAAAAAXKAREAAAAABdtOwQAAAAAF5/8xAAAAAAX5TOEAAAAABgX9UQAAAAAGF96pAAAAAAYj+3EAAAAABjXcyQAAAAAGQfmRAAAAAAZT2ukAAAAABmCLWQAAAAAGcdkJAAAAAAZ+iXkAAAAABo/XKQAAAAAGnIeZAAAAAAat1UkAAAAABrqFuQAAAAAGzGcRAAAAAAbYg9kAAAAABuplMQAAAAAG9oH5AAAAAAcIY1EAAAAABxUTwQAAAAAHJmFxAAAAAAczEeEAAAAAB0RfkQAAAAAHURABAAAAAAdi8VkAAAAAB28OIQAAAAAHgO95AAAAAAeNDEEAAAAAB57tmQAAAAAHqwphAAAAAAe867kAAAAAB8mcKQAAAAAH2unZAAAAAAfnmkkAAAAAB/jn+QAAYBAgECAQIBAgECAQIDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBQMEAwUDBAMFAwQDBQMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMEAwQDBAMHAgMEAwQDBAMEAwQDBAMEAwQDBAgGCAYIBggGCAYIBggJCgkKCQoJCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggGCAYIBggG///3YwAAAAAOEAEEAAAAAAAJAAAOEAEEAAAAAAAJAAAcIAENAAAAAAAJAAAOEAASAAAOEAEEAAAOEAASAAAcIAEWAAAOEAEEAAAAAAAJTE1UAFdFU1QAV0VUAFdFTVQAQ0VUAENFU1QAAAAAAQEBAQEBAQEBAQAAAAAAAAEAAQEBAQEKV0VUMFdFU1QsTTMuNS4wLzEsTTEwLjUuMAo='

def lisbon_zone():
    try:
        return ZoneInfo('Europe/Lisbon')
    except ZoneInfoNotFoundError:
        return ZoneInfo.from_file(io.BytesIO(base64.b64decode(LISBON_TZIF)), key='Europe/Lisbon')

def local_datetime(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?', value):
        raise ValueError('Usa uma data e hora locais no formato AAAA-MM-DDTHH:MM.')
    naive = datetime.fromisoformat(value)
    zone = lisbon_zone()
    valid = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
            valid.append(candidate)
    if not valid:
        raise ValueError('Essa hora não existe em Lisboa devido à mudança da hora. Escolhe outra hora.')
    if len(valid) == 2 and valid[0].utcoffset() != valid[1].utcoffset():
        raise ValueError('Essa hora repete-se na mudança da hora em Lisboa. Escolhe uma hora sem ambiguidade.')
    return valid[0]

class CalendarConnection:
    def __init__(self, root):
        self.file = Path(root) / 'google_calendar.dpapi'
        self.lock = threading.RLock()
        self.pending = None
        self.last_error = ''
        self.calendar_id = 'primary'
        self.calendar_name = 'Agenda principal'
        self.load_error = ''
        if self.file.is_file():
            try:
                saved = self.load()
                self.calendar_id = saved.get('calendar_id', 'primary')
                self.calendar_name = saved.get('calendar_name', 'Agenda principal')
            except (RuntimeError, ValueError, OSError):
                self.load_error = 'Não consegui abrir a ligação Google guardada. Volta a autorizar neste utilizador Windows.'

    def status(self):
        with self.lock:
            if self.pending and time.monotonic() > self.pending['deadline']:
                self.pending = None
                self.last_error = 'O pedido de autorização expirou. Inicia novamente a ligação.'
            return {'configured': self.file.is_file() and not self.load_error,
                    'pending': self.pending is not None, 'error': self.last_error or self.load_error,
                    'calendar_id': self.calendar_id, 'calendar_name': self.calendar_name}

    def load(self):
        if not self.file.is_file():
            raise ValueError('Liga primeiro a Google Agenda nas Definições → Ligar Google Agenda.')
        return json.loads(protect_bytes(self.file.read_bytes(), decrypt=True).decode())

    def save(self, data):
        encrypted = protect_bytes(json.dumps(data, ensure_ascii=False).encode())
        temporary = self.file.with_suffix('.tmp')
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.file)
        self.load_error = ''

    @staticmethod
    def client_config(value):
        if isinstance(value, str):
            if len(value) > 20000:
                raise ValueError('O ficheiro JSON de credenciais é demasiado grande.')
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError('O ficheiro não contém um JSON válido.') from None
        config = value.get('installed') if isinstance(value, dict) else None
        if not isinstance(config, dict):
            raise ValueError('Escolhe o JSON de um cliente «App para computador», não de uma aplicação Web ou conta de serviço.')
        client_id, client_secret = config.get('client_id', ''), config.get('client_secret', '')
        if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_\-]{5,250}\.apps\.googleusercontent\.com', client_id):
            raise ValueError('O JSON não tem um ID de cliente Google válido.')
        if not isinstance(client_secret, str) or not re.fullmatch(r'[A-Za-z0-9_\-]{5,300}', client_secret):
            raise ValueError('O JSON não tem o segredo do cliente Google.')
        # Never use token/auth URLs supplied by a file; Google hosts are fixed below.
        return {'client_id': client_id, 'client_secret': client_secret}

    def start(self, value=None):
        with self.lock:
            client = self.client_config(value) if value is not None else self.load()['client']
            # Verify DPAPI availability before asking the user to authorize.
            protect_bytes(b'Jarvis Google authorization')
            verifier = secrets.token_urlsafe(64)
            state = secrets.token_urlsafe(32)
            self.pending = {'state': state, 'verifier': verifier, 'client': client,
                            'deadline': time.monotonic() + 600}
            self.last_error = ''
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
                    'client_id': client['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
                    'scope': SCOPES, 'state': state, 'code_challenge': challenge,
                    'code_challenge_method': 'S256', 'access_type': 'offline',
                    'prompt': 'consent select_account', 'include_granted_scopes': 'true'}),
                    'expires_seconds': 600}

    @staticmethod
    def token_request(body):
        req = urllib.request.Request('https://oauth2.googleapis.com/token', data=urlencode(body).encode(),
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (400, 401):
                raise RuntimeError('A autorização Google expirou, foi revogada ou o cliente é inválido. Volta a autorizar a conta nas Definições.') from None
            raise RuntimeError('O Google não conseguiu concluir a autorização. Tenta novamente mais tarde.') from None
        except (OSError, ValueError):
            raise RuntimeError('Não consegui comunicar com a autorização Google. Verifica a internet e tenta novamente.') from None

    def complete(self, query):
        with self.lock:
            state = query.get('state', [])
            pending = self.pending
            if not pending or time.monotonic() > pending['deadline']:
                self.pending = None
                raise ValueError('Pedido de autorização inexistente ou expirado. Volta ao Jarvis e inicia a ligação.')
            if len(state) != 1 or not secrets.compare_digest(state[0], pending['state']):
                raise ValueError('A resposta Google não corresponde à autorização iniciada neste Jarvis.')
            self.pending = None  # one-use state; failures require a fresh authorization.
            try:
                if query.get('error'):
                    raise ValueError('A autorização foi cancelada ou recusada no Google. Podes iniciar novamente a ligação.')
                code = query.get('code', [])
                if len(code) != 1 or not isinstance(code[0], str) or not 1 <= len(code[0]) <= 4096:
                    raise ValueError('O Google não devolveu um código de autorização válido.')
                token = self.token_request({**pending['client'], 'code': code[0],
                        'grant_type': 'authorization_code', 'redirect_uri': REDIRECT,
                        'code_verifier': pending['verifier']})
                granted = set(str(token.get('scope', SCOPES)).split())
                if not set(SCOPES.split()).issubset(granted):
                    raise ValueError('Faltam permissões de agenda. Repete a autorização e permite consultar agendas e gerir eventos.')
                if not token.get('access_token') or not token.get('refresh_token'):
                    raise ValueError('O Google não devolveu uma autorização duradoura. Inicia a ligação novamente.')
                saved = {'client': pending['client'], 'access_token': token['access_token'],
                         'refresh_token': token['refresh_token'], 'expires_at': time.time() + int(token.get('expires_in', 3600)),
                         'calendar_id': 'primary', 'calendar_name': 'Agenda principal'}
                # A successful API read is required before replacing an existing connection.
                calendars = self.calendars_with_token(saved['access_token'])
                primary = next((c for c in calendars if c.get('primary')), None)
                if not primary:
                    raise ValueError('Não encontrei a agenda principal nesta conta Google.')
                saved['calendar_id'], saved['calendar_name'] = primary['id'], primary['name']
                self.save(saved)
                self.calendar_id, self.calendar_name = primary['id'], primary['name']
                self.last_error = ''
                return {'ok': True, **self.status(), 'verified': True}
            except (RuntimeError, ValueError, OSError) as error:
                self.last_error = str(error)
                raise

    def access_token(self):
        with self.lock:
            data = self.load()
            if data.get('access_token') and data.get('expires_at', 0) > time.time() + 60:
                return data['access_token']
            token = self.token_request({**data['client'], 'refresh_token': data['refresh_token'],
                                       'grant_type': 'refresh_token'})
            if not token.get('access_token'):
                raise RuntimeError('O Google não devolveu um token válido. Volta a autorizar nas Definições.')
            data['access_token'] = token['access_token']
            data['expires_at'] = time.time() + int(token.get('expires_in', 3600))
            if token.get('refresh_token'):
                data['refresh_token'] = token['refresh_token']
            self.save(data)
            return data['access_token']

    def api(self, method, path, body=None, token=None, missing_ok=False):
        credential = token if token is not None else self.access_token()
        req = urllib.request.Request('https://www.googleapis.com/calendar/v3/' + path,
                data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, method=method,
                headers={'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            messages = {401: 'A ligação Google deixou de ser válida. Volta a autorizar a conta nas Definições.',
                        403: 'O Google recusou o acesso. Confirma a API Calendar ativada, as permissões e o utilizador de teste.',
                        404: 'A agenda ou evento Google já não está disponível.',
                        409: 'Este evento já existe. Consulta a agenda antes de repetir.',
                        429: 'O Google está a limitar pedidos. Aguarda um pouco antes de voltar a tentar.'}
            raise RuntimeError(messages.get(error.code, 'O Google recusou o pedido (HTTP ' + str(error.code) + ').')) from None
        except (OSError, ValueError):
            if method != 'GET':
                raise RuntimeError('A ligação Google foi interrompida. O evento pode ter sido criado: verifica a agenda antes de repetir. Repetir o mesmo título e horário reutiliza o mesmo evento.') from None
            raise RuntimeError('Não consegui consultar a Google Agenda. Verifica a internet.') from None

    def calendars_with_token(self, token=None):
        calendars, cursor = [], None
        for _ in range(10):
            query = {'maxResults': 250}
            if cursor:
                query['pageToken'] = cursor
            data = self.api('GET', 'users/me/calendarList?' + urlencode(query), token=token)
            calendars.extend({'id': c['id'], 'name': c.get('summaryOverride') or c.get('summary', 'Agenda'),
                              'primary': bool(c.get('primary')), 'role': c.get('accessRole', 'reader')}
                             for c in data.get('items', []) if not c.get('deleted'))
            cursor = data.get('nextPageToken')
            if not cursor:
                return calendars
        raise RuntimeError('A lista de agendas é demasiado grande para esta ligação. Não consegui obter a lista completa.')

    def verify(self):
        with self.lock:
            calendars = self.calendars_with_token()
            if not any(c['id'] == self.calendar_id for c in calendars):
                raise ValueError('A agenda selecionada já não está acessível. Escolhe outra nas Definições.')
            self.last_error = ''
            return {'ok': True, **self.status(), 'verified': True, 'calendars': calendars}

    def select(self, calendar_id):
        with self.lock:
            calendars = self.calendars_with_token()
            chosen = next((c for c in calendars if c['id'] == calendar_id), None)
            if not chosen:
                raise ValueError('Escolhe uma das agendas disponíveis na conta autorizada.')
            data = self.load()
            data['calendar_id'], data['calendar_name'] = chosen['id'], chosen['name']
            self.save(data)
            self.calendar_id, self.calendar_name = chosen['id'], chosen['name']
            return {'ok': True, **self.status()}

    @staticmethod
    def event_row(event):
        start, end = event.get('start', {}), event.get('end', {})
        return {'id': event['id'], 'title': event.get('summary', '(sem título)'),
                'start': start.get('dateTime') or start.get('date', ''),
                'end': end.get('dateTime') or end.get('date', ''),
                'all_day': 'date' in start, 'url': event.get('htmlLink', ''),
                'location': event.get('location', '')}

    def events(self, day=None):
        with self.lock:
            day = date.fromisoformat(day) if day else today_lisbon()
            zone = lisbon_zone()
            start = datetime.combine(day, day_time.min, zone)
            end = datetime.combine(day + timedelta(days=1), day_time.min, zone)
            query = {'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'singleEvents': 'true',
                     'orderBy': 'startTime', 'timeZone': 'Europe/Lisbon', 'maxResults': 250}
            events, partial = [], False
            for _ in range(4):
                data = self.api('GET', 'calendars/' + quote(self.calendar_id, safe='') + '/events?' + urlencode(query))
                events.extend(self.event_row(e) for e in data.get('items', []) if e.get('status') != 'cancelled')
                cursor = data.get('nextPageToken')
                if not cursor:
                    break
                query['pageToken'], partial = cursor, True
            else:
                return {'events': events, 'partial': True, 'date': day.isoformat(), 'calendar_name': self.calendar_name}
            return {'events': events, 'partial': False, 'date': day.isoformat(), 'calendar_name': self.calendar_name}

    def create_event(self, title, start, end):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 500:
            raise ValueError('Escreve um título de evento com 1 a 500 caracteres.')
        start, end = local_datetime(start), local_datetime(end)
        duration = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
        if not timedelta(0) < duration <= timedelta(days=7):
            raise ValueError('O fim tem de ser posterior ao início, com duração máxima de sete dias.')
        with self.lock:
            calendars = self.calendars_with_token()
            chosen = next((c for c in calendars if c['id'] == self.calendar_id), None)
            if not chosen or chosen['role'] not in ('owner', 'writer'):
                raise ValueError('Não tens permissão para criar eventos nesta agenda. Seleciona uma agenda onde possas escrever.')
            fingerprint = hashlib.sha256(json.dumps([self.calendar_id, title.strip(), start.isoformat(), end.isoformat()], ensure_ascii=False).encode()).hexdigest()
            path = 'calendars/' + quote(self.calendar_id, safe='') + '/events'
            existing = self.api('GET', path + '/' + fingerprint, missing_ok=True)
            if existing:
                if existing.get('status') == 'cancelled':
                    raise ValueError('Um evento igual foi eliminado anteriormente. Altera o título para o criares novamente.')
                if existing.get('extendedProperties', {}).get('private', {}).get('jarvisFingerprint') != fingerprint:
                    raise ValueError('O identificador deste evento já está em uso. Verifica a agenda.')
                try:
                    actual_start=datetime.fromisoformat(existing.get('start', {}).get('dateTime', '').replace('Z','+00:00'))
                    actual_end=datetime.fromisoformat(existing.get('end', {}).get('dateTime', '').replace('Z','+00:00'))
                    same_times=(actual_start.tzinfo is not None and actual_end.tzinfo is not None and
                                actual_start.astimezone(timezone.utc)==start.astimezone(timezone.utc) and
                                actual_end.astimezone(timezone.utc)==end.astimezone(timezone.utc))
                except (ValueError,TypeError):
                    same_times=False
                if existing.get('summary') != title.strip() or not same_times:
                    raise ValueError('O evento criado anteriormente foi alterado. Consulta a agenda antes de criar outro igual.')
                return {'ok': True, 'created': False, 'event': self.event_row(existing), 'calendar_name': self.calendar_name}
            body = {'id': fingerprint, 'summary': title.strip(),
                    'start': {'dateTime': start.isoformat(), 'timeZone': 'Europe/Lisbon'},
                    'end': {'dateTime': end.isoformat(), 'timeZone': 'Europe/Lisbon'},
                    'extendedProperties': {'private': {'jarvisFingerprint': fingerprint}}}
            event = self.api('POST', path, body)
            return {'ok': True, 'created': True, 'event': self.event_row(event), 'calendar_name': self.calendar_name}

    def disconnect(self):
        with self.lock:
            self.pending = None
            self.file.unlink(missing_ok=True)
            self.last_error = self.load_error = ''
            self.calendar_id, self.calendar_name = 'primary', 'Agenda principal'
            return {'ok': True, **self.status()}
