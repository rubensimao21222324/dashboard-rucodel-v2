"""Windows installer/launcher for official Open WebUI plus the local Jarvis gateway."""
from pathlib import Path
import argparse,json,os,secrets,shutil,socket,sqlite3,subprocess,sys,threading,time,urllib.request,webbrowser
SOURCE=Path(__file__).resolve().parent
DEST=Path.home()/'Jarvis_Central_Pro'
PROJECT=Path.home()/'Jarvis'
VERSION='0.12.5'

def python_exe():return DEST/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
def find_uv():
 uv=shutil.which('uv')
 if uv:return uv
 for f in [Path.home()/'.local/bin/uv.exe',Path.home()/'.cargo/bin/uv.exe']:
  if f.is_file():return str(f)
 raise RuntimeError('Nao encontrei o uv. O Jarvis antigo precisa desta ferramenta; abre um novo terminal e confirma where uv.')
def run(cmd,**kw):
 print('A executar: '+str(cmd[0])+' '+str(cmd[1]) if len(cmd)>1 else str(cmd[0]),flush=True)
 subprocess.run([str(x) for x in cmd],check=True,**kw)
def snapshot():
 target=DEST/'importacao';target.mkdir(exist_ok=True)
 db=PROJECT/'jarvis_data/memoria.sqlite3'
 if not db.is_file():print('Nao encontrei a memoria antiga; sera criada quando iniciares.');return
 stamp=time.strftime('%Y%m%d_%H%M%S')
 backup=target/('memoria_antes_central_'+stamp+'.sqlite3')
 with sqlite3.connect(db) as con,sqlite3.connect(backup) as out:
  con.backup(out)
  con.row_factory=sqlite3.Row
  rows=[dict(r) for r in con.execute('SELECT id,content,pinned,created_at,updated_at FROM memories')]
 (target/('memorias_'+stamp+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Copia das memorias antigas criada. A Central usa a mesma base local; nao depende de uma importacao manual.')
def install():
 if not (PROJECT/'jarvis_data/memoria.sqlite3').is_file():
  print('Nao encontrei a memoria da instalacao antiga em '+str(PROJECT)+'. A instalacao nao vai continuar para evitar criar uma base errada.')
  raise RuntimeError('Confirma a pasta do projeto Jarvis.')
 DEST.mkdir(exist_ok=True)
 if SOURCE!=DEST:
  for name in ['backend','painel']:
   shutil.copytree(SOURCE/name,DEST/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
  for name in ['bootstrap.py','LEIA-ME.html','FONTES.txt','Iniciar_Central.cmd','Diagnostico.cmd']:
   shutil.copy2(SOURCE/name,DEST/name)
 snapshot()
 uv=find_uv();python=python_exe()
 if not python.exists():run([uv,'venv','--python','3.12',DEST/'.venv'])
 print('A instalar Open WebUI oficial '+VERSION+' e voz Edge. O primeiro download pode ser grande. Aguarda.',flush=True)
 run([uv,'pip','install','--python',python,'open-webui=='+VERSION,'edge-tts>=7,<8'])
 # Save the versions actually resolved, without changing the existing Jarvis env.
 freeze=subprocess.run([uv,'pip','freeze','--python',python],capture_output=True,text=True,check=True)
 (DEST/'versoes_instaladas.txt').write_text(freeze.stdout,encoding='utf-8')
 sys.path.insert(0,str(DEST/'backend'))
 from central import Service
 Service(PROJECT,DEST)
 print('\nINSTALACAO CONCLUIDA. A iniciar a Central.',flush=True)
 launch()
def health(port,path='/health'):
 try:
  with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=2) as r:return json.load(r)
 except (OSError,ValueError):return None
def occupied(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=1):return True
 except OSError:return False
def launch():
 if not python_exe().exists():raise RuntimeError('Abre primeiro Instalar_Central.cmd.')
 cfg=json.loads((DEST/'central_config.json').read_text(encoding='utf-8'))
 bridge=health(12396)
 if bridge and bridge.get('app')!='jarvis-central-pro':raise RuntimeError('Porta 12396 ocupada por outro programa.')
 if not bridge and occupied(12396):raise RuntimeError('Porta 12396 ocupada. Nao vou fechar programas automaticamente.')
 if occupied(8088):
  if health(8088):
   webbrowser.open('http://127.0.0.1:12396');return
  raise RuntimeError('Porta 8088 ocupada por outro programa.')
 logdir=DEST/'logs';logdir.mkdir(exist_ok=True)
 bridge_proc=None
 if not bridge:
  log=(logdir/'voz_e_ferramentas.log').open('a',encoding='utf-8')
  bridge_proc=subprocess.Popen([str(python_exe()),'-u',str(DEST/'backend/central.py'),'--project',str(PROJECT)],cwd=DEST,stdout=log,stderr=subprocess.STDOUT)
  log.close()
  for _ in range(30):
   if health(12396):break
   time.sleep(.5)
  else:raise RuntimeError('O servico local nao iniciou. Consulta logs/voz_e_ferramentas.log.')
 env=os.environ.copy();env.update({'DATA_DIR':str(DEST/'dados_openwebui'),'WEBUI_SECRET_KEY':cfg['token'],'ENABLE_OLLAMA_API':'False','ENABLE_OPENAI_API':'True','OPENAI_API_BASE_URL':'http://127.0.0.1:12396/v1','OPENAI_API_KEY':cfg['token'],'OPENAI_API_BASE_URLS':'http://127.0.0.1:12396/v1','OPENAI_API_KEYS':cfg['token'],'DEFAULT_MODELS':'jarvis-rucodel','DEFAULT_LOCALE':'pt-PT','AUDIO_TTS_ENGINE':'openai','AUDIO_TTS_OPENAI_API_BASE_URL':'http://127.0.0.1:12396/v1','AUDIO_TTS_OPENAI_API_KEY':cfg['token'],'AUDIO_TTS_MODEL':'edge-tts','AUDIO_TTS_VOICE':cfg['voice'],'UVICORN_WORKERS':'1'})
 executable=DEST/'.venv'/('Scripts/open-webui.exe' if os.name=='nt' else 'bin/open-webui')
 if not executable.exists():raise RuntimeError('Open WebUI nao foi instalado. Volta a executar Instalar_Central.cmd.')
 # Stable working directory and data path are intentional: updates preserve chats.
 proc=subprocess.Popen([str(executable),'serve','--host','127.0.0.1','--port','8088'],cwd=DEST,env=env)
 def open_when_ready():
  for _ in range(360):
   if proc.poll() is not None:return
   if health(8088):
    webbrowser.open('http://127.0.0.1:12396');return
   time.sleep(1)
  print('O primeiro arranque ainda esta a preparar modelos. Consulta a janela para ver o progresso.',flush=True)
 threading.Thread(target=open_when_ready,daemon=True).start()
 print('Mantem esta janela aberta. No primeiro arranque cria a tua conta local no Open WebUI.\nPainel: http://127.0.0.1:12396\nConversas: http://127.0.0.1:8088',flush=True)
 try:proc.wait()
 except KeyboardInterrupt:proc.terminate();proc.wait()
 finally:
  if bridge_proc is not None and bridge_proc.poll() is None:bridge_proc.terminate();bridge_proc.wait()
def diagnose():
 print('Python de arranque:',sys.version.split()[0]);print('Projeto antigo:',PROJECT);print('Central:',DEST)
 print('Instalacao Open WebUI:',python_exe().exists())
 print('Memoria antiga encontrada:',(PROJECT/'jarvis_data/memoria.sqlite3').is_file())
 print('Ollama:',bool(health(11434,'/api/tags')))
 print('Servidor de voz/ferramentas:',health(12396));print('Open WebUI:',bool(health(8088)))
 cfg=DEST/'central_config.json'
 if cfg.exists():
  c=json.loads(cfg.read_text());print('Voz:',c['voice']);print('Modelo local:',c['model'])
 print('Nao foram apresentados tokens nem passwords.')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['install','start','diagnose']);args=p.parse_args()
 try:{'install':install,'start':launch,'diagnose':diagnose}[args.action]()
 except Exception as e:print('\nNAO FOI POSSIVEL TERMINAR:',str(e),flush=True);raise SystemExit(1)
