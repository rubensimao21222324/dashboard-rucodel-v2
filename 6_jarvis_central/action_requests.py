"""Local scheduling requests: extract independent slots, then validate before writing.

No model, document or old assistant message can authorize an action. Only a
direct user request (or a reply to our own short-lived question) is executed.

Patch 2: recognition uses a folded copy of the text, but every title is cut
from the original text (accents, names, quantities and punctuation kept).
Numbers are classified as hours, values or quantities before any question,
and questions are asked only for a real, named doubt.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
import json
import re
import threading
import time
import unicodedata


def fold_map(text):
    """Lowercase, accent-free copy plus the original index of every folded char."""
    folded, index = [], []
    for position, char in enumerate(text):
        for part in unicodedata.normalize('NFD', char.lower()):
            if not unicodedata.combining(part):
                folded.append(part); index.append(position)
    index.append(len(text))
    return ''.join(folded), index


def fold(value):
    return fold_map(value)[0]


PREFIX = re.compile(r'^\s*(?:jarvis\s*[,!:]?\s*)?(?:por favor[,\s]*)?'
    r'(?:(?:podes|consegues|podias|poderias)\s+(?:me\s+)?|'
    r'(?:quero|queria|preciso|gostava)\s+que\s+(?:me\s+)?)?'
    r'(?:(?:marca(?:r|s)?|agenda(?:r|s)?|aponta(?:r|s)?|regista(?:r|s)?|'
    r'adiciona(?:r|s)?|cria(?:r|s)?|guarda(?:r|s)?|poe|pores|ponhas|mete(?:r|s)?)(?:-me)?|'
    r'lembra(?:r)?-me)\b[\s,:]*')
DEST = re.compile(r'\b(?:no|na|ao|a|para o|para a|na minha|no meu)\s+'
    r'(?:(?:agenda|calendario|diario|lista)\s+(?:do |da |de )?)?'
    r'(notion|noteit|note it|google(?: calendar| agenda)?|lista local|jarvis)\b')
WEEKDAYS = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
WEEKDAY_NAMES = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
DAY = re.compile(r'\b(?:depois de amanha|anteontem|amanha|hoje|ontem|'
    r'daqui a \d{1,3} dias?|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?|'
    r'(?:(?:proxima|proximo|nesta|neste|esta|este)\s+)?(?:segunda|terca|quarta|quinta|sexta)'
    r'(?:-feira)?|(?:(?:proximo|proxima|neste|nesta|este|esta)\s+)?(?:sabado|domingo))\b')
HOUR = r'(?:\d{1,2}(?:[:.]\d{2}|h\d{0,2})?|meio[- ]dia|meia[- ]noite|'
HOUR += r'uma|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze)'
TIME = re.compile(r'\b(?:as|das|pelas|ate as)\s+('+HOUR+r')'
    r'(?:\s+e\s+(meia|um quarto))?'
    r'(?:\s+(?:da|de)\s+(manha|tarde|noite|madrugada))?\b|'
    r'\b(\d{1,2}(?:[:.]\d{2}|h\d{0,2}))\b|'
    r'\b(?:a|ao|ate a|ate ao)\s+(meio[- ]dia|meia[- ]noite)\b')  # «à meia-noite», «ao meio-dia»
# Durations: «durante 2h», «com a duração de 1 hora», «por meia hora», «que dura 45 minutos».
DURATION = re.compile(r'\b(?:(?:com\s+(?:a\s+)?|de\s+)?duracao\s+de|durante|que\s+dura|por)\s+'
    r'(\d{1,3}|uma|duas|tres|meia)\s*(minutos?|min|horas?|h)\b')
def duration_minutes(match):
    amount, unit = match[1], match[2]
    if amount == 'meia': return 30 if unit.startswith('h') else 0
    number = {'uma': 1, 'duas': 2, 'tres': 3}.get(amount) or int(amount)
    return number*(60 if unit.startswith('h') else 1)
def hhmm(minutes):
    return f'{(minutes % 1440)//60:02d}:{minutes % 60:02d}'
NUMBERS = {'uma':1, 'duas':2, 'tres':3, 'quatro':4, 'cinco':5, 'seis':6,
           'sete':7, 'oito':8, 'nove':9, 'dez':10, 'onze':11, 'doze':12}
# A number followed by one of these is a value or quantity, never an hour.
UNIT = re.compile(r'\s*(?:€|euros?\b|eur\b|centimos?\b|%|por cento\b|jantes?\b|pneus?\b|rodas?\b|'
    r'pecas?\b|unidades?\b|kg\b|quilos?\b|litros?\b|metros?\b|km\b|pessoas?\b|carros?\b|'
    r'caixas?\b|paletes?\b|vezes\b|dias?\b|semanas?\b|meses\b|anos?\b|minutos?\b)')
PRICE_BEFORE = re.compile(r'\b(?:por|de|custa|custou|valor|preco|paga|pagar|paguei)\s+$')
# Scheduling glue directly before a removed date/hour/destination.
GLUE = re.compile(r'\b(?:para o dia|para a|para o|no dia|para|dia|no|na|de|a|o|e|ou|ate|pelas)\s+$')
CANCEL = ('cancela', 'cancelar', 'esquece', 'deixa estar', 'nao', 'nao marques', 'nao quero')
QUESTION_START = re.compile(r'(?:que|qual|quais|como|quando|onde|porque|quem|quanto|quantos|quantas|o que)\b')


def parse_day(value, today):
    value = fold(value).strip(' .!?')
    offsets = {'hoje':0, 'amanha':1, 'depois de amanha':2, 'ontem':-1, 'anteontem':-2}
    if value in offsets: return (today+timedelta(days=offsets[value])).isoformat()
    match = re.fullmatch(r'daqui a (\d{1,3}) dias?', value)
    if match: return (today+timedelta(days=int(match[1]))).isoformat()
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', value)
    if match:
        day, month = int(match[1]), int(match[2])
        if match[3]: return date(int(match[3]), month, day).isoformat()  # explicit year: never changed
        # No year: the next valid occurrence that has not passed yet.
        for year in (today.year, today.year+1):
            try: candidate = date(year, month, day)
            except ValueError: continue
            if candidate >= today: return candidate.isoformat()
        raise ValueError('Essa data não é válida.')
    prefix = re.match(r'(proxima|proximo|nesta|neste|esta|este)\s+', value)
    weekday = value[prefix.end():] if prefix else value
    weekday = weekday.replace('-feira', '')
    if weekday in WEEKDAYS:
        offset = (WEEKDAYS.index(weekday)-today.weekday()) % 7
        if prefix and prefix[1] in ('proxima', 'proximo'): offset = offset or 7
        elif not prefix: offset = offset or 7  # same weekday as today: resolved by the caller
        return (today+timedelta(days=offset)).isoformat()
    return date.fromisoformat(value).isoformat()


def bare_weekday_today(value, today):
    value = fold(value).replace('-feira', '')
    return value in WEEKDAYS and WEEKDAYS.index(value) == today.weekday()


def parse_hour(value):
    match = TIME.fullmatch(fold(value).strip(' .!?'))
    if not match: raise ValueError('Indica a hora, por exemplo às 9h ou às 21:30.')
    hour, fraction, period = match[1] or match[4] or match[5], match[2], match[3]
    minute = 0
    hour = hour.replace(' ', '-')
    if hour == 'meio-dia': hour = 12
    elif hour == 'meia-noite': hour = 0
    elif hour in NUMBERS: hour = NUMBERS[hour]
    else:
        parts = re.split(r'[:.h]', hour)
        hour, minute = int(parts[0]), int(parts[1]) if len(parts)>1 and parts[1] else 0
    if fraction:
        if minute: raise ValueError('A hora tem duas indicações de minutos. Qual é a correta?')
        minute = 30 if fraction == 'meia' else 15
    if not 0 <= hour <= 23 or not 0 <= minute <= 59: raise ValueError('Essa hora não é válida. Qual é a hora correta?')
    if period:
        if hour > 12: raise ValueError('Confirma a hora usando o formato de 24 horas.')
        if period in ('tarde','noite') and hour < 12: hour += 12
        if period == 'noite' and hour == 12: hour = 0
    return f'{hour:02d}:{minute:02d}'


def am_pm_doubt(value):
    """True for 1–7 without «da manhã/tarde» and without a leading zero (07:00 is explicit)."""
    match = TIME.fullmatch(fold(value).strip(' .!?'))
    if not match or match[3]: return False
    token = (match[1] or match[4] or match[5]).replace(' ', '-')
    if token in ('meio-dia', 'meia-noite'): return False
    if token in NUMBERS: number = NUMBERS[token]
    else:
        if token.startswith('0'): return False
        number = int(re.split(r'[:.h]', token)[0])
    return 1 <= number <= 7


def plus12(value):
    hour, minute = map(int, value.split(':'))
    return f'{hour+12:02d}:{minute:02d}'


def short_date(iso):
    day = date.fromisoformat(iso)
    return day.strftime('%d/%m')


@dataclass
class Plan:
    destination: str | None = None
    day: str | None = None
    title: str = ''
    start: str | None = None
    end: str | None = None
    field: str | None = None
    question: str | None = None
    choices: tuple | None = None   # ((regex on the folded reply, {slot: value}), ...)
    queue: tuple = ()              # further (question, field, choices) still to ask
    end_next: bool = False         # the end is on the following day (e.g. 23:00–00:00)


def complete(plan):
    # Clarifications concern missing information, never a command template.
    if plan.question: return plan
    if plan.queue:
        (question, field, choices), rest = plan.queue[0], plan.queue[1:]
        return replace(plan, question=question, field=field, choices=choices, queue=rest)
    if not plan.destination: return replace(plan, field='destination', question='Queres guardar isso no Diário do Notion ou na Google Agenda?')
    if not plan.day: return replace(plan, field='day', question='Para que dia queres marcar?')
    if not plan.title: return replace(plan, field='title', question='O que queres marcar?')
    if plan.start and plan.end and plan.end <= plan.start and not plan.end_next:
        # Midnight, or a night interval such as 22:00–02:00, ends the next day.
        if plan.end == '00:00' or (plan.start >= '18:00' and plan.end <= '06:00'):
            plan = replace(plan, end_next=True)
        else:
            return replace(plan, field='end', question=f'O fim ({plan.end}) fica antes do início ({plan.start}). A que horas termina?')
    if plan.destination == 'google':
        if not plan.start: return replace(plan, field='start', question='A que horas começa?')
        if not plan.end: return replace(plan, field='end', question='A que horas termina, ou quanto tempo dura?')
    return plan


def build_title(header, normal, index, spans):
    """Cut the removed spans (plus glue right before them) out of the ORIGINAL text."""
    removed = [False]*len(header)
    for start, end in spans:
        while True:
            glue = GLUE.search(normal[:start])
            if not glue: break
            start = glue.start()
        for position in range(index[start], index[end]): removed[position] = True
    title = ''.join(char if not removed[i] else ' ' for i, char in enumerate(header))
    title = ' '.join(title.split())
    title = re.sub(r'\s+([,;:.!?])', r'\1', title)
    title = re.sub(r'([,;:])(?:\s*[,;:])+', r'\1', title)
    title = title.strip(' ,:;.!?')
    title = re.sub(r'[\s,]+por favor$', '', title, flags=re.I).strip(' ,:;.!?')
    return title


def extract(header, literal, today, now=None, *, reminder=False):
    """Slots and title from one piece of text. Returns (plan, issues)."""
    normal, index = fold_map(header)
    spans, targets, issues = [], set(), []
    def flag(question, field, choices=None): issues.append((question, field, choices))
    for match in DEST.finditer(normal):
        value = match[1]
        targets.add('notion' if value in ('notion','noteit','note it') else 'local' if value in ('lista local','jarvis') else 'google')
        spans.append(match.span())
    leading = re.match(r'^(?:(?:a |o )?(?:minha |meu )?(?:agenda|diario|calendario)\s+(?:do |da |de )?)?(notion|noteit|note it|google calendar|google agenda)\b', normal)
    if leading:
        targets.add('notion' if leading[1] in ('notion','noteit','note it') else 'google'); spans.append(leading.span())
    destination = None
    if len(targets)>1: flag('Queres criar no Notion ou na Google Agenda? Indicaste mais de um destino; ainda não criei nada.', 'destination')
    elif targets == {'local'}: flag('As tarefas locais não têm agenda com datas. Queres guardar esta tarefa no Notion ou criar um evento na Google Agenda?', 'destination')
    else: destination = next(iter(targets), None)
    noun = re.match(r'^(?:(?:uma|a|um|o)\s+)?(?:tarefa|lembrete|evento|compromisso)\b', normal)
    if noun:
        spans.append(noun.span())
        if not destination and not targets: destination = 'google' if re.search(r'\b(?:evento|compromisso)\b', noun[0]) else 'notion'
    if not destination and not targets and re.search(r'\b(?:no|na|ao)\s+(?:meu |minha )?diario\b', normal): destination = 'notion'
    plan = Plan(destination=destination)

    # Dates. A vague period only counts as a date when it works as one
    # («na próxima semana»); «a reunião da próxima semana» stays in the title.
    vague = re.search(r'\b(?:na|para a|ate a)\s+(?:proxima semana|semana que vem)\b|\b(?:no|para o|ate o)\s+proximo mes\b', normal)
    if vague: spans.append(vague.span())
    dates = [m for m in DAY.finditer(normal) if not any(a <= m.start() < b for a, b in spans)]
    spans.extend(m.span() for m in dates)
    resolved, same_weekday = set(), None
    try:
        for match in dates:
            if bare_weekday_today(match[0], today): same_weekday = match
            else: resolved.add(parse_day(match[0], today))
    except ValueError:
        resolved = set(); same_weekday = None; flag('Essa data não é válida. Para que dia queres marcar?', 'day')
    if len(resolved) + (same_weekday is not None) > 1:
        resolved = set(); same_weekday = None; flag('Indicaste mais de um dia. Qual é a data certa?', 'day')
    elif resolved: plan.day = resolved.pop()
    if vague:
        plan.day = None; same_weekday = None; flag('Qual é o dia exato em que queres marcar?', 'day')

    # A duration («durante 2h») is never read as a second hour.
    duration = DURATION.search(normal)
    if duration: spans.append(duration.span())
    # Hours. Values («12.50 euros») and quantities («das 4 jantes») are not hours.
    hours, value_doubt = [], None
    for match in TIME.finditer(normal):
        if any(a <= match.start() < b for a, b in spans): continue
        after, before = normal[match.end():], normal[:match.start()]
        token = match[1] or match[4] or match[5]
        if match[4] and '.' in token:
            if UNIT.match(after) or PRICE_BEFORE.search(before): continue
            try: as_hour = parse_hour(token)
            except ValueError: continue
            if value_doubt is None: value_doubt = (match, as_hour)
            continue
        if match[1] and not match[2] and not match[3] and token.isdigit() and UNIT.match(after): continue
        hours.append(match)
    spans.extend(m.span() for m in hours)

    def hour_issue():
        for marker in re.finditer(r'\b(?:as|das|pelas)\s+[-+]?(\d+)', normal):
            covered = next((m for m in hours if m.start() <= marker.start() < m.end()), None)
            if covered is not None:
                if re.match(r'[:.]\d|h\d', normal[covered.end():]): return 'Não consegui confirmar essa hora. Qual é a hora correta?'
                continue
            if len(marker[1]) >= 3 or UNIT.match(normal[marker.end():]): continue  # quantity
            return 'Não consegui confirmar essa hora. Qual é a hora correta?'
        if len(hours)>2: return 'Indicaste vários horários. Qual é o início e o fim?'
        alternative = re.match(r'\s+ou\s+(?:as\s+|ao\s+|a\s+|pelas\s+)?(?:\d{1,2}(?:[:.h]\d{0,2})?|meio-dia|meia-noite)', normal[hours[0].end():]) if hours else None
        if alternative:
            spans.append((hours[0].end(), hours[0].end()+alternative.end()))  # keep the alternative out of the title
            return 'Qual das horas queres usar? Ainda não criei nada.'
        if len(hours)==2 and not re.fullmatch(r'\s*(?:a|ate|-|e)?\s*', normal[hours[0].end():hours[1].start()]):
            return 'Queres um intervalo ou uma única hora? Indica o início e o fim.'
        return None
    problem = hour_issue()
    if problem: flag(problem, 'start')
    else:
        try:
            if hours: plan.start = parse_hour(hours[0][0])
        except ValueError as error: flag(str(error), 'start')
        try:
            if len(hours)==2 and plan.start: plan.end = parse_hour(hours[1][0])
        except ValueError as error: flag(str(error), 'end')
    # «às 3» can be 03:00 or 15:00: ask, naming both options.
    if plan.start and am_pm_doubt(hours[0][0]):
        start, end = plan.start, plan.end
        if not end: options = [{'start': start}, {'start': plus12(start)}]
        elif am_pm_doubt(hours[1][0]): options = [{'start': start, 'end': end}, {'start': plus12(start), 'end': plus12(end)}]
        else: options = [o for o in ({'start': start, 'end': end}, {'start': plus12(start), 'end': end}) if o['start'] < o['end']]
        if len(options) == 1: plan.start, plan.end = options[0]['start'], options[0]['end']
        elif options:
            plan.start = plan.end = None
            text = ' ou '.join(('das '+o['start']+' às '+o['end']) if 'end' in o else ('às '+o['start']) for o in options)
            flag('É '+text+'?', 'start', ((r'\b(?:manha|madrugada)\b', options[0]), (r'\b(?:tarde|noite)\b', options[1])))
    elif plan.start and plan.end and len(hours) == 2 and am_pm_doubt(hours[1][0]) and plan.end <= plan.start < plus12(plan.end):
        plan.end = plus12(plan.end)  # «das 11h às 2» ends at 14:00

    if duration:
        if plan.start and not plan.end:
            minutes = duration_minutes(duration)
            h, m = map(int, plan.start.split(':')); end = h*60+m+minutes
            if not 0 < minutes < 1440: flag('Essa duração não é válida. Quanto tempo dura, ou a que horas termina?', 'end')
            else: plan.end, plan.end_next = hhmm(end), end >= 1440

    # Same weekday as today: today if the hour is still ahead, otherwise ask.
    if same_weekday is not None:
        next_week = (today+timedelta(days=7)).isoformat()
        if plan.start and now and plan.start > now: plan.day = today.isoformat()
        else:
            name = WEEKDAY_NAMES[today.weekday()]
            this, other = ('esta', 'a próxima') if today.weekday() < 5 else ('este', 'o próximo')
            flag(f'Queres {this} {name} ({short_date(today.isoformat())}) ou {other} ({short_date(next_week)})?', 'day',
                 ((r'\b(?:esta|este|nesta|neste|hoje|desta|deste)\b', {'day': today.isoformat()}),
                  (r'\b(?:proxim[oa]|seguinte|outr[oa]|que vem)\b', {'day': next_week})))

    if literal is not None: plan.title = literal
    else:
        plan.title = build_title(header, normal, index, spans)
        if reminder: plan.title = re.sub(r'^(?:de|que)\s+', '', plan.title, flags=re.I)
        if value_doubt:
            match, as_hour = value_doubt
            without = build_title(header, normal, index, spans+[match.span()])
            if reminder: without = re.sub(r'^(?:de|que)\s+', '', without, flags=re.I)
            shown = header[index[match.start()]:index[match.end()]]
            if plan.start:
                pass  # an explicit hour already exists: the number is part of the description
            else:
                flag(f'«{shown}» é a hora ({as_hour}) ou faz parte da descrição?', 'start',
                     ((r'\b(?:descricao|titulo|valor|preco|euros?|quantidade|parte|nao e hora)\b', {'title': plan.title}),
                      (r'\bhora\b|^(?:as\s+)?'+re.escape(fold(shown))+r'$|^'+as_hour+r'$', {'start': as_hour, 'title': without})))
    if len(plan.title)>1500:
        plan.title = ''; flag('A descrição é demasiado longa. Qual é o título curto da tarefa?', 'title')
    return plan, issues


def with_issues(plan, issues):
    if not issues: return complete(plan)
    (question, field, choices), rest = issues[0], tuple(issues[1:])
    return replace(plan, question=question, field=field, choices=choices, queue=rest)


def parse_request(text, today, now=None):
    text = unicodedata.normalize('NFC', text)
    normal = fold(text)
    prefix = PREFIX.match(normal)
    if not prefix: return None
    reminder = 'lembra' in prefix[0]
    body = text[fold_map(text)[1][prefix.end()]:].strip()
    source = fold(body)
    if not re.search(r'\b(?:notion|noteit|note it|agenda|calendario|diario|tarefa|evento|compromisso|lembrete|hoje|amanha|\d{4}-\d{2}-\d{2})\b', source) \
            and not (reminder and DAY.search(source)):
        return None
    if re.search(r'\b(?:sem executar|nao executes|nao cries|nao marques|nao guardes|nao registes|apenas um exemplo|so um exemplo)\b', source):
        return Plan(question='Entendido. Não executei a criação de nenhum registo.')
    if re.search(r'\b(?:todos os|todas as|cada|semanalmente|diariamente)\b', source):
        # Not kept as a pending request: a reply with only a day would lose the rest.
        return Plan(question='Este pedido é recorrente. Ainda só consigo criar uma ocorrência de cada vez. Diz-me o pedido completo para o primeiro dia; não criei nada.')
    # A colon after the scheduling header makes the description literal.
    delimiter = re.search(r'(?<!\d):\s+', body)
    literal = body[delimiter.end():].strip() if delimiter else None
    header = body[:delimiter.start()] if delimiter else body
    # Only the scheduling part can contain a second action; a literal description cannot.
    if re.search(r'\b(?:e|depois|tambem)\s+(?:marca|cria|apaga|elimina|altera|muda|agenda|envia)\b', fold(header)):
        return Plan(question='Vejo mais de uma ação nesse pedido. Qual queres tratar primeiro? Nenhuma foi executada.')
    plan, issues = extract(header, literal, today, now, reminder=reminder)
    return with_issues(plan, issues)


class ActionRequests:
    def __init__(self):
        self.pending = {}
        self.lock = threading.Lock()

    @staticmethod
    def key(messages):
        compact=[{'role':m.get('role'),'content':m.get('content')} for m in messages[-6:]]
        return hashlib.sha256(json.dumps(compact,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    @staticmethod
    def continue_plan(previous, text, today, now=None):
        """Apply a reply to our own question; None means the user changed subject."""
        value = fold(text).strip(' .!?')
        if value in CANCEL: return Plan(question='Pedido cancelado. Não criei nenhum registo.')
        field = previous.field
        short = len(value) <= 40
        questionlike = text.strip().endswith('?') or bool(QUESTION_START.match(value))
        plan = replace(previous, question=None, field=None, choices=None)
        for pattern, slots in previous.choices or ():
            if re.search(pattern, value):
                for name, slot in slots.items(): setattr(plan, name, slot)
                return complete(plan)
        if field == 'title':
            if questionlike or not 0 < len(text.strip()) <= 1500: return None
        found, issues = extract(text, None, today, now)
        got = False
        if field == 'destination':
            if found.destination: plan.destination, got = found.destination, True
            else:
                notion = bool(re.search(r'\b(?:notion|noteit|note it|diario)\b', value))
                google = bool(re.search(r'\b(?:google|calendario)\b', value)) or (not notion and bool(re.search(r'\bagenda\b', value)))
                if notion != google: plan.destination, got = ('notion' if notion else 'google'), True
        elif field == 'day':
            if found.day: plan.day, got = found.day, True
        elif field in ('start', 'end'):
            duration = re.fullmatch(r'(?:(?:a |com a )?duracao (?:e |de )|dura |durante |por )?(\d{1,3}|uma|duas|tres|meia)\s*(minutos?|min|horas?|h)', value)
            # «10h» after a 09:00 start is an end time; «2h» (before the start) or «2 horas» is a duration.
            if duration and duration[2] == 'h' and not value.startswith(('dura', 'durante')) \
                    and found.start and plan.start and found.start > plan.start:
                duration = None
            if field == 'end' and duration and plan.start:
                h, m = map(int, plan.start.split(':')); minutes = duration_minutes(duration); end = h*60+m+minutes
                if 0 < minutes < 1440: plan.end, plan.end_next, got = hhmm(end), end >= 1440, True
                else: issues = [('Essa duração não é válida. Quanto tempo dura, ou a que horas termina?', 'end', None)]
            elif found.start:
                plan.end_next = False  # recomputed by complete() for midnight/night intervals
                if found.end: plan.start, plan.end, plan.end_next = found.start, found.end, found.end_next
                elif field == 'start':
                    plan.start = found.start
                    if plan.end and plan.end <= plan.start: plan.end = None
                else: plan.end = found.start
                got = True
            elif re.fullmatch(r'\d{1,2}(?:[:.h]\d{2})?|'+HOUR, value):
                try: setattr(plan, field, parse_hour('as '+value)); plan.end_next = False; got = True
                except ValueError as error: issues = [(str(error), field, None)]
        elif field == 'title':
            plan.title, got = found.title, bool(found.title)
        else: return None
        # Corrections in the same reply («às 10h, mas na sexta») replace those slots.
        corrected = False
        if found.destination and field != 'destination': plan.destination = found.destination; corrected = True
        if found.day and field != 'day': plan.day = found.day; corrected = True
        if found.start and field not in ('start', 'end', 'title'):
            plan.start, plan.end = found.start, found.end or plan.end; corrected = True
        if field == 'title' and found.start: plan.start, plan.end = found.start, found.end or plan.end
        if got: return complete(plan)
        if issues and (short or corrected):
            question, ask_field, choices = issues[0]
            return replace(plan, question=question, field=ask_field, choices=choices)
        if questionlike or not short: return None
        # A short reply we cannot read repeats the same question with the request kept.
        return replace(plan, question=previous.question, field=field, choices=previous.choices)

    def interpret(self, messages, today, now=None):
        text=unicodedata.normalize('NFC', messages[-1]['content'])
        with self.lock:
            moment=time.monotonic()
            self.pending={k:v for k,v in self.pending.items() if moment-v[0]<600}
            previous=self.pending.pop(self.key(messages[:-1]),None)
        plan=parse_request(text,today,now)
        if plan is None and previous:
            plan=self.continue_plan(previous[1],text,today,now)
        if plan and plan.question and plan.field:
            with self.lock:
                if len(self.pending)>=64: self.pending.pop(next(iter(self.pending)))
                key=self.key(messages+[{'role':'assistant','content':plan.question}])
                self.pending[key]=(time.monotonic(),plan)
        return plan
