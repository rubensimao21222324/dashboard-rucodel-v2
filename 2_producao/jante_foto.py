"""Identify which open service a jante belongs to, from a photo taken in the workshop.

How it works (everything stays on this PC):
- The service list (A aguardar, Em curso, Terminados, every zone) is read from the
  management site exactly as the production panel already does: read only.
- Each service photo is turned into a "visual fingerprint" by a small local image
  model (DINOv2-small, ~90 MB, runs on the CPU). Fingerprints are cached by photo
  name, so only new services are processed on each refresh.
- A new photo gets its fingerprint and is compared with all of them. Jarvis shows
  the 3 most similar services and never decides alone: a person confirms.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import threading

MODEL = 'facebook/dinov2-base'  # ~350 MB; «foto_modelo» in central_config.json to change
MAX_PIXELS = 40_000_000
TOP = 3


# --- images ----------------------------------------------------------------
def load_image(data):
    """Bytes -> RGB PIL image, rotated as the phone took it (EXIF)."""
    from PIL import Image, ImageOps
    if not data: raise ValueError('Fotografia vazia.')
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data)); image.load()
    except Exception as error:
        raise ValueError('Não consegui abrir a fotografia (usa JPG ou PNG).') from error
    image = ImageOps.exif_transpose(image)
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA'); background = Image.new('RGBA', image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    return image.convert('RGB')


def query_variants(image):
    """The whole photo and two tighter centre crops: the jante is usually in the middle, with floor or shelves around it."""
    width, height = image.size
    out = [image]
    for keep in (0.8, 0.6):
        side = int(min(width, height)*keep) if keep < 1 else min(width, height)
        left, top = (width-side)//2, (height-side)//2
        out.append(image.crop((left, top, left+side, top+side)))
    return out


# --- local image model --------------------------------------------------------
class Embedder:
    """DINOv2-small fingerprints (CLS token + mean of patches), L2-normalised.

    Pictures are prepared here with Pillow + numpy (resize, centre, ImageNet colours), so only the
    model itself comes from «transformers»: no image-processor extras (e.g. torchvision) are needed.
    torch/transformers are imported once, under a lock: importing them from two threads at the same
    time can fail with ImportError.
    """
    MEAN = (0.485, 0.456, 0.406)
    STD = (0.229, 0.224, 0.225)

    def __init__(self, model=MODEL, side=224):
        self.model_name, self.model, self.side = model, None, side
        self.lock = threading.RLock()
        self._ready = None
        self.problem = None

    def ready(self):
        if self._ready is None:
            with self.lock:
                if self._ready is None:
                    try:
                        import numpy, torch, transformers  # noqa: F401
                        self._ready = True
                    except Exception as error:
                        self._ready, self.problem = False, '%s: %s' % (type(error).__name__, error)
        return self._ready

    def load(self):
        with self.lock:
            if self.model is None:
                import torch
                from transformers import AutoModel
                torch.set_num_threads(max(2, min(8, (os.cpu_count() or 4)-2)))
                self.model = AutoModel.from_pretrained(self.model_name).eval()
        return self

    def prepare(self, image):
        import numpy as np
        from PIL import Image
        width, height = image.size
        scale = self.side/min(width, height)
        image = image.resize((max(self.side, round(width*scale)), max(self.side, round(height*scale))), Image.BICUBIC)
        width, height = image.size
        left, top = (width-self.side)//2, (height-self.side)//2
        pixels = np.asarray(image.crop((left, top, left+self.side, top+self.side)), dtype='float32')/255.0
        pixels = (pixels-np.array(self.MEAN, 'float32'))/np.array(self.STD, 'float32')
        return pixels.transpose(2, 0, 1)

    def __call__(self, images):
        import numpy as np
        with self.lock:
            self.load()
            import torch
            chunks = []
            for start in range(0, len(images), 16):
                batch = torch.from_numpy(np.stack([self.prepare(im) for im in images[start:start+16]]))
                with torch.no_grad():
                    hidden = self.model(pixel_values=batch).last_hidden_state
                chunks.append(torch.cat([hidden[:, 0], hidden[:, 1:].mean(dim=1)], dim=1).numpy().astype('float32'))
        vectors = np.concatenate(chunks) if chunks else np.zeros((0, 1), 'float32')
        return vectors/np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


# --- matching -----------------------------------------------------------------
STATE_LABELS = {'aguardar': 'A aguardar', 'curso': 'Em curso', 'terminado': 'Terminados'}
MAX_CONFIRMED = 6  # workshop photos kept per service after «É esta»


def size_number(text):
    match = re.search(r'\d{2}(?:[.,]\d)?', str(text or ''))
    return float(match.group(0).replace(',', '.')) if match else None


def index_crops(image):
    """Program photos often show several jantes, at an angle, with shelves behind: keep the whole photo,
    the centre and four overlapping corners, so the jante that matters is compared on its own."""
    width, height = image.size
    out = [image]
    side = int(min(width, height)*0.75); left, top = (width-side)//2, (height-side)//2
    out.append(image.crop((left, top, left+side, top+side)))
    side = int(min(width, height)*0.65)
    for x, y in ((0, 0), (width-side, 0), (0, height-side), (width-side, height-side)):
        out.append(image.crop((x, y, x+side, y+side)))
    return out


def confidence(scores):
    """Plain-language hint from the best score and how far ahead of the 2nd it is (cosine similarity)."""
    if not scores: return 'sem resultados'
    best, gap = scores[0], (scores[0]-scores[1] if len(scores) > 1 else 1.0)
    if best >= 0.80 and gap >= 0.04: return 'forte'
    if best >= 0.65 and gap >= 0.02: return 'média'
    if best >= 0.65: return 'várias muito parecidas: confirma pela cor, tamanho e cliente'
    return 'fraca: tira outra foto de frente, com boa luz'


def rank(query_vectors, index_vectors, owners, entries, size=None, state=None, top=TOP):
    """Each service scores the best match over all its reference pictures (program crops + confirmed workshop photos)."""
    import numpy as np
    if not len(entries) or not len(index_vectors): return []
    sims = (index_vectors @ query_vectors.T).max(axis=1)
    scores = np.full(len(entries), -1.0, dtype='float32')
    np.maximum.at(scores, owners, sims)
    wanted = size_number(size) if size else None
    label = STATE_LABELS.get(state) if state else None
    out = []
    for i in np.argsort(-scores):
        entry = entries[int(i)]
        if scores[i] < -0.5: break
        if wanted is not None and size_number(entry.get('tamanho')) != wanted: continue
        if label and entry.get('estado') != label: continue
        out.append({**entry, 'semelhanca': round(float(scores[i]), 4)})
        if len(out) == top: break
    return out


def same_client_note(found):
    names = {f.get('cliente') for f in found}
    if len(found) > 1 and len(names) == 1:
        return 'As %d hipóteses são do mesmo cliente (%s): o cliente é quase certo; confirma o serviço pela data, quantidade e estado.' % (len(found), found[0]['cliente'])
    return None


class JanteMatcher:
    def __init__(self, root, gestao, settings, embedder=None):
        self.root, self.gestao, self.settings = Path(root), gestao, settings
        self.folder = self.root/'jantes_fotos'
        self.embedder = embedder or Embedder(settings.get('foto_modelo', MODEL))
        self.lock = threading.Lock()
        self.confirm_lock = threading.Lock()
        self.error = None
        self._loaded = None

    # files (fingerprints depend on the model: changing it rebuilds them once)
    def index_file(self): return self.folder/'indice.json'
    def vector_file(self):
        slug = re.sub(r'[^a-z0-9]+', '_', str(getattr(self.embedder, 'model_name', 'modelo')).lower()).strip('_')
        return self.folder/('vetores_%s.npz' % slug)
    def confirmed_file(self): return self.folder/(self.vector_file().stem.replace('vetores_', 'confirmadas_')+'.npz')
    def log_file(self): return self.folder/'confirmacoes.jsonl'

    @staticmethod
    def read_npz(path):
        import numpy as np
        if not path.is_file(): return {}
        with np.load(path) as data:
            return {key: data[key] for key in data.files}

    @staticmethod
    def write_npz(path, values):
        import numpy as np
        path.parent.mkdir(exist_ok=True)
        temp = path.with_name(path.stem+'.tmp.npz')
        np.savez(temp, **values); os.replace(temp, path)

    def cached_vectors(self): return self.read_npz(self.vector_file())

    def load(self):
        import numpy as np
        path = self.index_file()
        if not path.is_file(): return [], np.zeros((0, 1), 'float32'), np.zeros(0, int), None
        stamps = (path.stat().st_mtime, self.vector_file().stat().st_mtime if self.vector_file().is_file() else 0,
                  self.confirmed_file().stat().st_mtime if self.confirmed_file().is_file() else 0)
        if self._loaded and self._loaded[0] == stamps: return self._loaded[1:]
        data = json.loads(path.read_text(encoding='utf-8'))
        cache, confirmed = self.cached_vectors(), self.read_npz(self.confirmed_file())
        by_photo, by_service = {}, {}
        for key, vector in cache.items(): by_photo.setdefault(key.split('#')[0], []).append(vector)
        for key, vector in confirmed.items(): by_service.setdefault(key.split('#')[0], []).append(vector)
        entries, rows, owners = [], [], []
        for entry in data['servicos']:
            refs = by_photo.get(entry['foto'], [])+by_service.get(entry['id'], [])
            if not refs: continue
            entry = {**entry, 'aprendidas': len(by_service.get(entry['id'], []))}
            rows += refs; owners += [len(entries)]*len(refs); entries.append(entry)
        vectors = np.stack(rows).astype('float32') if rows else np.zeros((0, 1), 'float32')
        self._loaded = (stamps, entries, vectors, np.array(owners, int), data.get('gerado'))
        return self._loaded[1:]

    def accuracy(self):
        """From the «É esta» / «Nenhuma» buttons: how often the right service was 1st, in the top 3, or missing."""
        counts = {'confirmacoes': 0, 'em_1o': 0, 'no_top3': 0, 'nenhuma': 0}
        try:
            for line in self.log_file().read_text(encoding='utf-8').splitlines()[-500:]:
                item = json.loads(line); counts['confirmacoes'] += 1
                if item.get('posicao') == 1: counts['em_1o'] += 1
                if item.get('posicao') in (1, 2, 3): counts['no_top3'] += 1
                if item.get('posicao') == 0: counts['nenhuma'] += 1
        except (OSError, ValueError): pass
        return counts

    def status(self):
        path = self.index_file()
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        return {'disponivel': self.embedder.ready(), 'problema': getattr(self.embedder, 'problem', None), 'configurado': self.gestao.configured(),
                'servicos': data.get('total', 0), 'com_foto': len(data.get('servicos', [])), 'gerado': data.get('gerado'),
                'a_atualizar': self.lock.locked(), 'erro': self.error, 'acertos': self.accuracy()}

    def age(self, now=None):
        data = self.status()
        if not data['gerado']: return None
        return (now or datetime.now())-datetime.strptime(data['gerado'], '%Y-%m-%d %H:%M')

    # build
    def rebuild(self, now=None):
        """Read every open service with a photo and fingerprint the new photos (6 crops each). Only reads the site."""
        if not self.embedder.ready():
            raise RuntimeError('A identificação por foto ainda não está instalada neste PC. Corre INSTALAR_JARVIS.cmd.')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('As fotografias dos serviços já estão a ser atualizadas. Aguarda um pouco.')
        try:
            now = now or datetime.now()
            zones = self.gestao.by_zone()
            services, seen = [], set()
            from gestao_rucodel import STATES, service_entry
            for zone in zones:
                for state, _ in STATES:
                    for row in zone['estados'][state]:
                        if row['id'] in seen: continue
                        seen.add(row['id'])
                        item = service_entry(row, state, None)
                        item.update({'zona': zone['nome'], 'prazo': row['prazo'][:10], 'foto': (row['imagem'] or '').rsplit('/', 1)[-1]})
                        services.append(item)
            with_photo = [s for s in services if s['imagem']]
            cache = self.cached_vectors()
            done = {key.split('#')[0] for key in cache}
            missing = [s for s in with_photo if s['foto'] not in done]

            def fetch(service):
                try: return service, self.gestao.photo(service['imagem'])
                except (OSError, RuntimeError): return service, None
            if missing and hasattr(self.gestao, 'ensure_login'):
                try: self.gestao.ensure_login()  # one login before the parallel downloads
                except (OSError, RuntimeError): pass
            with ThreadPoolExecutor(6) as pool:
                photos = [(s, data) for s, data in pool.map(fetch, missing) if data]
            for start in range(0, len(photos), 20):  # small batches: the panel stays responsive
                images, names = [], []
                for service, data in photos[start:start+20]:
                    try:
                        crops = index_crops(load_image(data))
                        images += crops; names += ['%s#%d' % (service['foto'], k) for k in range(len(crops))]
                    except ValueError: pass
                if images:
                    for name, vector in zip(names, self.embedder(images)): cache[name] = vector
            wanted = {s['foto'] for s in with_photo}
            kept = {k: v for k, v in cache.items() if k.split('#')[0] in wanted}
            indexed = [s for s in with_photo if '%s#0' % s['foto'] in kept]
            self.write_npz(self.vector_file(), kept)
            ids = {s['id'] for s in services}
            with self.confirm_lock:
                confirmed = self.read_npz(self.confirmed_file())
                if any(k.split('#')[0] not in ids for k in confirmed):
                    self.write_npz(self.confirmed_file(), {k: v for k, v in confirmed.items() if k.split('#')[0] in ids})
            data = {'gerado': now.strftime('%Y-%m-%d %H:%M'), 'total': len(services), 'servicos': indexed}
            temp = self.index_file().with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8'); os.replace(temp, self.index_file())
            self.error = None; self._loaded = None
            return self.status()
        except Exception as error:
            self.error = str(error) if isinstance(error, RuntimeError) else 'A atualização das fotografias falhou (%s: %s).' % (type(error).__name__, str(error)[:200])
            raise
        finally:
            self.lock.release()

    # search
    def identify(self, data, size=None, state=None):
        if not self.embedder.ready():
            raise RuntimeError('A identificação por foto ainda não está instalada neste PC. Corre INSTALAR_JARVIS.cmd.')
        entries, vectors, owners, generated = self.load()
        if not entries:
            raise RuntimeError('Ainda não há fotografias dos serviços. Carrega em «Atualizar fotos» (a primeira vez demora alguns minutos).')
        if state and state not in STATE_LABELS: raise ValueError('Estado desconhecido.')
        query = self.embedder(query_variants(load_image(data)))
        found = rank(query, vectors, owners, entries, size, state)
        if (size or state) and not found:
            raise RuntimeError('Nenhum serviço em aberto com esse filtro. Escolhe «Todos» e tenta de novo.')
        return {'hipoteses': found, 'confianca': confidence([f['semelhanca'] for f in found]),
                'nota': same_client_note(found), 'comparadas': len(entries), 'indice': generated}

    # learning from the person's confirmation
    def confirm(self, data, service_id, position, score=None):
        """«É esta»: the workshop photo becomes one more reference of that service. «Nenhuma» (position 0) only counts a miss."""
        if not re.fullmatch(r'[A-Za-z0-9:_ -]{1,64}', str(service_id or '')) and position != 0: raise ValueError('Serviço inválido.')
        position = int(position)
        if not 0 <= position <= TOP: raise ValueError('Posição inválida.')
        if position:
            entries = self.load()[0]
            if not any(e['id'] == service_id for e in entries): raise ValueError('Esse serviço já não está em aberto.')
            vector = self.embedder([load_image(data)])[0]
            with self.confirm_lock:
                confirmed = self.read_npz(self.confirmed_file())
                mine = sorted(k for k in confirmed if k.split('#')[0] == service_id)
                for old in mine[:max(0, len(mine)-MAX_CONFIRMED+1)]: confirmed.pop(old)
                confirmed['%s#%s' % (service_id, datetime.now().strftime('%Y%m%d%H%M%S%f'))] = vector
                self.write_npz(self.confirmed_file(), confirmed)
            self._loaded = None
        self.folder.mkdir(exist_ok=True)
        with self.confirm_lock, open(self.log_file(), 'a', encoding='utf-8') as log:
            log.write(json.dumps({'quando': datetime.now().strftime('%Y-%m-%d %H:%M'), 'posicao': position,
                                  'semelhanca': score if isinstance(score, (int, float)) else None})+'\n')
        return {'ok': True, 'acertos': self.accuracy()}


def photo_schedule(matcher, clock=None, sleep=None, runs=None):
    """Keep the fingerprints fresh: every «fotos_intervalo_horas» (default 2) between 05:00 and 22:00."""
    import time
    clock = clock or datetime.now
    sleep = sleep or time.sleep
    count = 0
    while runs is None or count < runs:
        now = clock(); hours = float(matcher.settings.get('fotos_intervalo_horas', 2))
        age = matcher.age(now)
        if matcher.gestao.configured() and matcher.embedder.ready() and 5 <= now.hour < 22 and (age is None or age >= timedelta(hours=hours)):
            count += 1
            try: matcher.rebuild(); print('Fotografias dos serviços atualizadas.', flush=True)
            except Exception as error:
                print('Fotografias dos serviços não atualizadas: '+(str(error) if isinstance(error, RuntimeError) else type(error).__name__), flush=True)
                sleep(15*60)  # do not hammer the site after a failure
        sleep(60)
