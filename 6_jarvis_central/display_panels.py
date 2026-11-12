"""Persistent named display layouts in the existing Jarvis SQLite backup."""
from contextlib import closing
import json
import re
import threading

WIDGETS={'clock','agenda','notion','tasks','memory','rucodel','documents','system','core'}
DEFAULTS=[
 {'id':'day','title':'O meu dia','subtitle':'Agenda, prioridades e espaço para respirar.','columns':2,'theme':'gold','widgets':[{'type':'clock','size':1},{'type':'system','size':1},{'type':'agenda','size':2},{'type':'notion','size':1},{'type':'tasks','size':1}]},
 {'id':'work','title':'Rucodel · Em foco','subtitle':'O que sabemos. O que falta tratar.','columns':2,'theme':'gold','widgets':[{'type':'clock','size':1},{'type':'system','size':1},{'type':'rucodel','size':2},{'type':'tasks','size':1},{'type':'documents','size':1}]},
 {'id':'core','title':'Jarvis · Núcleo','subtitle':'O teu universo, sempre presente.','columns':2,'theme':'gold','widgets':[{'type':'core','size':2},{'type':'clock','size':1},{'type':'agenda','size':1}]}
]

class DisplayPanels:
 def __init__(self,store):
  self.store=store;self.lock=threading.RLock()
  with closing(store.connect()) as con,con:
   con.execute('CREATE TABLE IF NOT EXISTS central_display_layouts(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,layouts TEXT NOT NULL)')
   con.execute('INSERT OR IGNORE INTO central_display_layouts VALUES(1,0,?)',(json.dumps(DEFAULTS,ensure_ascii=False),))
 def list(self):
  with closing(self.store.connect()) as con:
   row=con.execute('SELECT version,layouts FROM central_display_layouts WHERE id=1').fetchone()
  return {'version':row['version'],'layouts':json.loads(row['layouts'])}
 @staticmethod
 def validate(value):
  if not isinstance(value,dict):raise ValueError('Configuração de ecrã inválida.')
  uid=value.get('id');title=value.get('title');subtitle=value.get('subtitle','')
  if not isinstance(uid,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',uid):raise ValueError('Identificador de ecrã inválido.')
  if not isinstance(title,str) or not 1<=len(title.strip())<=60:raise ValueError('O nome do ecrã precisa de 1 a 60 caracteres.')
  if not isinstance(subtitle,str) or len(subtitle)>150:raise ValueError('A descrição admite até 150 caracteres.')
  columns=value.get('columns',2);theme=value.get('theme','gold');widgets=value.get('widgets')
  if type(columns)!=int or columns not in (1,2,3) or theme not in ('gold','ice'):raise ValueError('Estilo de ecrã inválido.')
  if not isinstance(widgets,list) or not 1<=len(widgets)<=8:raise ValueError('Escolhe de 1 a 8 blocos para o ecrã.')
  cleaned=[]
  for widget in widgets:
   if not isinstance(widget,dict) or widget.get('type') not in WIDGETS or type(widget.get('size',1))!=int or widget.get('size',1) not in (1,2):raise ValueError('Bloco de ecrã inválido.')
   if any(w['type']==widget['type'] for w in cleaned):raise ValueError('Cada bloco só pode aparecer uma vez no mesmo ecrã.')
   cleaned.append({'type':widget['type'],'size':widget.get('size',1)})
  return {'id':uid,'title':title.strip(),'subtitle':subtitle.strip(),'columns':columns,'theme':theme,'widgets':cleaned}
 def update(self,body):
  with self.lock,closing(self.store.connect()) as con,con:
   con.execute('BEGIN IMMEDIATE')
   row=con.execute('SELECT version,layouts FROM central_display_layouts WHERE id=1').fetchone()
   if type(body.get('version'))!=int or body['version']!=row['version']:raise ValueError('Os ecrãs foram alterados noutra janela. Reabre Personalizar antes de guardar.')
   layouts=json.loads(row['layouts']);action=body.get('action')
   if action=='save':
    value=self.validate(body.get('layout'));index=next((i for i,x in enumerate(layouts) if x['id']==value['id']),None)
    if index is None:
     if len(layouts)>=12:raise ValueError('Podes guardar até 12 ecrãs.')
     layouts.append(value)
    else:layouts[index]=value
   elif action=='delete':
    if not any(x['id']==body.get('id') for x in layouts):raise ValueError('Esse ecrã já não existe.')
    if len(layouts)==1:raise ValueError('Mantém pelo menos um ecrã guardado.')
    layouts=[x for x in layouts if x['id']!=body['id']]
   else:raise ValueError('Operação de ecrã desconhecida.')
   con.execute('UPDATE central_display_layouts SET version=version+1,layouts=? WHERE id=1',(json.dumps(layouts,ensure_ascii=False),))
  return self.list()
