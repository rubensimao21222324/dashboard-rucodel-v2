# Ações a corrigir: lista simples de coisas a corrigir na empresa, escritas pelo Simão no painel.
# Guardadas só neste PC (acoes_corrigir.json). Ações: criar, editar, feita, apagar.
from __future__ import annotations
import json,os,secrets,threading
from datetime import datetime
from pathlib import Path
try:from calendar_connection import lisbon_zone
except Exception:  # testes sem as dependências da Central
 from zoneinfo import ZoneInfo
 def lisbon_zone():return ZoneInfo('Europe/Lisbon')

MAX_TEXT=2000

class CorrectiveActions:
 def __init__(self,root):
  self.path=Path(root)/'acoes_corrigir.json';self.lock=threading.Lock()
 def _load(self):
  if not self.path.is_file():return []
  data=json.loads(self.path.read_text(encoding='utf-8'))
  return data if isinstance(data,list) else []
 def _save(self,items):
  temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(items,ensure_ascii=False,indent=1),encoding='utf-8');os.replace(temp,self.path)
 @staticmethod
 def _now():return datetime.now(lisbon_zone()).strftime('%Y-%m-%d %H:%M')
 @staticmethod
 def _text(value):
  text=str(value or '').strip()
  if not 0<len(text)<=MAX_TEXT:raise ValueError('Escreve a ação a corrigir (até 2000 caracteres).')
  return text
 def handle(self,body=None):
  with self.lock:
   items=self._load()
   if body is None:return {'acoes':items}
   action=body.get('acao')
   if action=='criar':
    items.insert(0,{'id':secrets.token_hex(6),'criada':self._now(),'texto':self._text(body.get('texto')),'feita':False,'feita_em':''})
   elif action in ('editar','feita','apagar'):
    found=[a for a in items if a.get('id')==body.get('id')]
    if not found:raise ValueError('Ação não encontrada.')
    item=found[0]
    if action=='editar':item['texto']=self._text(body.get('texto'))
    elif action=='feita':item['feita']=bool(body.get('feita'));item['feita_em']=self._now() if item['feita'] else ''
    else:items.remove(item)
   else:raise ValueError('Ação desconhecida.')
   self._save(items)
   return {'acoes':items}
