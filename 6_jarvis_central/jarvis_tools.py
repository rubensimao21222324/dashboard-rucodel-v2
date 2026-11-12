"""Local tools: tasks, text documents, CSV analysis and consistent SQLite backup."""
from pathlib import Path
from contextlib import closing
import csv, io, json, sqlite3, zipfile
from datetime import datetime, timezone
from jarvis_memoria import MemoryStore, tokens

class Tools:
    def __init__(self,project):
        self.project=Path(project);self.store=MemoryStore(project)
        with closing(self.store.connect()) as c,c:
            c.execute("CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, done INTEGER DEFAULT 0, created_at TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, name TEXT NOT NULL, content TEXT NOT NULL)")
    def tasks(self):
        with closing(self.store.connect()) as c:return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY done,id DESC LIMIT 500')]
    def documents(self):
        with closing(self.store.connect()) as c:return [dict(r) for r in c.execute('SELECT id,name,length(content) AS characters FROM documents ORDER BY id DESC')]
    def search(self,query):
        terms=tokens(query)
        if not terms:return []
        found=[]
        with closing(self.store.connect()) as c:
            for row in c.execute('SELECT * FROM documents'):
                content=row['content']
                for start in range(0,len(content),1200):
                    chunk=content[start:start+1500];score=len(terms & tokens(chunk))
                    if score:found.append({'name':row['name'],'text':chunk,'score':score})
        return sorted(found,key=lambda x:x['score'],reverse=True)[:3]
    def action(self,b):
        action=b.get('action')
        with closing(self.store.connect()) as c,c:
            if action=='task_add':
                title=str(b.get('title','')).strip()
                if not title or len(title)>500:raise ValueError('Escreve uma tarefa com ate 500 caracteres.')
                if c.execute('SELECT count(*) FROM tasks').fetchone()[0]>=500:raise ValueError('Limite de 500 tarefas.')
                c.execute('INSERT INTO tasks(title,created_at) VALUES(?,?)',(title,datetime.now(timezone.utc).isoformat()))
            elif action=='task_done':c.execute('UPDATE tasks SET done=? WHERE id=?',(int(bool(b.get('done'))),int(b['id'])))
            elif action=='task_delete':c.execute('DELETE FROM tasks WHERE id=?',(int(b['id']),))
            elif action=='task_edit':
                title=str(b.get('title','')).strip()
                if not title or len(title)>500:raise ValueError('Escreve uma tarefa com ate 500 caracteres.')
                if c.execute('UPDATE tasks SET title=? WHERE id=?',(title,int(b['id']))).rowcount!=1:raise ValueError('Essa tarefa ja nao existe.')
            elif action=='document_add':
                name=Path(str(b.get('name','documento.txt'))).name[:160];content=str(b.get('content','')).strip()
                if not content or len(content)>200000:raise ValueError('Usa texto com ate 200 000 caracteres.')
                if c.execute('SELECT count(*) FROM documents').fetchone()[0]>=100:raise ValueError('Limite de 100 documentos.')
                c.execute('INSERT INTO documents(name,content) VALUES(?,?)',(name,content))
            elif action=='document_delete':c.execute('DELETE FROM documents WHERE id=?',(int(b['id']),))
            elif action=='search':return {'results':self.search(str(b.get('query','')))}
            elif action=='csv':return analyse_csv(str(b.get('content','')),str(b.get('column','')))
            else:raise ValueError('Operacao desconhecida.')
        return {'ok':True,'tasks':self.tasks(),'documents':self.documents()}
    def backup(self):
        folder=self.project/'jarvis_backups';folder.mkdir(exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f');path=folder/('Jarvis_'+stamp+'.zip')
        temp=folder/(stamp+'.sqlite3')
        try:
            with closing(self.store.connect()) as source,closing(sqlite3.connect(temp)) as target:source.backup(target)
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(temp,'jarvis_data/memoria.sqlite3')
                history=self.project/'chat_history'
                if history.is_dir():
                    for f in history.rglob('*'):
                        if f.is_file() and not f.is_symlink():z.write(f,f.relative_to(self.project))
        finally:temp.unlink(missing_ok=True)
        return path
    def daily_backup(self):
        folder=self.project/'jarvis_backups';prefix='Jarvis_'+datetime.now().strftime('%Y%m%d')
        if not folder.exists() or not any(folder.glob(prefix+'*.zip')):self.backup()

def analyse_csv(content,column=''):
    if len(content)>1000000:raise ValueError('CSV demasiado grande: limite de 1 MB de texto.')
    try:dialect=csv.Sniffer().sniff(content[:10000],delimiters=';,\t')
    except csv.Error:dialect=csv.excel
    reader=csv.DictReader(io.StringIO(content),dialect=dialect)
    names=reader.fieldnames or []
    if not names:raise ValueError('O CSV precisa de uma linha de cabecalhos.')
    if not column:return {'columns':names}
    if column not in names:raise ValueError('Escolhe uma coluna existente.')
    values=[];invalid=0;rows=0
    from decimal import Decimal,InvalidOperation
    for row in reader:
        rows+=1
        if rows>50000:raise ValueError('Limite de 50 000 linhas.')
        raw=str(row.get(column,'') or '').strip().replace('€','').replace(' ','').replace('\u00a0','')
        if ',' in raw:raw=raw.replace('.','').replace(',','.')
        try:
            value=Decimal(raw)
            if not value.is_finite():raise InvalidOperation
            values.append(value)
        except InvalidOperation:invalid+=1
    total=sum(values,Decimal(0))
    return {'column':column,'rows':rows,'valid':len(values),'ignored':invalid,'sum':str(total),'average':str(total/len(values)) if values else None,'min':str(min(values)) if values else None,'max':str(max(values)) if values else None}
