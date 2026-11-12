const $=id=>document.getElementById(id);
const make=(tag,cls='',text='')=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e;};
const fold=t=>String(t).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const business=/rucodel|empresa|jantes|custos|producao|luxemburgo|fornecedor|contabilidade|cnc|oficina|ads|mycar|decap/;
const types={clock:{name:'Relógio de Lisboa',tag:'AO TEU RITMO',symbol:'◷'},agenda:{name:'Agenda de hoje',tag:'GOOGLE',symbol:'◷'},notion:{name:'Pendentes do Diário',tag:'NOTION',symbol:'☷'},tasks:{name:'Tarefas locais',tag:'CENTRAL',symbol:'✓'},memory:{name:'Memória viva',tag:'MEMÓRIAS',symbol:'✧'},rucodel:{name:'Rucodel em foco',tag:'NOTAS GUARDADAS',symbol:'◈'},documents:{name:'Os teus documentos',tag:'CENTRAL',symbol:'▤'},system:{name:'A tua Central',tag:'ESTADO REAL',symbol:'◎'},core:{name:'O teu Jarvis',tag:'NÚCLEO',symbol:'◎'}};
const selected=new URLSearchParams(location.search).get('screen');
let layouts=[],version=0,current=null,snapshot=null,loading=false,lastSuccess=null,stale=false,editorDraft=null,editorVersion=0,editorBusy=false,toastTimer;
const cards=new Map();
function notify(text,error=false){$('screen-toast').textContent=text;$('screen-toast').classList.toggle('error',error);$('screen-toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('screen-toast').hidden=true,9000);}
async function safe(fn){try{return await fn();}catch(e){notify(e.message||'Não consegui concluir o pedido.',true);}}
async function api(path,body){const response=await fetch(path,body===undefined?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error?.message||data.error||'A Central não conseguiu concluir o pedido.');return data;}
const clone=value=>JSON.parse(JSON.stringify(value));
const dateFormat=(value,options)=>new Intl.DateTimeFormat('pt-PT',{timeZone:'Europe/Lisbon',...options}).format(new Date(value));
const action=(label,fn,cls='')=>{const button=make('button',cls,label);button.type='button';button.addEventListener('click',()=>safe(fn));return button;};
function link(label,url,cls='',target='_blank'){const a=make('a',cls,label);a.href=url;a.target=target;if(target==='_blank'||target.startsWith('jarvis-'))a.rel='noopener';return a;}
function safeExternal(url){try{const u=new URL(url);return u.protocol==='https:'&&['www.notion.so','notion.so','app.notion.com','calendar.google.com','www.google.com'].includes(u.hostname)?u.href:null;}catch{return null;}}
function showNotice(body,text,error=false){body.append(make('p','widget-notice'+(error?' widget-error':''),text));}
function row(body,title,detail='',url=null,hour=null){const r=make('div','widget-row');if(hour!==null)r.append(make('span','event-hour',hour));else r.append(make('span','event-marker'));const main=make('div','row-main');main.append(make('strong','',title));if(detail)main.append(make('small','',detail));const safe=safeExternal(url);if(safe)main.append(link('Abrir na origem ↗',safe));r.append(main);body.append(r);}
function footnote(body,total,shown){if(total>shown)body.append(make('p','widget-count','A mostrar '+shown+' de '+total+' registos nesta vista.'));}
function screenUrl(id){return '/screens?screen='+encodeURIComponent(id);}
async function loadLayouts(){const data=await api('/screens/layouts');layouts=data.layouts;version=data.version;current=layouts.find(x=>x.id===selected)||null;renderView();}
function renderLauncher(){
  const host=$('layout-cards');host.replaceChildren();
  layouts.forEach((layout,index)=>{
    const card=make('article','layout-card');const preview=make('div','layout-preview');
    layout.widgets.slice(0,4).forEach(widget=>{const mini=make('div','mini-widget'+(widget.size===2?' wide':'')+(widget.type==='core'?' core':''));mini.append(make('small','',widget.type==='core'?'':types[widget.type].name),make('span','',widget.type==='core'?'J':types[widget.type].symbol));preview.append(mini);});
    const content=make('div','layout-card-content'),top=make('div','layout-card-title');top.append(make('h2','',layout.title),make('small','','ECRÃ '+String(index+1).padStart(2,'0')));content.append(top,make('p','',layout.subtitle||'O teu espaço de trabalho, ao teu gosto.'));
    const links=make('div','layout-card-links');links.append(link('Abrir janela ↗',screenUrl(layout.id),'open-screen','jarvis-'+layout.id),action('Personalizar',()=>openEditor(layout)),link('Usar esta janela',screenUrl(layout.id),'','_self'));
    const tools=make('div','layout-tools');tools.append(action('Duplicar',()=>openEditor({...clone(layout),id:newId(),title:(layout.title+' · cópia').slice(0,60)})),action('Retirar ecrã',async()=>{if(!confirm('Retirar o ecrã «'+layout.title+'»? As tarefas, memórias e agendas mantêm-se.'))return;const data=await api('/screens/layouts',{action:'delete',id:layout.id,version});layouts=data.layouts;version=data.version;renderView();broadcast();}));content.append(links,tools);card.append(preview,content);host.append(card);
  });
}
function renderView(){
  const standalone=!!selected&&!!current;
  document.body.classList.toggle('standalone',standalone);document.body.dataset.theme=current?.theme||'gold';
  $('screen-intro').hidden=standalone;$('layout-cards').hidden=standalone;$('setup-note').hidden=standalone;$('screen-heading').hidden=!standalone;$('widget-grid').hidden=!standalone;$('screen-customize').hidden=!standalone;$('screen-home').hidden=!standalone;
  if(!standalone){$('widget-grid').replaceChildren();$('widget-grid').dataset.layout='';cards.clear();document.title='Jarvis · Os teus ecrãs';renderLauncher();if(selected)notify('Este ecrã já não existe. Escolhe outro dos ecrãs guardados.',true);return;}
  document.title='Jarvis · '+current.title;$('screen-title').textContent=current.title;$('screen-subtitle').textContent=current.subtitle;$('screen-serial').textContent=String(layouts.findIndex(x=>x.id===selected)+1).padStart(2,'0');
  const grid=$('widget-grid');grid.style.setProperty('--columns',current.columns);grid.style.setProperty('--wide-span',Math.min(2,current.columns));grid.dataset.columns=String(current.columns);
  // Keep the live robot iframe mounted during data refreshes.
  const signature=JSON.stringify(current.widgets);
  if(grid.dataset.layout!==signature){
    grid.dataset.layout=signature;grid.replaceChildren();cards.clear();
    current.widgets.forEach(widget=>{const card=make('article','widget-card widget-'+widget.type+(widget.size===2?' wide':'')),head=make('header'),body=make('div','widget-body');head.append(make('h2','',types[widget.type].name),make('span','widget-tag',types[widget.type].tag));card.append(head,body);cards.set(widget.type,{card,body});grid.append(card);
      if(widget.type==='core'){const iframe=make('iframe');iframe.src='/?view=core';iframe.title='Núcleo animado do Jarvis';iframe.setAttribute('loading','lazy');body.append(iframe);}
      else if(widget.type==='clock')renderClock(body);
      else showNotice(body,'A consultar os teus dados…');
    });
  }
  if(snapshot)renderWidgets();updateClock();
}
async function refresh(){
  if(loading)return;loading=true;$('screen-refresh').disabled=true;
  try{
    snapshot=await api('/screens/data');lastSuccess=Date.now();stale=false;
    $('central-dot').classList.add('online');$('central-status').textContent=snapshot.status.ollama?'Central ligada · inteligência local':'Central ligada · Ollama desligado';
    if(current)renderWidgets();updateSync();
  }catch(e){stale=true;$('central-dot').classList.remove('online');$('central-status').textContent='Sem ligação à Central';updateSync();if(!snapshot)for(const [type,entry] of cards)if(!['clock','core'].includes(type)){entry.body.replaceChildren();showNotice(entry.body,'Não consegui carregar os dados. Mantém a janela da Central aberta e volta a atualizar.',true);}notify(e.message,true);}
  finally{loading=false;$('screen-refresh').disabled=false;}
}
function updateSync(){const stamp=lastSuccess?dateFormat(lastSuccess,{hour:'2-digit',minute:'2-digit',second:'2-digit'}):null;const external=snapshot?.external_checked_at?dateFormat(snapshot.external_checked_at,{hour:'2-digit',minute:'2-digit'}):null;$('screen-sync').textContent=stale?'Sem ligação · '+(stamp?'últimos dados às '+stamp:'sem dados disponíveis'):stamp?'Local '+stamp+' · Notion / Google '+external+' · atualização externa até 60 s':'A consultar a Central…';}
function renderClock(body){body.replaceChildren();const clock=make('div','large-clock');clock.append(make('span','clock-hours'),make('span','clock-seconds'));body.append(clock,make('div','clock-date'),make('div','clock-greeting'));}
function updateClock(){
  const now=Date.now();$('header-date').textContent=dateFormat(now,{day:'2-digit',month:'2-digit',year:'numeric'});$('display-day').textContent=dateFormat(now,{weekday:'long',day:'numeric',month:'long'});
  const body=cards.get('clock')?.body;if(!body)return;
  body.querySelector('.clock-hours').textContent=dateFormat(now,{hour:'2-digit',minute:'2-digit'});body.querySelector('.clock-seconds').textContent=dateFormat(now,{second:'2-digit'});
  body.querySelector('.clock-date').textContent=dateFormat(now,{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  const hour=Number(dateFormat(now,{hour:'2-digit',hourCycle:'h23'}));body.querySelector('.clock-greeting').textContent=hour<12?'Bom dia, meu rei.':hour<20?'Boa tarde, meu rei.':'Boa noite, meu rei.';
}
function renderWidgets(){
  const data=snapshot;if(!data)return;
  for(const [type,entry] of cards){
    if(type==='clock'||type==='core')continue;
    const body=entry.body,scroll=body.scrollTop;body.replaceChildren();
    if(type==='agenda'){
      if(data.daily.calendar_error)showNotice(body,data.daily.calendar_error,true);
      else if(!data.connections.google)showNotice(body,'Liga a Google Agenda nas Definições do painel principal.');
      else if(data.daily.calendar){const calendar=data.daily.calendar;body.append(make('p','widget-note',calendar.calendar_name+' · hoje · horas de Lisboa'));if(!calendar.events.length)showNotice(body,'Sem compromissos nesta agenda para hoje. Um pouco de espaço para o que importa.');calendar.events.slice(0,30).forEach(event=>row(body,event.title,event.location||'',event.url,event.all_day?'DIA':dateFormat(event.start,{hour:'2-digit',minute:'2-digit'})));footnote(body,calendar.events.length,30);if(calendar.partial)showNotice(body,'Consulta parcial: há mais eventos por consultar.');}
      else showNotice(body,'A agenda não ficou disponível nesta consulta.',true);
    }
    if(type==='notion'){
      if(data.daily.notion_error)showNotice(body,data.daily.notion_error,true);
      else if(!data.connections.notion)showNotice(body,'Liga o Notion nas Definições do painel principal.');
      else if(data.daily.notion){const notion=data.daily.notion;body.append(make('p','widget-note','Caixas por concluir nos últimos 30 registos do Diário até hoje.'));if(!notion.tasks.length)showNotice(body,'Sem caixas pendentes nos registos consultados.');notion.tasks.slice(0,30).forEach(task=>row(body,task.title,task.date,task.url));footnote(body,notion.tasks.length,30);if(notion.partial)showNotice(body,'Consulta parcial: há registos ou blocos adicionais por consultar.');}
      else showNotice(body,'O Diário não ficou disponível nesta consulta.',true);
    }
    if(type==='tasks'){
      const pending=data.tasks.filter(t=>!t.done);body.append(make('p','widget-note',pending.length+' pendentes na tua lista local.'));if(!pending.length)showNotice(body,'Tudo tratado na lista local.');
      pending.slice(0,30).forEach(task=>{const r=make('div','widget-row'),check=make('input');check.type='checkbox';check.className='task-check';check.setAttribute('aria-label','Concluir '+task.title);check.addEventListener('change',()=>safe(async()=>{check.disabled=true;try{await api('/tasks',{action:'task_done',id:task.id,done:check.checked});await refresh();broadcast('data');}catch(e){check.checked=false;throw e;}finally{check.disabled=false;}}));const main=make('div','row-main');main.append(make('strong','',task.title),make('small','','Tarefa local · #'+task.id));r.append(check,main);body.append(r);});footnote(body,pending.length,30);
    }
    if(type==='memory'||type==='rucodel'){
      let memories=type==='rucodel'?data.memories.filter(m=>business.test(fold(m.content))):data.memories;const limit=type==='rucodel'?10:8;
      body.append(make('p','widget-note',type==='rucodel'?'Notas e contexto da Rucodel encontrados nas 80 memórias mais recentes ou fixas. Produção e faturação ainda sem fonte ligada.':'Uma seleção das tuas memórias mais recentes ou fixas.'));
      if(!memories.length)showNotice(body,type==='rucodel'?'Ainda não há notas da Rucodel nesta seleção de memórias.':'Ainda não há memórias guardadas.');
      memories.slice(0,limit).forEach((memory,i)=>{const r=make('div','widget-row');r.append(make('span','note-index',String(i+1).padStart(2,'0')),make('p','fact-text',memory.content));body.append(r);});footnote(body,memories.length,limit);
      if(type==='rucodel'){const pending=data.tasks.filter(t=>!t.done&&business.test(fold(t.title)));if(pending.length){body.append(make('p','widget-note','PENDENTES LOCAIS DA RUCODEL'));pending.slice(0,8).forEach(task=>row(body,task.title,'Lista local · #'+task.id));footnote(body,pending.length,8);}}
    }
    if(type==='documents'){body.append(make('p','widget-note','Documentos importados para a Central.'));if(!data.documents.length)showNotice(body,'Ainda não há documentos importados.');data.documents.slice(0,20).forEach(doc=>row(body,doc.name,new Intl.NumberFormat('pt-PT').format(doc.characters)+' caracteres'));footnote(body,data.documents.length,20);body.append(link('Abrir documentos no painel principal ↗','/','quiet-link'));}
    if(type==='system'){
      const stats=make('div','stat-grid');[[data.memory_total,'memórias'],[data.tasks.filter(t=>!t.done).length,'pendentes locais'],[data.documents.length,'documentos']].forEach(([number,label])=>{const cell=make('div');cell.append(make('strong','',String(number)),make('small','',label));stats.append(cell);});body.append(stats);
      [['Modelo local',data.status.ollama?data.status.selected_model:'Ollama desligado'],['Notion',data.daily.notion_error?'Erro na consulta':data.connections.notion?'Ligação configurada':'Por ligar'],['Google Agenda',data.daily.calendar_error?'Erro na consulta':data.connections.google?'Ligação configurada':'Por ligar']].forEach(([label,value])=>{const line=make('div','source-line');line.append(make('span','',label),make('b','',value));body.append(line);});
    }
    body.scrollTop=scroll;
  }
}
function newId(){return 'screen-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);}
async function openEditor(layout=null){
  // Read the current revision before opening an editor; saves never overwrite concurrent edits.
  const latest=await api('/screens/layouts');version=latest.version;layouts=latest.layouts;editorVersion=latest.version;
  editorDraft=layout?clone(latest.layouts.find(x=>x.id===layout.id)||layout):{id:newId(),title:'O meu ecrã',subtitle:'A informação de que preciso, no meu espaço.',columns:2,theme:'gold',widgets:[{type:'clock',size:1},{type:'agenda',size:1},{type:'notion',size:2}]};
  $('layout-name').value=editorDraft.title;$('layout-subtitle').value=editorDraft.subtitle;$('layout-columns').value=String(editorDraft.columns);$('layout-theme').value=editorDraft.theme;$('editor-feedback').textContent='';$('layout-save').disabled=false;
  renderEditorWidgets();if(!$('layout-editor').open)$('layout-editor').showModal();
}
function renderEditorWidgets(){
  const list=$('editor-widgets');list.replaceChildren();
  editorDraft.widgets.forEach((widget,i)=>{const line=make('div','editor-widget');line.append(make('strong','',types[widget.type].name));const wide=make('label'),check=make('input');check.type='checkbox';check.checked=widget.size===2;check.addEventListener('change',()=>widget.size=check.checked?2:1);wide.append(check,document.createTextNode('Largo'));line.append(wide);
    const up=action('↑',()=>{[editorDraft.widgets[i-1],editorDraft.widgets[i]]=[editorDraft.widgets[i],editorDraft.widgets[i-1]];renderEditorWidgets();});up.setAttribute('aria-label','Subir '+types[widget.type].name);up.disabled=i===0;
    const down=action('↓',()=>{[editorDraft.widgets[i+1],editorDraft.widgets[i]]=[editorDraft.widgets[i],editorDraft.widgets[i+1]];renderEditorWidgets();});down.setAttribute('aria-label','Descer '+types[widget.type].name);down.disabled=i===editorDraft.widgets.length-1;
    const remove=action('×',()=>{editorDraft.widgets.splice(i,1);renderEditorWidgets();});remove.setAttribute('aria-label','Retirar '+types[widget.type].name);line.append(up,down,remove);list.append(line);
  });
  const select=$('widget-type');select.replaceChildren();Object.entries(types).filter(([type])=>!editorDraft.widgets.some(w=>w.type===type)).forEach(([type,meta])=>{const option=make('option','',meta.name);option.value=type;select.append(option);});if(select.children.length)select.value=select.children[0].value;$('widget-add').disabled=editorDraft.widgets.length>=8||!select.children.length;
}
$('widget-add').addEventListener('click',()=>{const type=$('widget-type').value;if(!types[type]||editorDraft.widgets.length>=8||editorDraft.widgets.some(w=>w.type===type))return;editorDraft.widgets.push({type,size:1});renderEditorWidgets();});
$('layout-form').addEventListener('submit',event=>{event.preventDefault();safe(async()=>{if(editorBusy)return;editorBusy=true;$('layout-save').disabled=true;try{if(!editorDraft.widgets.length)throw Error('Adiciona pelo menos um bloco ao ecrã.');editorDraft.title=$('layout-name').value;editorDraft.subtitle=$('layout-subtitle').value;editorDraft.columns=Number($('layout-columns').value);editorDraft.theme=$('layout-theme').value;const data=await api('/screens/layouts',{action:'save',layout:editorDraft,version:editorVersion});layouts=data.layouts;version=data.version;current=layouts.find(x=>x.id===selected)||null;$('layout-editor').close();renderView();notify('Ecrã guardado na tua Central.');broadcast();}catch(e){$('editor-feedback').textContent=e.message;throw e;}finally{editorBusy=false;$('layout-save').disabled=false;}});});
$('editor-close').addEventListener('click',()=>$('layout-editor').close());
$('screen-new').addEventListener('click',()=>safe(()=>openEditor()));$('screen-customize').addEventListener('click',()=>safe(()=>openEditor(current)));
$('screen-fullscreen').addEventListener('click',()=>safe(async()=>{if(document.fullscreenElement)await document.exitFullscreen();else if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();else notify('Usa F11 para colocar esta janela em ecrã inteiro.');}));
$('screen-refresh').addEventListener('click',()=>safe(refresh));
let channel=null;try{if(typeof BroadcastChannel!=='undefined')channel=new BroadcastChannel('jarvis-displays');}catch{}
function broadcast(kind='layouts'){channel?.postMessage({kind});}
if(channel)channel.onmessage=event=>{if(event.data?.kind==='layouts'){if(!$('layout-editor').open)safe(loadLayouts);}else if(event.data?.kind==='data')safe(refresh);};
document.addEventListener('visibilitychange',()=>{if(!document.hidden)safe(async()=>{if(!$('layout-editor').open)await loadLayouts();await refresh();});});
setInterval(updateClock,1000);setInterval(()=>{if(!document.hidden)safe(refresh);},20000);
safe(async()=>{await loadLayouts();await refresh();updateClock();});
