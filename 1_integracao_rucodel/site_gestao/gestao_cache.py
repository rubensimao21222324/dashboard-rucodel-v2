"""Faster answers from the management site: Jarvis reads it in the background and answers from that reading.

- Every «gestao_intervalo_min» minutes (default 10) between 05:00 and 22:00, a separate session reads
  the zones/states lists and «Fora de Prazo» (read only, same pages as before) and keeps them here.
- Lists, the production panel and the photo index use that reading when it is recent; otherwise they
  read the site live, exactly as before. Answers say at what time the program was read.
- Photos come from the local photo cache (fotos_gestao) instead of being downloaded for every PDF.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta
import json
import os
import threading

from gestao_rucodel import GestaoRucodel


def interval(settings):
    try: return max(3, min(120, int(settings.get('gestao_intervalo_min', 10))))
    except (TypeError, ValueError): return 10


class SiteCache:
    """Last background reading of the site, also kept on disk so a restart has data at once."""
    def __init__(self, root, settings, protect, reader=None):
        self.root, self.settings = root, settings
        self.reader = reader or GestaoRucodel(root, settings, protect)  # its own login, never shared
        self.file = root/'gestao_leitura.json'
        self.lock, self.busy = threading.Lock(), threading.Lock()
        self.data = {'zonas': None, 'fora': None, 'lido': None, 'setores': {}}
        self.error = None
        try:
            if self.file.is_file(): self.data.update(json.loads(self.file.read_text(encoding='utf-8')))
        except (OSError, ValueError): pass

    def read_at(self):
        return datetime.strptime(self.data['lido'], '%Y-%m-%d %H:%M:%S') if self.data.get('lido') else None

    def fresh(self, now=None, slack=2.5):
        moment = self.read_at()
        return bool(moment) and (now or datetime.now())-moment <= timedelta(minutes=interval(self.settings)*slack)

    def get(self, key, now=None):
        with self.lock:
            return copy.deepcopy(self.data[key]) if self.fresh(now) and self.data.get(key) is not None else None

    def put(self, **values):
        with self.lock:
            self.data.update(values)
            temp = self.file.with_suffix('.tmp')
            temp.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8'); os.replace(temp, self.file)

    def refresh(self, now=None, wait=False):
        """One reading (about a minute). If one is already running: False, or wait for it to finish (wait=True)."""
        if not self.busy.acquire(blocking=False):
            if wait and self.busy.acquire(timeout=300): self.busy.release()
            return False
        try:
            zones = self.reader.by_zone()
            overdue = self.reader.overdue()
            self.put(zonas=zones, fora=overdue, lido=(now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'))
            self.error = None
            return True
        except Exception as error:
            self.error = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            raise
        finally:
            self.busy.release()

    # sectors (from each service's «Gerir» window) change during the day: keep them for one interval
    def sectors(self, ids, now=None):
        now = now or datetime.now(); limit = timedelta(minutes=interval(self.settings))
        out = {}
        with self.lock:
            for sid in ids:
                hit = self.data['setores'].get(sid)
                if hit and now-datetime.strptime(hit[1], '%Y-%m-%d %H:%M:%S') <= limit: out[sid] = hit[0]
        return out

    def last_sectors(self, ids):
        """Last known sector (up to 12 h old), used when a fresh «Gerir» window fails to read."""
        with self.lock:
            return {sid: self.data['setores'][sid][0] for sid in ids if sid in self.data['setores']}

    def put_sectors(self, values, now=None):
        stamp = (now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        with self.lock:
            self.data['setores'] = {k: v for k, v in self.data['setores'].items()
                                    if (now or datetime.now())-datetime.strptime(v[1], '%Y-%m-%d %H:%M:%S') <= timedelta(hours=12)}
            for sid, value in values.items(): self.data['setores'][sid] = [value, stamp]


class CachedGestao(GestaoRucodel):
    """Same reading functions, but zones/«Fora de Prazo»/sectors/photos come from the background reading when recent."""
    def __init__(self, root, settings, protect, cache=None):
        super().__init__(root, settings, protect)
        self.cache = cache
        self.login_lock = threading.Lock()
        self.last_source = None  # (live|leitura, time) of the last list, shown in answers

    def ensure_login(self):
        with self.login_lock:
            if self.opener is None: self.login()

    def by_zone(self):
        cached = self.cache.get('zonas') if self.cache else None
        if cached is not None:
            self.last_source = ('leitura', self.cache.read_at()); return cached
        zones = super().by_zone()
        self.last_source = ('direto', datetime.now())
        return zones

    def overdue(self, max_pages=30):
        cached = self.cache.get('fora') if self.cache else None
        if cached is not None:
            self.last_source = ('leitura', self.cache.read_at()); return cached
        rows = super().overdue(max_pages)
        self.last_source = ('direto', datetime.now())
        return rows

    def sectors(self, rows):
        ids = list(dict.fromkeys(r['id'] for r in rows))
        known = self.cache.sectors(ids) if self.cache else {}
        missing = [r for r in {r['id']: r for r in rows}.values() if r['id'] not in known]
        if missing:
            self.ensure_login()
            found = super().sectors(missing)
            failed = [r for r in missing if found.get(r['id']) is None]
            if failed and len(failed)*2 >= len(missing):
                # Most «Gerir» windows came back empty: the site session expired (overnight) and returned the login page.
                with self.login_lock: self.login()
                found.update(super().sectors(failed))
            elif failed:
                # A few windows failed (slow site / timeout): try those once more.
                found.update(super().sectors(failed))
            if self.cache: self.cache.put_sectors({k: v for k, v in found.items() if v is not None})
            still = [r['id'] for r in missing if found.get(r['id']) is None]
            if still and self.cache:
                # Still unreadable: use the last sector seen today (not saved again, so it never looks fresh).
                found.update(self.cache.last_sectors(still))
            # Never seen and unreadable: counts as before the lathe (nothing done yet), not «sem informação».
            found.update({sid: 1 for sid in still if found.get(sid) is None})
            known.update(found)
        return known

    def thumbnail(self, path):
        try: return self.photo(path) if path else None
        except (OSError, RuntimeError): return None

    def thumbnails(self, rows):
        from concurrent.futures import ThreadPoolExecutor
        unique = {r['id']: r['imagem'] for r in rows}
        folder = self.root/'fotos_gestao'
        if any(p and not (folder/p.rsplit('/', 1)[-1]).is_file() for p in unique.values()):
            try: self.ensure_login()
            except (OSError, RuntimeError): pass
        with ThreadPoolExecutor(6) as pool:
            return dict(zip(unique, pool.map(self.thumbnail, unique.values())))

    def source_text(self):
        if not self.last_source: return ''
        kind, moment = self.last_source
        return ('Dados do programa lidos às %s.' % moment.strftime('%H:%M')) if kind == 'leitura' and moment else ''


def site_schedule(service, clock=None, sleep=None, runs=None):
    """Background reading every «gestao_intervalo_min» (05:00-22:00), then refresh the panel count and photo index from it."""
    import time
    clock = clock or datetime.now; sleep = sleep or time.sleep
    count = 0
    while runs is None or count < runs:
        now = clock(); cache = service.site_cache
        moment = cache.read_at()
        due = moment is None or now-moment >= timedelta(minutes=interval(service.settings))
        if service.gestao.configured() and 5 <= now.hour < 22 and due:
            count += 1
            try:
                if cache.refresh(now):
                    try: service.production_refresh()
                    except Exception as error: print('Painel da produção não atualizado: '+type(error).__name__, flush=True)
                    try:
                        if service.fotos.embedder.ready(): service.fotos.rebuild()
                    except Exception: pass  # the error stays in /jantes/foto
            except Exception as error:
                print('Leitura do programa de gestão falhou: '+(str(error) if isinstance(error, RuntimeError) else type(error).__name__), flush=True)
                sleep(5*60)
        sleep(30)
