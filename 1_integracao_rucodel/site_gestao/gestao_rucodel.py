"""Read-only access to the Rucodel management site (gestao.rucodel.pt): overdue services list.

The Jarvis user logs in with its own account and only ever *reads* pages:
- every GET goes through an allow-list (login page, «Fora de Prazo» pages, image cache);
- the only POST is the login form itself;
- no button, link or form that changes data is ever used.
Credentials are stored in a Windows DPAPI protected file, never in logs or chats.
"""
from __future__ import annotations
from datetime import date, datetime
import html
from http.cookiejar import CookieJar
import io
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

BASE = 'https://gestao.rucodel.pt'
LOGIN_PATH = '/pt/'
OVERDUE_PATH = '/p.acesso/Servicos.L1/servico.g/qt/prazo/pag/{}'
LIST_PATH = '/p.acesso/Servicos.L1/servico'
# Only list pages (zone / state / page filters) and images: nothing that edits, prints or invoices.
SEGMENT = r'(?:/(?:zona/\d{1,4}|qt/(?:aguardar|curso|terminado|prazo)|pag/\d{1,3}))'
ALLOWED_GET = re.compile(r'^/(?:pt/|p\.acesso/Servicos\.L1/servico\.g'+SEGMENT+r'{1,4}|p\.acesso/Servicos\.L1/servico-tarefas-modal\.g/id/[a-f0-9]{32}|img/cache/[A-Za-z0-9_-]+\.(?:jpe?g|png|gif|webp))$')
STATES = [('aguardar', 'A aguardar'), ('curso', 'Em curso'), ('terminado', 'Terminados')]
ZONE_TRIGGER = re.compile(r'\bpor zonas?\b|\bzonas?\b[^.?!]{0,40}\b(?:pronto|prontas?|aguardar|em curso|terminad\w*|lista)\b'
                          r'|\b(?:pronto|prontas?|lista)\b[^.?!]{0,40}\bzonas?\b')
REPORT_TRIGGER = re.compile(
    r'\b(?:jantes?|servicos?|trabalhos?)\b[^.?!]{0,40}\b(?:fora d[eo] prazo|atrasad[oa]s?|em atraso)\b'
    r'|\b(?:fora d[eo] prazo|atrasad[oa]s?|em atraso)\b[^.?!]{0,25}\b(?:jantes?|servicos?)\b')


def clean(fragment):
    text = re.sub(r'<[^>]+>', ' ', fragment or '')
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


class FormReader:
    """Finds the login form: action, hidden fields, user and password field names."""
    @staticmethod
    def parse(page):
        for form in re.finditer(r'<form\b([^>]*)>(.*?)</form>', page, re.S | re.I):
            attrs, body = form.group(1), form.group(2)
            inputs = [dict(re.findall(r'([\w-]+)\s*=\s*["\']([^"\']*)["\']', tag)) for tag in re.findall(r'<input\b[^>]*>', body, re.I)]
            password = next((i for i in inputs if i.get('type', '').lower() == 'password' and i.get('name')), None)
            if not password: continue
            user = next((i for i in inputs if i.get('name') and i.get('type', 'text').lower() in ('text', 'email', '')), None)
            action = (re.search(r'action\s*=\s*["\']([^"\']*)["\']', attrs, re.I) or [None, ''])[1]
            hidden = {i['name']: i.get('value', '') for i in inputs if i.get('type', '').lower() == 'hidden' and i.get('name')}
            buttons = {i['name']: i.get('value', '') for i in inputs if i.get('type', '').lower() == 'submit' and i.get('name')}
            return {'action': html.unescape(action), 'user': user and user['name'], 'password': password['name'], 'hidden': {**hidden, **buttons}}
        raise RuntimeError('Não encontrei o formulário de entrada do programa de gestão. A página pode ter mudado.')


def parse_overdue(page):
    """One dict per service row of a «Fora de Prazo» page."""
    rows = []
    starts = [m.start() for m in re.finditer(r'<td class="hidden-lg">', page)]
    for index, start in enumerate(starts):
        chunk = page[start:starts[index+1] if index+1 < len(starts) else len(page)]
        def field(name):
            match = re.search(r'data-title="'+re.escape(name)+r':">(.*?)</td>', chunk, re.S)
            return clean(match.group(1)) if match else ''
        created = re.search(r'Criado:</small>\s*<br>\s*([\d-]{10} [\d:]{5,8})', chunk)
        due = re.search(r'Prazo de Entrega:</small>\s*<br>\s*(?:<span[^>]*>)?\s*([\d-]{10} [\d:]{5,8})', chunk)
        client = re.search(r'data-title="Cliente">\s*(?:<span class="label[^"]*">([^<]*)</span>)?\s*(?:<a [^>]*>(.*?)</a>)?(?:\s*<br>\s*<em>(.*?)</em>)?', chunk, re.S)
        service_id = re.search(r'/servico\.g/(?:edit|tarefas)/([a-f0-9]{32})', chunk)
        modal = re.search(r'url="(/p\.acesso/Servicos\.L1/servico-tarefas-modal\.g/id/[a-f0-9]{32})"', chunk)
        thumb = re.search(r'<img src="(/img/cache/[^"]+)"', chunk)
        quantity = re.search(r'data-title="Qt:">\s*<span[^>]*>\s*(\d+)', chunk)
        if not (created and due): continue
        rows.append({
            'id': service_id.group(1) if service_id else created.group(1),
            'criado': created.group(1), 'prazo': due.group(1),
            'cliente_numero': clean(client.group(1)) if client else '',
            'cliente': clean(client.group(2)) if client else '',
            'tipo': field('Tipo'), 'quantidade': int(quantity.group(1)) if quantity else None,
            'tamanho': field('Tam'), 'cor': field('Cor'), 'outra': field('Outra'),
            'detalhes': field('Detalhes'), 'imagem': thumb.group(1) if thumb else None, 'gerir': modal.group(1) if modal else None})
    return rows


def has_next(page):
    return bool(next_page(page))


def next_page(page):
    match = re.search(r'<a href="([^"]*/pag/\d+)" title="seguinte">', page)
    return html.unescape(match.group(1)) if match else None


def zone_options(page):
    """[(id, name)] from the «Zonas» selector, in the order the program shows them."""
    block = re.search(r'<select[^>]*id="zona".*?</select>', page, re.S)
    return [(z, clean(name)) for z, name in re.findall(r'<option value="(\d+)"[^>]*>([^<]+)</option>', block.group(0) if block else '')]


def zone_selected(page, final_path, zone):
    block = re.search(r'<select[^>]*id="zona".*?</select>', page, re.S)
    marked = bool(block and re.search(r'<option value="'+zone+r'"\s+selected', block.group(0)))
    return marked or bool(re.search(r'/zona/'+zone+r'(?:/|$)', final_path))


def state_link(page, state):
    match = re.search(r'href="(/p\.acesso/Servicos\.L1/servico\.g/[^"]*qt/'+state+r'(?:/[^"]*)?)"', page)
    return html.unescape(match.group(1)) if match else None


def due_label(row, today):
    days = (date.fromisoformat(row['prazo'][:10]) - today).days
    if days < 0: return 'atrasado %d dia%s' % (-days, 's' if days < -1 else '')
    return {0: 'hoje', 1: 'amanhã'}.get(days, 'em %d dias' % days)


def colour_or_job(row):
    """The colour when there is one; otherwise the job type (e.g. «Só Desempenar / Soldar»)."""
    return row['cor'] if row['cor'] else (row['tipo'] or 'Sem cor indicada')


def days_late(row, today):
    return (today - date.fromisoformat(row['prazo'][:10])).days


class GestaoRucodel:
    def __init__(self, root, settings, protect=None):
        self.root, self.settings = Path(root), settings
        self.file = self.root/'gestao_rucodel.dpapi'
        self.protect = protect
        self.opener = None

    # --- credentials -------------------------------------------------------
    def configured(self):
        return self.file.is_file()

    def save_credentials(self, user, password):
        data = json.dumps({'user': user, 'password': password}).encode()
        temporary = self.file.with_suffix('.tmp'); temporary.write_bytes(self.protect(data)); temporary.replace(self.file)

    def credentials(self):
        if not self.configured():
            raise RuntimeError('O acesso ao programa de gestão ainda não está configurado. Corre CONFIGURAR_GESTAO.cmd no PC.')
        return json.loads(self.protect(self.file.read_bytes(), decrypt=True))

    # --- read-only HTTP ----------------------------------------------------
    def base(self):
        return self.settings.get('gestao_url', BASE).rstrip('/')

    def get(self, path, binary=False):
        if not ALLOWED_GET.match(path):
            raise RuntimeError('Endereço fora da lista de leitura permitida: nada foi aberto.')
        request = urllib.request.Request(self.base()+path, headers={'X-Requested-With': 'XMLHttpRequest'} if 'tarefas-modal' in path else {})
        with self.opener.open(request, timeout=30) as response:
            data = response.read(8_000_000)
            final = urllib.parse.urlparse(response.geturl()).path
        return data if binary else (data.decode('utf-8', 'replace'), final)

    def login(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.opener.addheaders = [('User-Agent', 'Jarvis-Rucodel/1.0 (leitura)')]
        page, _ = self.get(LOGIN_PATH)
        form = FormReader.parse(page)
        creds = self.credentials()
        fields = {**form['hidden'], form['password']: creds['password']}
        if form['user']: fields[form['user']] = creds['user']
        action = urllib.parse.urljoin(self.base()+LOGIN_PATH, form['action'] or LOGIN_PATH)
        if urllib.parse.urlparse(action).netloc != urllib.parse.urlparse(self.base()).netloc:
            raise RuntimeError('O formulário de entrada aponta para outro site: não enviei a palavra-passe.')
        request = urllib.request.Request(action, data=urllib.parse.urlencode(fields).encode(), method='POST',
                                         headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': self.base()+LOGIN_PATH})
        with self.opener.open(request, timeout=30) as response: response.read(2_000_000)
        page, final = self.get(OVERDUE_PATH.format(1))
        if 'type="password"' in page or 'Fora de Prazo' not in page:
            raise RuntimeError('O programa de gestão não aceitou o utilizador ou a palavra-passe do Jarvis. Corre CONFIGURAR_GESTAO.cmd de novo.')
        return page

    def all_pages(self, first_path, max_pages=40):
        """Rows of a list and of all its following pages (page 1, 2, 3…), without duplicates."""
        page, final = self.get(first_path)
        rows, seen, path = [], set(), first_path
        for _ in range(max_pages):
            for row in parse_overdue(page):
                if row['id'] not in seen: seen.add(row['id']); rows.append(row)
            path = next_page(page)
            if not path: break
            page, final = self.get(path)
        return rows

    def zone_state(self, zone, state):
        """Open the zone, follow its «A Aguardar / Em Curso / Terminados» button and check the zone is still applied."""
        zone_page, _ = self.get(LIST_PATH+'.g/zona/'+zone)
        candidates = [state_link(zone_page, state), LIST_PATH+'.g/zona/'+zone+'/qt/'+state, LIST_PATH+'.g/qt/'+state+'/zona/'+zone]
        for path in dict.fromkeys(c for c in candidates if c and ALLOWED_GET.match(c)):
            page, final = self.get(path)
            if zone_selected(page, final, zone) and ('zona/'+zone) in path+final:
                return self.all_pages(path)
        raise RuntimeError('O programa não manteve a zona ao escolher «'+dict(STATES)[state]+'». Nada foi alterado; envia ao Claude a página dessa zona.')

    def by_zone(self):
        first = self.login()
        zones = zone_options(first)
        if not zones: raise RuntimeError('Não encontrei a lista de zonas no programa de gestão.')
        result = []
        for zone, name in zones:
            states = {state: self.zone_state(zone, state) for state, _ in STATES}
            result.append({'zona': zone, 'nome': name, 'estados': states})
        # Safety net: if every zone returned the same services, the zone filter was ignored.
        for state, _ in STATES:
            sets = [frozenset(r['id'] for r in z['estados'][state]) for z in result if z['estados'][state]]
            if len(sets) > 2 and len(set(sets)) == 1:
                raise RuntimeError('Todas as zonas devolveram os mesmos serviços: o filtro de zona não funcionou. Não gerei a lista.')
        return result

    def thumbnails(self, rows):
        from concurrent.futures import ThreadPoolExecutor
        unique = {r['id']: r['imagem'] for r in rows}
        with ThreadPoolExecutor(6) as pool:
            return dict(zip(unique, pool.map(self.thumbnail, unique.values())))

    def zone_report(self, today=None, now=None):
        today = today or date.today(); now = now or datetime.now()
        zones = self.by_zone()
        images = self.thumbnails([r for z in zones for rows in z['estados'].values() for r in rows])
        folder = self.root/'relatorios'; folder.mkdir(exist_ok=True)
        stem = 'jantes_por_zona_'+now.strftime('%Y%m%d_%H%M')
        pdf, xlsx = folder/(stem+'.pdf'), folder/(stem+'.xlsx')
        build_zone_pdf(zones, images, pdf, today, now)
        build_zone_xlsx(zones, images, xlsx, today, now)
        return {'zonas': zones, 'pdf': pdf.name, 'excel': xlsx.name}

    def overdue(self, max_pages=30):
        page = self.login()
        rows, seen = [], set()
        for number in range(1, max_pages+1):
            if number > 1: page, _ = self.get(OVERDUE_PATH.format(number))
            for row in parse_overdue(page):
                if row['id'] not in seen: seen.add(row['id']); rows.append(row)
            if not has_next(page): break
        return rows

    def thumbnail(self, path):
        try: return self.get(path, binary=True) if path else None
        except (OSError, RuntimeError): return None

    # --- report ------------------------------------------------------------
    def report(self, today=None, now=None):
        today = today or date.today(); now = now or datetime.now()
        rows = sorted(self.overdue(), key=lambda r: r['prazo'])
        images = {r['id']: self.thumbnail(r['imagem']) for r in rows}
        folder = self.root/'relatorios'; folder.mkdir(exist_ok=True)
        stem = 'jantes_fora_de_prazo_'+now.strftime('%Y%m%d_%H%M')
        pdf, xlsx = folder/(stem+'.pdf'), folder/(stem+'.xlsx')
        build_pdf(rows, images, pdf, today, now)
        build_xlsx(rows, images, xlsx, today, now)
        return {'linhas': rows, 'pdf': pdf.name, 'excel': xlsx.name}


def small_image(data, size=160):
    if not data: return None
    try:
        from PIL import Image
        picture = Image.open(io.BytesIO(data)); picture.thumbnail((size, size)); picture = picture.convert('RGB')
        out = io.BytesIO(); picture.save(out, 'JPEG', quality=80); out.seek(0); return out
    except Exception:
        return None


COLUMNS = ['Foto', 'Cliente', 'Criado', 'Prazo de entrega', 'Atraso', 'Qt / Tam', 'Cor / trabalho']


def row_values(row, today):
    client = (row['cliente_numero']+' · ' if row['cliente_numero'] else '')+row['cliente']
    size = (str(row['quantidade'] or '?')+' × '+re.sub(r'\.0+$', '', row['tamanho'])+'"') if row['tamanho'] else str(row['quantidade'] or '')
    return [client, row['criado'][:16], row['prazo'][:16], str(days_late(row, today))+' dias', size, colour_or_job(row)]


def build_pdf(rows, images, path, today, now):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    styles = getSampleStyleSheet(); cell = styles['BodyText']; cell.fontSize = 9; cell.leading = 11
    week = sum(days_late(r, today) > 7 for r in rows)
    story = [Paragraph('Jantes fora de prazo', styles['Title']),
             Paragraph('Gerado pelo Jarvis em %s · %d serviços fora de prazo · %d há mais de 7 dias' % (now.strftime('%d/%m/%Y %H:%M'), len(rows), week), styles['Normal']),
             Spacer(1, 4*mm)]
    data = [COLUMNS]
    for row in rows:
        picture = small_image(images.get(row['id']))
        data.append([Image(picture, width=18*mm, height=18*mm, kind='proportional') if picture else '—']
                    + [Paragraph(html.escape(v), cell) for v in row_values(row, today)])
    table = Table(data, colWidths=[22*mm, 62*mm, 30*mm, 30*mm, 20*mm, 22*mm, 84*mm], repeatRows=1)
    style = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
             ('FONTSIZE', (0, 0), (-1, 0), 9), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
             ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
             ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])]
    for index, row in enumerate(rows, start=1):
        if days_late(row, today) > 7: style.append(('TEXTCOLOR', (4, index), (4, index), colors.HexColor('#b91c1c')))
    table.setStyle(TableStyle(style))
    story.append(table if rows else Paragraph('Não há serviços fora de prazo.', styles['Normal']))
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm,
                      title='Jantes fora de prazo').build(story)


def build_xlsx(rows, images, path, today, now):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.styles import Alignment, Font, PatternFill
    book = Workbook(); sheet = book.active; sheet.title = 'Fora de prazo'
    sheet.append(['Jantes fora de prazo — gerado pelo Jarvis em '+now.strftime('%d/%m/%Y %H:%M')])
    sheet['A1'].font = Font(bold=True, size=13)
    sheet.append(COLUMNS+['Dias de atraso', 'Detalhes'])
    for cell in sheet[2]: cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='1F2937')
    for width, letter in zip([14, 32, 18, 18, 10, 12, 40, 10, 40], 'ABCDEFGHI'): sheet.column_dimensions[letter].width = width
    for index, row in enumerate(rows, start=3):
        values = row_values(row, today)
        sheet.append(['']+values+[days_late(row, today), row['detalhes']])
        sheet.row_dimensions[index].height = 62
        for cell in sheet[index]: cell.alignment = Alignment(vertical='center', wrap_text=True)
        picture = small_image(images.get(row['id']), 80)
        if picture:
            image = XlImage(picture); image.anchor = 'A'+str(index); sheet.add_image(image)
    sheet.freeze_panes = 'A3'; sheet.auto_filter.ref = 'B2:I'+str(max(2, len(rows)+2))
    book.save(path)


def summary_text(result, today):
    rows = result['linhas']
    if not rows:
        return 'Não há serviços fora de prazo no programa de gestão. Não gerei lista.'
    week = [r for r in rows if days_late(r, today) > 7]
    lines = ['Há %d serviços fora de prazo no programa de gestão, %d deles há mais de 7 dias.' % (len(rows), len(week))]
    lines.append('Os mais atrasados: '+'; '.join('%s (%s), %d dias' % (r['cliente'] or 'cliente sem nome', colour_or_job(r), days_late(r, today)) for r in rows[:3])+'.')
    lines.append('Lista completa com fotografias:')
    lines.append('/relatorios/'+result['pdf'])
    lines.append('/relatorios/'+result['excel'])
    return '\n'.join(lines)


ZONE_COLUMNS = ['Foto', 'Cliente', 'Criado', 'Prazo de entrega', 'Situação', 'Qt / Tam', 'Cor / trabalho']


def zone_values(row, today):
    values = row_values(row, today)
    return values[:3]+[due_label(row, today)]+values[4:]


def build_zone_pdf(zones, images, path, today, now):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    styles = getSampleStyleSheet(); cell = styles['BodyText']; cell.fontSize = 9; cell.leading = 11
    total = sum(len(rows) for z in zones for rows in z['estados'].values())
    story = [Paragraph('Jantes por zona', styles['Title']),
             Paragraph('Gerado pelo Jarvis em %s · %d serviços · A aguardar, Em curso e Terminados de cada zona' % (now.strftime('%d/%m/%Y %H:%M'), total), styles['Normal'])]
    for zone in zones:
        if not any(zone['estados'].values()): continue
        story += [Spacer(1, 6*mm), CondPageBreak(60*mm), Paragraph('Zona '+html.escape(zone['nome']), styles['Heading1'])]
        for state, label in STATES:
            rows = sorted(zone['estados'][state], key=lambda r: r['prazo'])
            if not rows: continue
            story.append(Paragraph('%s · %d serviço%s' % (label, len(rows), '' if len(rows) == 1 else 's'), styles['Heading3']))
            data = [ZONE_COLUMNS]
            for row in rows:
                picture = small_image(images.get(row['id']))
                data.append([Image(picture, width=16*mm, height=16*mm, kind='proportional') if picture else '—']
                            + [Paragraph(html.escape(v), cell) for v in zone_values(row, today)])
            table = Table(data, colWidths=[20*mm, 62*mm, 30*mm, 30*mm, 26*mm, 22*mm, 80*mm], repeatRows=1)
            style = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                     ('FONTSIZE', (0, 0), (-1, 0), 9), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                     ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
                     ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])]
            for index, row in enumerate(rows, start=1):
                days = (date.fromisoformat(row['prazo'][:10]) - today).days
                if days <= 0: style.append(('TEXTCOLOR', (4, index), (4, index), colors.HexColor('#b91c1c' if days < 0 else '#b45309')))
            table.setStyle(TableStyle(style)); story += [table, Spacer(1, 3*mm)]
    if total == 0: story.append(Paragraph('Não há serviços a aguardar, em curso ou terminados em nenhuma zona.', styles['Normal']))
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm,
                      title='Jantes por zona').build(story)


def build_zone_xlsx(zones, images, path, today, now):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.styles import Alignment, Font, PatternFill
    book = Workbook(); sheet = book.active; sheet.title = 'Por zona'
    sheet.append(['Jantes por zona — gerado pelo Jarvis em '+now.strftime('%d/%m/%Y %H:%M')]); sheet['A1'].font = Font(bold=True, size=13)
    sheet.append(['Zona', 'Estado']+ZONE_COLUMNS+['Detalhes'])
    for cell in sheet[2]: cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='1F2937')
    for width, letter in zip([24, 12, 12, 30, 17, 17, 14, 10, 38, 38], 'ABCDEFGHIJ'): sheet.column_dimensions[letter].width = width
    index = 2
    for zone in zones:
        for state, label in STATES:
            for row in sorted(zone['estados'][state], key=lambda r: r['prazo']):
                index += 1
                sheet.append([zone['nome'], label, '']+zone_values(row, today)+[row['detalhes']])
                sheet.row_dimensions[index].height = 50
                for cell in sheet[index]: cell.alignment = Alignment(vertical='center', wrap_text=True)
                picture = small_image(images.get(row['id']), 64)
                if picture:
                    image = XlImage(picture); image.anchor = 'C'+str(index); sheet.add_image(image)
    sheet.freeze_panes = 'A3'; sheet.auto_filter.ref = 'A2:J'+str(max(2, index))
    book.save(path)


def zone_summary_text(result, today):
    lines, total = [], 0
    for zone in result['zonas']:
        counts = [len(zone['estados'][s]) for s, _ in STATES]
        if not any(counts): continue
        total += sum(counts)
        due = sum(1 for s in ('aguardar', 'curso') for r in zone['estados'][s] if date.fromisoformat(r['prazo'][:10]) <= today)
        lines.append('Zona %s: %d a aguardar, %d em curso, %d terminados%s.' % (zone['nome'], *counts, (' (%d com prazo até hoje)' % due) if due else ''))
    if not lines: return 'Não há serviços a aguardar, em curso ou terminados em nenhuma zona.'
    return '\n'.join(lines+['Lista completa por zona, com fotografias:', '/relatorios/'+result['pdf'], '/relatorios/'+result['excel']])


# --- Day list: what must be ready on a given day (and the next working day) -------------------
MONTHS = ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
WEEKDAY_NAMES = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
DAY_WORDS = re.compile(r'\b(?:servicos?|trabalhos?|jantes?|pronto|prontas?|producao)\b')


def fold_text(text):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def extract_day(text, today):
    """«dia 2», «2 de novembro», «02/11», «amanhã», «sábado»… -> date, or None."""
    from datetime import timedelta
    value = fold_text(text)
    match = re.search(r'\b(?:dia\s+)?(\d{1,2})\s+de\s+('+'|'.join(MONTHS)+r')(?:\s+de\s+(\d{4}))?\b', value)
    if match:
        day, month = int(match[1]), MONTHS.index(match[2])+1
        if match[3]: return date(int(match[3]), month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today-timedelta(days=31) else date(today.year+1, month, day)
    match = re.search(r'\bdia\s+(\d{1,2})\b(?!\s*[/:h])', value)
    if match:
        day, year, month = int(match[1]), today.year, today.month
        for _ in range(13):  # this month if the day has not passed, otherwise the next month that has that day
            try:
                candidate = date(year, month, day)
                if candidate >= today: return candidate
            except ValueError: pass
            year, month = (year+1, 1) if month == 12 else (year, month+1)
        return None
    from action_requests import DAY, parse_day
    match = DAY.search(value)
    if match:
        try: return date.fromisoformat(parse_day(match.group(0), today))
        except ValueError: return None
    return None


def next_working_day(day):
    """The following day, jumping Sunday (Saturday is a working day)."""
    from datetime import timedelta
    following = day+timedelta(days=1)
    return following+timedelta(days=1) if following.weekday() == 6 else following


def job_group(row):
    kind = fold_text(row['tipo'])
    if kind.startswith('orcamento'): return 'Outro'
    if 'maquinad' in kind: return 'Maquinada'
    if 'pintad' in kind: return 'Pintada'
    return 'Outro'


def day_counts(rows):
    counts = {'Maquinada': 0, 'Pintada': 0, 'Outro': 0}
    for row in rows: counts[job_group(row)] += row['quantidade'] or 1
    return counts


def day_label(day):
    return '%s, %d de %s' % (WEEKDAY_NAMES[day.weekday()], day.day, ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'][day.month-1])


def split_by_day(zones, days):
    """{day: [zone with only that day's services]} keeping zone and state order."""
    result = {}
    for day in days:
        key = day.isoformat()
        result[day] = [{**z, 'estados': {s: [r for r in rows if r['prazo'][:10] == key] for s, rows in z['estados'].items()}} for z in zones]
    return result


def _day_report(self, day, now=None):
    now = now or datetime.now()
    days = [day, next_working_day(day)]
    parts = split_by_day(self.by_zone(), days)
    rows = [r for zones in parts.values() for z in zones for rs in z['estados'].values() for r in rs]
    images = self.thumbnails(rows)
    folder = self.root/'relatorios'; folder.mkdir(exist_ok=True)
    stem = 'jantes_dia_'+day.strftime('%Y%m%d')+'_'+now.strftime('%Y%m%d_%H%M')
    pdf, xlsx = folder/(stem+'.pdf'), folder/(stem+'.xlsx')
    build_day_pdf(parts, images, pdf, now)
    build_day_xlsx(parts, images, xlsx, now)
    return {'dias': parts, 'pdf': pdf.name, 'excel': xlsx.name}


GestaoRucodel.day_report = _day_report
DAY_COLUMNS = ['Foto', 'Cliente', 'Entrada', 'Hora', 'Qt × Tam', 'Tipo', 'Cor']


def by_client(rows):
    """Same client together (alphabetical), then by delivery time."""
    return sorted(rows, key=lambda r: (fold_text(r['cliente']).strip(), r['cliente_numero'], r['prazo']))


def compact_values(row):
    size = re.sub(r'\.0+$', '', row['tamanho'])
    entry = row['criado'][8:10]+'/'+row['criado'][5:7]
    return [(row['cliente_numero']+' · ' if row['cliente_numero'] else '')+row['cliente'], entry, row['prazo'][11:16],
            str(row['quantidade'] or '?')+(' × '+size+'"' if size else ''), row['tipo'], row['cor'] or '—']


def build_day_pdf(parts, images, path, now):
    """Compact A4 portrait: small photo, thin rows, one heading line per zone and state."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['BodyText'], fontSize=7.5, leading=8.6)
    head = ParagraphStyle('head', parent=styles['Heading4'], fontSize=9, leading=11, spaceBefore=4, spaceAfter=1.5)
    title = ParagraphStyle('title', parent=styles['Heading1'], fontSize=15, leading=18, spaceAfter=2)
    totals = ParagraphStyle('totals', parent=styles['BodyText'], fontSize=10.5, leading=14, spaceAfter=2)
    story = []
    for number, (day, zones) in enumerate(parts.items()):
        rows = [r for z in zones for rs in z['estados'].values() for r in rs]
        counts = day_counts(rows)
        if number: story.append(PageBreak())
        story += [Paragraph('Serviço para '+day_label(day)+' · '+day.strftime('%d/%m/%Y'), title),
                  Paragraph('<b>Maquinadas: %d jantes</b> &nbsp;·&nbsp; <b>Pintadas: %d jantes</b> &nbsp;·&nbsp; <b>Total: %d jantes</b> &nbsp;·&nbsp; Outros trabalhos: %d &nbsp;·&nbsp; %d serviços'
                            % (counts['Maquinada'], counts['Pintada'], counts['Maquinada']+counts['Pintada'], counts['Outro'], len(rows)), totals),
                  Paragraph('Gerado pelo Jarvis em '+now.strftime('%d/%m/%Y %H:%M'), cell)]
        if not rows: story.append(Paragraph('Não há serviços com prazo de entrega neste dia.', totals)); continue
        for zone in zones:
            for state, label in STATES:
                items = by_client(zone['estados'][state])
                if not items: continue
                story += [CondPageBreak(25*mm), Paragraph('Zona %s · %s (%d)' % (html.escape(zone['nome']), label, len(items)), head)]
                data = [DAY_COLUMNS]
                for row in items:
                    picture = small_image(images.get(row['id']), 90)
                    data.append([Image(picture, width=9*mm, height=9*mm, kind='proportional') if picture else '—']
                                + [Paragraph(html.escape(v), cell) for v in compact_values(row)])
                table = Table(data, colWidths=[11*mm, 46*mm, 12*mm, 10*mm, 16*mm, 43*mm, 52*mm], repeatRows=1)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTSIZE', (0, 0), (-1, 0), 7), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])]))
                story.append(table)
        story.append(Spacer(1, 2*mm))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=9*mm, bottomMargin=9*mm,
                      title='Serviço por dia').build(story)


def build_day_xlsx(parts, images, path, now):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.styles import Alignment, Font, PatternFill
    book = Workbook(); first = True
    for day, zones in parts.items():
        sheet = book.active if first else book.create_sheet(); first = False
        sheet.title = day.strftime('%d-%m')
        rows = [r for z in zones for rs in z['estados'].values() for r in rs]; counts = day_counts(rows)
        sheet.append(['Serviço para '+day_label(day)+' — gerado pelo Jarvis em '+now.strftime('%d/%m/%Y %H:%M')]); sheet['A1'].font = Font(bold=True, size=13)
        sheet.append(['Maquinadas', counts['Maquinada'], 'Pintadas', counts['Pintada'], 'Total', counts['Maquinada']+counts['Pintada'], 'Outros', counts['Outro'], 'Serviços', len(rows)])
        for cell in sheet[2]: cell.font = Font(bold=True)
        sheet.append(['Zona', 'Estado']+DAY_COLUMNS+['Grupo', 'Detalhes'])
        for cell in sheet[3]: cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='1F2937')
        for width, letter in zip([22, 12, 8, 30, 9, 7, 10, 28, 30, 11, 34], 'ABCDEFGHIJK'): sheet.column_dimensions[letter].width = width
        index = 3
        for zone in zones:
            for state, label in STATES:
                for row in by_client(zone['estados'][state]):
                    index += 1
                    sheet.append([zone['nome'], label, '']+compact_values(row)+[job_group(row), row['detalhes']])
                    sheet.row_dimensions[index].height = 30
                    for cell in sheet[index]: cell.alignment = Alignment(vertical='center', wrap_text=True)
                    picture = small_image(images.get(row['id']), 38)
                    if picture:
                        image = XlImage(picture); image.anchor = 'C'+str(index); sheet.add_image(image)
        sheet.freeze_panes = 'A4'; sheet.auto_filter.ref = 'A3:K'+str(max(3, index))
    book.save(path)


def day_summary_text(result):
    lines = []
    for day, zones in result['dias'].items():
        rows = [r for z in zones for rs in z['estados'].values() for r in rs]
        if not rows: lines.append(day_label(day)+': não há serviços com prazo de entrega neste dia.'); continue
        counts = day_counts(rows)
        per_zone = ', '.join('%s %d' % (z['nome'], sum(len(rs) for rs in z['estados'].values())) for z in zones if any(z['estados'].values()))
        lines.append('%s: %d jantes maquinadas, %d pintadas, total %d; %d outros trabalhos (%d serviços). Por zona: %s.'
                     % (day_label(day), counts['Maquinada'], counts['Pintada'], counts['Maquinada']+counts['Pintada'], counts['Outro'], len(rows), per_zone))
    return '\n'.join(lines+['Lista por zona, com fotografias:', '/relatorios/'+result['pdf'], '/relatorios/'+result['excel']])


# --- Production panel: counts only (no PDF, no photos), refreshed every night ----------------
def overview_day(zones, day):
    rows_all, zone_list = [], []
    for zone in zones:
        rows = [r for rs in zone['estados'].values() for r in rs if r['prazo'][:10] == day.isoformat()]
        if not rows: continue
        counts = day_counts(rows); rows_all += rows
        zone_list.append({'zona': zone['zona'], 'nome': zone['nome'], 'servicos': len(rows), 'maquinadas': counts['Maquinada'],
                          'pintadas': counts['Pintada'], 'outros': counts['Outro'], 'total': counts['Maquinada']+counts['Pintada']})
    counts = day_counts(rows_all)
    return {'dia': day.isoformat(), 'rotulo': day_label(day), 'servicos': len(rows_all), 'maquinadas': counts['Maquinada'],
            'pintadas': counts['Pintada'], 'outros': counts['Outro'], 'total': counts['Maquinada']+counts['Pintada'], 'zonas': zone_list}


def panel_day(today, hour):
    """Which day the panel shows: today until 18:00 (not Sunday), afterwards the next working day."""
    return today if hour < 18 and today.weekday() != 6 else next_working_day(today)


def _production_overview(self, day, now=None):
    now = now or datetime.now()
    zones = self.by_zone()
    days = [day, next_working_day(day)]
    return {'gerado': now.strftime('%Y-%m-%d %H:%M'), 'dias': [overview_day(zones, d) for d in days]}


GestaoRucodel.production_overview = _production_overview


# --- Sectors from the «Gerir Tarefas» window (read only: its buttons are never pressed) -----
COLOURS = {'warning': 'amarelo', 'danger': 'vermelho', 'success': 'verde'}
ICONS = {'play': 'amarelo', 'stop': 'vermelho', 'ok': 'verde', 'check': 'verde'}


def parse_tasks(fragment):
    """[(task name, colour)] from the «Gerir Tarefas» window: amarelo (▶), vermelho (■) or verde (✓)."""
    tasks, previous = [], 0
    for match in re.finditer(r'<(?:a|button|span)\b[^>]*class="([^"]*\bbtn-(?:warning|danger|success)\b[^"]*)"[^>]*>', fragment):
        colour = COLOURS[re.search(r'\bbtn-(warning|danger|success)\b', match.group(1)).group(1)]
        texts = [html.unescape(t).strip() for t in re.findall(r'>([^<>]+)<', fragment[previous:match.start()])]
        names = [t for t in texts if t and not re.fullmatch(r'[\d.,\s]+', t)]
        previous = match.end()
        if names: tasks.append((names[-1], colour))
    if not tasks:  # layout without bootstrap colours: fall back to the icons
        for name, icon in re.findall(r'<td[^>]*>\s*([^<>]*[A-Za-zÀ-ú][^<>]*)\s*</td>.*?(?:glyphicon|fa)-(play|stop|ok|check)\b', fragment, re.S):
            tasks.append((html.unescape(name).strip(), ICONS[icon]))
    return tasks


def sector(tasks):
    """1 = before the lathe (Torno), 2 = after it. Without a Torno task: any yellow task left -> 1, otherwise 2.
    No tasks found -> None here (it can also be an expired login page); the panel then counts it as 1."""
    if not tasks: return None
    lathe = [colour for name, colour in tasks if 'torno' in fold_text(name)]
    if lathe: return 1 if lathe[0] == 'amarelo' else 2
    return 1 if any(colour == 'amarelo' for _, colour in tasks) else 2


def _sectors(self, rows):
    from concurrent.futures import ThreadPoolExecutor
    def one(row):
        if not row.get('gerir'): return row['id'], None
        try: return row['id'], sector(parse_tasks(self.get(row['gerir'])[0]))
        except (OSError, RuntimeError): return row['id'], None
    with ThreadPoolExecutor(6) as pool:
        return dict(pool.map(one, {r['id']: r for r in rows}.values()))


GestaoRucodel.sectors = _sectors


def sector_counts(rows, sectors):
    counts = {'setor1': 0, 'setor2': 0, 'sem_info': 0}
    for row in rows:
        key = 'setor2' if sectors.get(row['id']) == 2 else 'setor1'  # nothing marked / unknown = before the lathe
        counts[key] += row['quantidade'] or 1
    return counts


def _production_overview_with_sectors(self, day, now=None):
    now = now or datetime.now()
    zones = self.by_zone()
    days = [day, next_working_day(day)]
    wanted = {d.isoformat() for d in days}
    rows = [r for z in zones for rs in z['estados'].values() for r in rs if r['prazo'][:10] in wanted]
    late = late_filter(days[0])
    late_rows = [r for z in zones for s, rs in z['estados'].items() for r in rs if late(s, r)]
    sectors = self.sectors(rows + late_rows)
    result = []
    for d in days:
        item = overview_day(zones, d)
        day_rows = [r for r in rows if r['prazo'][:10] == d.isoformat()]
        item.update(sector_counts(day_rows, sectors))
        for zone_item in item['zonas']:
            zone = next(z for z in zones if z['zona'] == zone_item['zona'])
            zone_item.update(sector_counts([r for rs in zone['estados'].values() for r in rs if r['prazo'][:10] == d.isoformat()], sectors))
            # The services behind the numbers, so the big screen can list them when a box is clicked.
            zone_item['lista'] = [service_entry(r, state, sectors.get(r['id'])) for state, _ in STATES for r in by_client(zone['estados'][state]) if r['prazo'][:10] == d.isoformat()]
        result.append(item)
    behind = overview_where(zones, late, sectors)
    behind.update({'dia': '', 'atras': True, 'rotulo': 'Ficou para trás · prazo antes de ' + day_label(days[0])})
    return {'gerado': now.strftime('%Y-%m-%d %H:%M'), 'dias': result, 'atras': behind}


def late_filter(first_day):
    """Not finished (A aguardar / Em curso) and with a delivery date before the first day on the screen."""
    first = first_day.isoformat()
    return lambda state, row: state in ('aguardar', 'curso') and bool(row['prazo'][:10]) and row['prazo'][:10] < first


def overview_where(zones, keep, sectors):
    """Same totals as a day (per zone, with sectors and the list behind them), for the services keep(state, row) picks."""
    rows_all, zone_list = [], []
    for zone in zones:
        pairs = [(s, r) for s, rs in zone['estados'].items() for r in rs if keep(s, r)]
        if not pairs: continue
        rows = [r for _, r in pairs]; counts = day_counts(rows); rows_all += rows
        item = {'zona': zone['zona'], 'nome': zone['nome'], 'servicos': len(rows), 'maquinadas': counts['Maquinada'],
                'pintadas': counts['Pintada'], 'outros': counts['Outro'], 'total': counts['Maquinada']+counts['Pintada']}
        item.update(sector_counts(rows, sectors))
        item['lista'] = [service_entry(r, s, sectors.get(r['id'])) for s, _ in STATES for r in by_client([r for st, r in pairs if st == s])]
        zone_list.append(item)
    counts = day_counts(rows_all)
    out = {'servicos': len(rows_all), 'maquinadas': counts['Maquinada'], 'pintadas': counts['Pintada'], 'outros': counts['Outro'],
           'total': counts['Maquinada']+counts['Pintada'], 'zonas': zone_list}
    out.update(sector_counts(rows_all, sectors))
    return out


GestaoRucodel.production_overview = _production_overview_with_sectors


def service_entry(row, state, sector_number):
    return {'id': row['id'], 'cliente': (row['cliente_numero']+' · ' if row['cliente_numero'] else '')+row['cliente'], 'quantidade': row['quantidade'] or 1,
            'tamanho': re.sub(r'\.0+$', '', row['tamanho']), 'tipo': row['tipo'], 'cor': row['cor'], 'grupo': job_group(row),
            'entrada': row['criado'][8:10]+'/'+row['criado'][5:7], 'hora': row['prazo'][11:16], 'prazo': row['prazo'][:10], 'estado': dict(STATES)[state],
            'setor': 2 if sector_number == 2 else 1, 'imagem': row['imagem'],
            'detalhes': (row.get('detalhes') or '').strip()}


def _photo(self, path):
    """Thumbnail of a service for the big screen, through the Jarvis login (cached on this PC)."""
    if not path or not re.fullmatch(r'/img/cache/[A-Za-z0-9_-]+\.(?:jpe?g|png|gif|webp)', path): raise RuntimeError('Fotografia inválida.')
    cache = self.root/'fotos_gestao'; cache.mkdir(exist_ok=True)
    target = cache/path.rsplit('/', 1)[1]
    if target.is_file(): return target.read_bytes()
    for attempt in range(2):
        try:
            if self.opener is None or attempt: self.login()
            data = self.get(path, binary=True)
            if data[:4] in (b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\x89PNG') or data[:3] == b'\xff\xd8\xff' or data[:4] == b'RIFF' or data[:3] == b'GIF':
                target.write_bytes(data); return data
        except (OSError, RuntimeError):
            if attempt: raise
    raise RuntimeError('O programa de gestão não devolveu a fotografia.')


GestaoRucodel.photo = _photo
