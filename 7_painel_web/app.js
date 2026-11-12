const $ = id => document.getElementById(id);
const safeStorage = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Conversations remain on the server. */ } }
};
const prefs = {...{voiceAuto:true,reduced:false,view:'core',chat:null},...safeStorage.get('jarvis-universe-preferences',{})};
const coreOnly=typeof location!=='undefined'&&new URLSearchParams(location.search).get('view')==='core';
if(coreOnly){prefs.voiceAuto=false;prefs.view='core';document.body.classList.add('display-core');}
let displayChannel=null;try{if(typeof BroadcastChannel!=='undefined'&&!coreOnly)displayChannel=new BroadcastChannel('jarvis-displays');}catch{}
const state = {status:null,tasks:[],memories:[],memoryInfo:null,documents:[],messages:[],chat:null,busy:false,speaking:false,audioLoading:false,connected:false,groups:[],mode:'core'};
const groupDefinitions = [
  {id:'rucodel',name:'Rucodel',test:/rucodel|empresa|jantes|custos|producao|luxemburgo/},
  {id:'cnc',name:'CNC & oficina',test:/cnc|mach3|nvem|g31|2002|decapagem|alit|impressao 3d/},
  {id:'familia',name:'Família',test:/filha|leonor|elisa|companheira|cao|bolt|familia/},
  {id:'organizacao',name:'Organização',test:/notion|agenda|tarefas|organiz|rotina|stress|tempo/},
  {id:'jarvis',name:'Jarvis',test:/jarvis|assistente|memoria|inteligencia/},
  {id:'saude',name:'Saúde & rotina',test:/lynch|saude|hernia|azia|refluxo|refeic|figado|colonoscop|jantares|costocondrite/}
];
const coordinates = [[72,19],[86,35],[85,61],[68,79],[24,77],[12,40],[35,13]];
const fold = t => t.toLocaleLowerCase('pt-PT').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const savePrefs = () => safeStorage.set('jarvis-universe-preferences',prefs);
const icon = name => { const s=document.createElementNS('http://www.w3.org/2000/svg','svg');const u=document.createElementNS(s.namespaceURI,'use');u.setAttribute('href','#i-'+name);s.append(u);return s; };
const element = (tag, cls='', text='') => {const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e;};
const actionButton = (name, fn, symbol, cls='icon-button') => {const b=element('button',cls);b.type='button';b.title=name;b.setAttribute('aria-label',name);if(symbol)b.append(icon(symbol));else b.textContent=name;b.addEventListener('click',()=>safe(fn));return b;};
let toastTimer;
function notify(text,error=false){$('toast').textContent=text;$('toast').hidden=false;$('toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,error?12000:6500);}
async function safe(fn){try{return await fn();}catch(e){notify(e.message||'Não foi possível concluir o pedido.',true);}}
async function api(path,body){
  const response=await fetch(path,body===undefined?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw Error(data.error?.message||data.error||'A Central não conseguiu concluir o pedido.');
  if(body!==undefined&&['/tasks','/memories','/documents','/panel/chat'].includes(path))displayChannel?.postMessage({kind:'data'});
  return data;
}
function dateText(value,options={day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}){return new Intl.DateTimeFormat('pt-PT',{timeZone:'Europe/Lisbon',...options}).format(new Date(value));}
// Conversa em barra: a resposta abre por cima da barra e fecha sozinha passado um bocado sem mexer.
let chatTimer=null;
function openChat(){$('chat-pop').hidden=false;armChatClose();const l=$('messages');l.scrollTop=l.scrollHeight;}
function closeChat(){clearTimeout(chatTimer);$('chat-pop').hidden=true;}
function armChatClose(){clearTimeout(chatTimer);chatTimer=setTimeout(()=>{const pop=$('chat-pop');if(state.busy||state.speaking||state.audioLoading||pop.matches(':hover')||pop.contains(document.activeElement)||(document.activeElement===$('message')&&$('message').value)){armChatClose();return;}closeChat();},75000);}
function setBusy(value){if(value)openChat();else armChatClose();state.busy=value;$('send').disabled=value;$('new-chat').disabled=value;$('history-button').disabled=value;$('thinking').hidden=!value;updateActivity();}
function updateActivity(){
  const ready=state.connected;
  let label=ready?'À tua disposição.':'A ligar à tua Central…';
  let detail=ready?'Memórias, tarefas e conversa no mesmo lugar.':'Mantém a janela de arranque da Central aberta.';
  if(ready&&!state.status?.ollama){label='O modelo local está desligado.';detail='Abre o Ollama. As tuas memórias e tarefas continuam disponíveis.';}
  if(state.busy){label='A ligar os pontos.';detail=state.status?.reasoning_enabled?'O modelo local pode demorar mais enquanto prepara a resposta.':'O Jarvis está a preparar a tua resposta.';}
  if(state.audioLoading){label='A preparar a voz.';detail='A voz é gerada pelo serviço online que já utilizas.';}
  if(state.speaking){label='Estou a falar contigo.';detail='A personagem e o núcleo acompanham a voz.';}
  if(handsFree&&handsFree.on&&!state.busy&&!state.speaking&&!state.audioLoading){
    if(handsFree.sending){label='A reconhecer a tua voz.';detail='A transcrição é feita no teu PC.';}
    else if(Date.now()<handsFree.awakeUntil){label='Estou a ouvir.';detail='Diz o teu pedido.';}
    else{label='À escuta.';detail='Diz «Jarvis» e o teu pedido. O reconhecimento é feito no teu PC.';}
  }
  $('activity').textContent=label;$('activity-detail').textContent=detail;
  $('chat-state').textContent=state.busy?'A pensar contigo':state.speaking?'A falar':ready?(state.status?.reasoning_version==='3'?'Local · '+state.status.reasoning_label+(state.status.reasoning_enabled?' · raciocínio ativo':''):state.status?.reasoning_enabled?'Modelo local · raciocínio ativo':'Aqui contigo · modelo local'):'A ligar';
  $('stop-voice').hidden=!state.speaking&&!state.audioLoading;
  $('live-indicator').style.background=state.speaking?'#f5dcab':ready?'#83b39d':'#656b74';
}
function updateSoundUI(){
  $('sound').replaceChildren(icon(prefs.voiceAuto?'sound':'muted'));
  $('sound').setAttribute('aria-pressed',String(prefs.voiceAuto));
  $('sound').setAttribute('aria-label',prefs.voiceAuto?'Desativar voz automática':'Ativar voz automática');
  $('sound').title=prefs.voiceAuto?'Voz automática ligada':'Voz automática desligada';
  const name=(state.status?.voice||'Duarte').includes('Raquel')?'Raquel':'Duarte';
  $('voice-label').textContent=(prefs.voiceAuto?'Voz automática':'Só texto')+' · '+name;
}
let refreshing=false;
// Production panel: the nightly count of jantes to have ready (per zone). Counts only; the PDF is asked in the chat.
function productionDayWord(iso){const today=new Date();const d=new Date(iso+'T12:00:00');const diff=Math.round((d-new Date(today.getFullYear(),today.getMonth(),today.getDate(),12))/864e5);return diff===0?'Hoje':diff===1?'Amanhã':'';}
let productionDay=null;
$('pdf-button').addEventListener('click',()=>{if(state.busy)return;const d=productionDay?new Date(productionDay+'T12:00:00'):new Date();$('message').value='Jarvis, dá-me o serviço para o dia '+d.getDate()+'/'+(d.getMonth()+1);openChat();$('composer').requestSubmit();});
function renderProduction(data){
  const body=$('production-body');body.replaceChildren();
  $('zones-body').replaceChildren(element('div','empty-small','Sem contagem.'));
  if(!data.configurado){body.append(element('div','empty-small','Configura o acesso ao programa de gestão com CONFIGURAR_GESTAO.cmd.'));return;}
  if(data.erro&&!data.dias){body.append(element('div','empty-small',data.erro));return;}
  if(!data.dias){body.append(element('div','empty-small','Ainda sem contagem. Carrega em atualizar ou espera pelas '+data.hora+'.'));return;}
  const [day,next]=data.dias;const word=productionDayWord(day.dia);
  $('production-title').textContent='Produção'+(word?' · '+word:'');
  const label=element('p','prod-day');label.append(element('b','',day.rotulo));body.append(label);
  const total=element('div','prod-total');total.append(element('strong','',String(day.total)),element('span','','jantes (maquinadas + pintadas) · '+day.servicos+' serviços'));body.append(total);
  const split=element('div','prod-split');[['Maquinadas',day.maquinadas],['Pintadas',day.pintadas],['Outros',day.outros]].forEach(([n,v])=>{const b=element('div');b.append(element('strong','',String(v)),element('small','',n));split.append(b);});body.append(split);
  if(day.setor1!==undefined){const sectors=element('div','prod-sectors');[['Setor 1','antes do torno',day.setor1],['Setor 2','já passou o torno',day.setor2]].forEach(([n,h,v])=>{const b=element('div');b.append(element('strong','',String(v)),element('small','',n+' · '+h));sectors.append(b);});body.append(sectors);if(day.sem_info)body.append(element('p','prod-next','Sem informação do torno: '+day.sem_info+' jantes.'));}
  productionDay=day.dia;const zones=element('div','prod-zones');
  if(!day.zonas.length)zones.append(element('div','empty-small','Nenhum serviço com prazo neste dia.'));
  day.zonas.forEach(z=>{const r=element('div','prod-zone');r.title=z.maquinadas+' maquinadas · '+z.pintadas+' pintadas · '+z.outros+' outros · '+z.servicos+' serviços';const n=element('b','',z.total+(z.total===1?' jante':' jantes'));n.append(element('small','',z.maquinadas+'M · '+z.pintadas+'P'+(z.outros?' · '+z.outros+'O':'')));const name=element('span','',z.nome);if(z.setor1!==undefined){const chips=element('em');chips.append(element('i','chip s1','Antes '+z.setor1),element('i','chip s2','Depois '+z.setor2));if(z.sem_info)chips.append(element('i','chip','? '+z.sem_info));name.append(chips);}r.append(name,n);zones.append(r);});
  $('zones-body').replaceChildren(zones);$('zones-next').textContent='';
  if(next)$('zones-next').append(element('span','','A seguir, '+next.rotulo+': '+next.total+' jantes ('+next.maquinadas+' maquinadas, '+next.pintadas+' pintadas'+(next.setor1!==undefined?'; setor 1: '+next.setor1+', setor 2: '+next.setor2:'')+').'));
  body.append(element('div','prod-foot','Contado em '+data.gerado.slice(8,10)+'/'+data.gerado.slice(5,7)+' às '+data.gerado.slice(11,16)+' · atualiza sozinho '+(data.intervalo?'de '+data.intervalo+' em '+data.intervalo+' min (5h–22h) e ':'')+'às '+data.hora));
}
async function loadProduction(){try{renderProduction(await api('/producao'));}catch{$('production-body').replaceChildren(element('div','empty-small','Contagem indisponível.'));}}
async function refreshProduction(){const b=$('production-refresh');if(b.classList.contains('spin'))return;b.classList.add('spin');notify('A contar as jantes no programa de gestão (cerca de 1 minuto)…');try{renderProduction(await api('/producao/atualizar',{}));notify('Contagem da produção atualizada.');}catch(e){notify(e.message,true);}finally{b.classList.remove('spin');}}
// Jarvis portrait with a talking mouth. Mouth line measured on jarvis-rosto.png (fractions of the image).
const ROSTO_MOUTH={x0:.418,x1:.582,split:.430,low:.478};
let rostoImage=null;
function rostoReady(){if(!rostoImage){rostoImage=new Image();rostoImage.src='/assets/jarvis-rosto.png?v=1';}return rostoImage.complete&&rostoImage.naturalWidth>0;}
function drawRostoAt(c,left,top,w,h,opening){
  const img=rostoImage,iw=img.naturalWidth,ih=img.naturalHeight,m=ROSTO_MOUTH;
  c.drawImage(img,left,top,w,h);
  if(opening<.4)return;
  const mx=left+m.x0*w,mw=(m.x1-m.x0)*w,sy=top+m.split*h,lh=(m.low-m.split)*h;
  // the lower lip and jaw move down with the voice; the upper lip stays
  c.save();c.beginPath();c.ellipse(left+w/2,sy+lh*.45,mw/2,lh*.55+opening*.6,0,0,Math.PI*2);c.clip();
  c.drawImage(img,m.x0*iw,m.split*ih,(m.x1-m.x0)*iw,(m.low-m.split)*ih,mx,sy+opening,mw,lh);c.restore();
  // the open mouth: a dark lens, narrower than the lips so the corners stay
  const inside=c.createLinearGradient(0,sy,0,sy+opening*1.2);inside.addColorStop(0,'#010205');inside.addColorStop(1,'#0a2433');
  c.save();c.beginPath();c.ellipse(left+w/2,sy+opening*.55,mw*.40,opening*.62+.6,0,0,Math.PI*2);c.fillStyle=inside;c.fill();
  c.strokeStyle='rgba(120,215,255,.25)';c.lineWidth=Math.max(.6,w*.002);c.stroke();c.restore();
}
let mouthLevel=0;
function mouthOpening(volume,h){const target=state.speaking?Math.min(.016,volume*.05)*h:0;mouthLevel=mouthLevel*.55+target*.45;return mouthLevel;}
function drawPersona(volume){
  const canvas=$('persona-canvas');if(!canvas||!rostoReady())return;
  const rect=canvas.getBoundingClientRect();if(!rect.width)return;const dpr=Math.min(devicePixelRatio||1,2);
  if(canvas.width!==Math.round(rect.width*dpr)||canvas.height!==Math.round(rect.height*dpr)){canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);}
  const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,rect.width,rect.height);
  const ratio=rostoImage.naturalWidth/rostoImage.naturalHeight;let h=rect.height,w=h*ratio;if(w>rect.width){w=rect.width;h=w/ratio;}
  drawRostoAt(c,(rect.width-w)/2,(rect.height-h)/2,w,h,mouthOpening(volume,h));
}
// Production notes (written on the big screen): listed on the main screen and recalled every 2 hours.
const NOTES_EVERY=2*60*60*1000;let notesCache=[];
function noteLine(n,withButton){
  const row=element('div','note-mini');const text=element('p','',n.texto);
  const who=[...new Set(n.jantes.map(j=>j.cliente))].slice(0,3).join(', ');
  text.append(element('small','',n.jantes.length+' jante'+(n.jantes.length!==1?'s':'')+(who?' · '+who:'')+' · '+n.criada.slice(8,10)+'/'+n.criada.slice(5,7)));row.append(text);
  if(withButton){const done=element('button','','✓ Feita');done.type='button';done.addEventListener('click',()=>safe(async()=>{await api('/producao/notas',{acao:'feita',id:n.id,feita:true});await loadNotes();}));row.append(done);}
  return row;
}
async function loadAlerts(){
  // 🚨 Jantes que já deviam ter passado o torno (mesma lista do Ecrã de produção).
  const box=$('prod-alert');let d;try{d=await api('/producao/alertas');}catch{return;}
  const all=(d.vermelho||[]).concat(d.laranja||[]);if(!all.length){box.hidden=true;return;}
  const red=(d.vermelho||[]).length;box.hidden=false;box.classList.toggle('orange',!red);box.replaceChildren();
  const t=element('span','',red?'Jantes demasiado atrasadas':'Jantes de hoje em risco');t.append(element('small','','Ainda não passaram o torno · tocar para ver'));
  box.append(element('b','','🚨 '+d.jantes),t);
}
async function loadAcoes(){
  // Ações a corrigir: só o número das que faltam, no cartão do lado direito.
  try{const data=await api('/acoes/lista');const n=data.acoes.filter(x=>!x.feita).length;$('acoes-count').textContent=n?n+' por corrigir':'Escrever o que é preciso corrigir';}catch{}
}
async function loadSeguranca(){
  // Segurança: só o resumo (tudo OK ou quantos avisos) no cartão do lado direito.
  try{const d=await api('/seguranca/estado');const red=d.avisos.filter(a=>a.nivel==='vermelho').length,warn=d.avisos.filter(a=>a.nivel!=='info').length;
    $('seg-count').textContent=red?'⚠ '+red+' problema'+(red>1?'s':'')+' a ver':warn?warn+' aviso'+(warn>1?'s':''):'Tudo OK · cópia '+(d.copias.ultima_valida?d.copias.ultima_valida.slice(8,10)+'/'+d.copias.ultima_valida.slice(5,7):'—');
    $('seg-icon').textContent=red?'🚨':'🛡️';}catch{}
}
async function loadNotes(){
  try{const data=await api('/producao/notas');notesCache=data.notas.filter(n=>!n.feita);}catch{$('notes-body').replaceChildren(element('div','empty-small','Notas indisponíveis.'));return;}
  $('notes-count').textContent=notesCache.length?String(notesCache.length):'';
  const body=$('notes-body');body.replaceChildren();
  if(!notesCache.length){body.append(element('div','empty-small','Sem notas por tratar. Cria notas nas listas do ecrã grande da produção.'));return;}
  const list=element('div','notes-scroll');notesCache.forEach(n=>list.append(noteLine(n,true)));body.append(list);
}
function remindNotes(force=false){
  const hour=new Date().getHours();if(!force&&(hour>=22||hour<6))return;  // quiet at night
  let last=0;try{last=Number(localStorage.getItem('jarvis-notes-alert')||0);}catch{}
  if(!force&&Date.now()-last<NOTES_EVERY)return;
  if(!notesCache.length||$('notes-alert').open)return;
  const body=$('notes-alert-body');body.replaceChildren();notesCache.slice(0,6).forEach(n=>body.append(noteLine(n,false)));
  if(notesCache.length>6)body.append(element('div','empty-small','e mais '+(notesCache.length-6)+' nota(s).'));
  $('notes-alert-title').textContent=notesCache.length===1?'Tens 1 nota por tratar':'Tens '+notesCache.length+' notas por tratar';
  try{localStorage.setItem('jarvis-notes-alert',String(Date.now()));}catch{}
  try{prepareAudio();if(audioContext){const o=audioContext.createOscillator(),g=audioContext.createGain();o.frequency.value=880;g.gain.value=.06;o.connect(g).connect(audioContext.destination);o.start();o.stop(audioContext.currentTime+.18);}}catch{}
  $('notes-alert').showModal();
}
async function refresh(quiet=false){
  if(refreshing)return;refreshing=true;$('refresh').classList.add('spin');
  try{
    const results=await Promise.allSettled([api('/status'),api('/tasks'),api('/memories'),api('/documents')]);
    const errors=[];
    for(let i=0;i<results.length;i++){
      const r=results[i];if(r.status==='rejected'){errors.push(r.reason.message);if(i===0)state.connected=false;continue;}
      if(i===0){state.status=r.value;state.connected=true;}
      if(i===1)state.tasks=r.value.tasks;
      if(i===2){state.memories=r.value.memories;state.memoryInfo=r.value.info;}
      if(i===3)state.documents=r.value.documents;
    }
    if((state.status?.ui_version!=='5.0'||state.status?.reasoning_version!=='3'||state.status?.actions_version!=='1'||state.status?.model_families_version!=='2'||state.status?.memory_version!=='1')&&state.connected)throw Error('Fecha a janela da Central e volta a abrir Iniciar_Central.cmd para concluir a atualização.');
    $('connection').classList.toggle('online',state.connected&&!!state.status?.ollama);
    $('connection').lastElementChild.textContent=state.connected?(state.status.ollama?'Inteligência local':'Ollama desligado'):'Central desligada';
    $('memory-total').textContent=state.connected?String(state.status.memory_count):'—';
    $('task-total').textContent=state.connected?String(state.tasks.filter(t=>!t.done).length):'—';
    $('document-total').textContent=state.connected?String(state.documents.length):'—';
    $('model-label').textContent=state.status?'MODELO LOCAL / '+state.status.selected_model.toUpperCase():'INTELIGÊNCIA LOCAL';
    if(!errors.length)$('sync-label').textContent='Sincronizado às '+dateText(Date.now(),{hour:'2-digit',minute:'2-digit'})+' · dados locais';
    renderTaskPreview();renderMemoryPreview();renderGroups();updateSoundUI();updateActivity();
    if(errors.length&&!quiet)throw Error(errors.join('\n'));
  }finally{refreshing=false;$('refresh').classList.remove('spin');}
}
function taskRow(task,withDelete=false){
  const row=element('div','task-item'+(task.done?' done':''));
  const check=element('input');check.type='checkbox';check.checked=!!task.done;check.setAttribute('aria-label',(task.done?'Reabrir ':'Concluir ')+task.title);
  check.addEventListener('change',()=>safe(async()=>{check.disabled=true;try{await api('/tasks',{action:'task_done',id:task.id,done:check.checked});await refresh();if(withDelete)openTasks();}catch(e){check.checked=!!task.done;throw e;}finally{check.disabled=false;}}));
  row.append(check,element('span','',task.title));
  if(withDelete)row.append(actionButton('Apagar tarefa',async()=>{if(!confirm('Apagar a tarefa «'+task.title+'»?'))return;await api('/tasks',{action:'task_delete',id:task.id});await refresh();openTasks();},'trash'));
  else row.append(element('small','task-id',String(task.id).padStart(2,'0')));
  return row;
}
// Tarefas importantes: coisas sem data que não se podem esquecer. Mesma lista local que o Jarvis usa na conversa.
function renderTaskPreview(){
  if($('task-preview').querySelector('.lc-task-input'))return;  // não apagar o que está a ser escrito na atualização automática
  const list=$('task-preview');list.replaceChildren();const pending=state.tasks.filter(t=>!t.done);
  $('focus-count').textContent=pending.length?String(pending.length):'';
  if(!pending.length){list.append(element('div','empty-small',state.connected?'Nada pendente. Escreve acima o que não podes esquecer.':'A ligar à Central…'));return;}
  pending.forEach(t=>{const row=element('div','lc-task');
    const done=element('button','lc-task-done');done.type='button';done.title='Já está tratado';done.setAttribute('aria-label','Concluir '+t.title);done.append(icon('check'));
    done.addEventListener('click',()=>safe(async()=>{row.classList.add('leaving');done.disabled=true;try{await api('/tasks',{action:'task_done',id:t.id,done:true});notify('Tarefa concluída.');await refresh(true);}catch(e){row.classList.remove('leaving');done.disabled=false;throw e;}}));
    const del=element('button','lc-task-del');del.type='button';del.title='Apagar';del.setAttribute('aria-label','Apagar '+t.title);del.append(icon('trash'));
    del.addEventListener('click',()=>safe(async()=>{if(!confirm('Apagar a tarefa «'+t.title+'»?'))return;await api('/tasks',{action:'task_delete',id:t.id});await refresh(true);}));
    const text=element('span','lc-task-text',t.title);text.title='Toca para editar';text.addEventListener('click',()=>editTask(row,text,t));
    const edit=element('button','lc-task-edit');edit.type='button';edit.title='Editar';edit.setAttribute('aria-label','Editar '+t.title);edit.append(icon('edit'));edit.addEventListener('click',()=>editTask(row,text,t));
    row.append(done,text,edit,del);list.append(row);});
}
// Editar no próprio sítio: Enter ou sair da caixa guarda, Esc cancela.
function editTask(row,text,t){
  if(row.querySelector('input'))return;const input=element('input','lc-task-input');input.type='text';input.maxLength=500;input.value=t.title;
  let finished=false;const finish=async save=>{if(finished)return;finished=true;const title=input.value.trim();
    if(!save||!title||title===t.title){input.replaceWith(text);return;}
    input.disabled=true;try{await api('/tasks',{action:'task_edit',id:t.id,title});t.title=title;text.textContent=title;input.replaceWith(text);notify('Tarefa alterada.');await refresh(true);}
    catch(e){input.replaceWith(text);notify(/desconhecida/i.test(e.message)?'Para editar, reinicia a Central (Iniciar_Central.cmd) uma vez.':e.message,true);}};
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();finish(true);}else if(e.key==='Escape'){e.preventDefault();finish(false);}});
  input.addEventListener('blur',()=>finish(true));
  text.replaceWith(input);input.focus();input.setSelectionRange(input.value.length,input.value.length);
}
$('task-add').addEventListener('submit',e=>{e.preventDefault();const input=$('task-title');const title=input.value.trim();if(!title)return;
  safe(async()=>{input.disabled=true;try{await api('/tasks',{action:'task_add',title});input.value='';await refresh(true);}finally{input.disabled=false;input.focus();}});});
function renderMemoryPreview(){
  const list=$('memory-preview');list.replaceChildren();
  if(!state.memories.length){list.append(element('div','empty-small','O que quiseres guardar começa aqui.'));return;}
  state.memories.slice(0,3).forEach(memory=>{const b=element('button','memory-snippet');b.append(element('small','',memory.pinned?'✦ MEMÓRIA PRINCIPAL':'MEMÓRIA #'+memory.id),element('span','',memory.content));b.addEventListener('click',()=>openMemory({highlight:memory.id}));list.append(b);});
}
function renderGroups(){
  state.groups=groupDefinitions.map(group=>({...group,memories:state.memories.filter(m=>group.test.test(fold(m.content)))})).filter(g=>g.memories.length);
  const rest=state.memories.filter(m=>!state.groups.some(g=>g.memories.includes(m)));
  if(rest.length)state.groups.push({id:'outros',name:'Outras notas',memories:rest});
  const list=$('orbit-nodes');list.replaceChildren();
  state.groups.forEach((group,i)=>{const b=element('button','orbit-node');b.style.left=coordinates[i][0]+'%';b.style.top=coordinates[i][1]+'%';b.append(element('i'),element('span','',group.name),element('small','',String(group.memories.length).padStart(2,'0')));b.title='Abrir '+group.memories.length+' memórias de '+group.name;b.addEventListener('click',()=>openMemory({group:group.id}));list.append(b);});
  $('node-count').textContent=state.connected?state.memories.length+' FACTOS · '+state.groups.length+' LIGAÇÕES':'A SINCRONIZAR';
}
function setDrawer(title){
  $('drawer-title').textContent=title;$('drawer-body').replaceChildren();
  if(!$('drawer').open)$('drawer').showModal();
  return $('drawer-body');
}
function openTasks(){
  const body=setDrawer('O que temos por fazer');
  body.append(element('p','help','A tua lista local, partilhada com o Jarvis. Marca uma tarefa quando estiver concluída.'));
  const form=element('form');const label=element('label','','Nova tarefa');const input=element('input');input.type='text';input.maxLength=500;input.required=true;input.placeholder='O que precisas de tratar?';input.id='drawer-task-title';label.htmlFor=input.id;
  const submit=element('button','gold-button','Adicionar tarefa');submit.type='submit';form.append(label,input,submit);
  form.addEventListener('submit',e=>{e.preventDefault();safe(async()=>{submit.disabled=true;try{await api('/tasks',{action:'task_add',title:input.value});await refresh();openTasks();}finally{submit.disabled=false;}});});
  body.append(form,element('h3','drawer-section-title','EM ABERTO'));
  const pending=state.tasks.filter(t=>!t.done);if(!pending.length)body.append(element('p','help','Não tens tarefas pendentes.'));
  pending.forEach(t=>body.append(taskRow(t,true)));
  const done=state.tasks.filter(t=>t.done);if(done.length){const details=element('details');details.style.marginTop='24px';details.append(element('summary','drawer-section-title','CONCLUÍDAS · '+done.length));done.forEach(t=>details.append(taskRow(t,true)));body.append(details);}
}
function openMemory(options={}){
  const body=setDrawer(options.group?state.groups.find(g=>g.id===options.group)?.name||'Memória':'A tua memória');
  const kinds={fact:'Facto',preference:'Preferência',rule:'Regra de trabalho'};
  body.append(element('p','help','Factos, preferências e regras guardados no teu computador. Corrigir substitui o valor usado nas próximas consultas e conserva até 20 versões anteriores. Uma data de validade limita quando a memória pode ser fornecida ao modelo.'));
  body.append(element('p','help','Também podes dizer: Aprende que … ou Guarda esta regra: … A conversa livre não é gravada automaticamente como um ensinamento e não treina o modelo.'));
  const selected=state.memoryInfo?.last_selection||[];
  if(selected.length)body.append(element('p','help','Memórias fornecidas no último pedido ao modelo: '+selected.map(id=>'#'+id).join(', ')+'.'));
  const form=element('form');const label=element('label','','O que queres que eu guarde?');const content=element('textarea');content.maxLength=1500;content.required=true;content.placeholder='Uma informação importante sobre ti ou sobre a Rucodel…';content.id='memory-content';label.htmlFor=content.id;
  const kind=element('select');kind.setAttribute('aria-label','Tipo de memória');Object.entries(kinds).forEach(([id,name])=>{const choice=element('option','',name);choice.value=id;kind.append(choice);});kind.value='fact';
  const topic=element('input');topic.type='text';topic.maxLength=120;topic.placeholder='Tema, por exemplo Rucodel · pintura';topic.setAttribute('aria-label','Tema da memória');
  const expiry=element('input');expiry.type='date';expiry.setAttribute('aria-label','Validade da memória');
  let editId=null,editRevision=null;const row=element('div','row');const pinLabel=element('label');const pin=element('input');pin.type='checkbox';pinLabel.append(pin,document.createTextNode(' Memória principal'));
  const save=element('button','gold-button','Guardar memória');save.type='submit';row.append(pinLabel,save);form.append(label,content,element('label','','Tipo'),kind,element('label','','Tema · opcional'),topic,element('label','','Válida até · opcional'),expiry,row);
  form.addEventListener('submit',e=>{e.preventDefault();safe(async()=>{save.disabled=true;try{await api('/memories',{content:content.value,id:editId,pinned:pin.checked,kind:kind.value,topic:topic.value,valid_until:expiry.value,expected_revision:editRevision});await refresh();openMemory();notify('Memória guardada. Já pode ser usada nas respostas.');}finally{save.disabled=false;}});});body.append(form);
  const search=element('input');search.type='search';search.placeholder='Procurar nas memórias…';search.setAttribute('aria-label','Procurar nas memórias');search.style.marginTop='24px';body.append(search);
  const list=element('div');body.append(list);
  const group=options.group?state.groups.find(g=>g.id===options.group):null;
  function render(){
    list.replaceChildren();const candidates=group?group.memories:state.memories;
    const filtered=candidates.filter(m=>fold(m.content).includes(fold(search.value))||String(m.id)===search.value.trim());
    if(!filtered.length)list.append(element('p','help','Não encontrei memórias para esta pesquisa.'));
    filtered.forEach(memory=>{
      const card=element('article','memory-card');if(memory.id===options.highlight)card.style.borderColor='#ddbd8080';
      const top=element('div','row');top.append(element('small','',(memory.pinned?'✦ PRINCIPAL · ':'')+(kinds[memory.kind]||'Facto')+' #'+memory.id));
      const actions=element('div','memory-actions');
      actions.append(actionButton(memory.pinned?'Desafixar':'Fixar entre as principais',async()=>{await api('/memories',{id:memory.id,content:memory.content,pinned:!memory.pinned,expected_revision:memory.revision});await refresh();openMemory(options);},'star'));
      actions.append(actionButton('Editar memória',()=>{editId=memory.id;editRevision=memory.revision;content.value=memory.content;pin.checked=!!memory.pinned;kind.value=memory.kind||'fact';topic.value=memory.topic||'';expiry.value=memory.valid_until||'';save.textContent='Guardar correção';content.focus();content.scrollIntoView({block:'center',behavior:prefs.reduced?'instant':'smooth'});},'edit'));
      actions.append(actionButton('Retirar memória',async()=>{if(!confirm('Retirar esta memória e o seu histórico de correções? O texto continuará nas conversas onde já aparece.'))return;await api('/memories',{action:'delete',id:memory.id,expected_revision:memory.revision});await refresh();openMemory(options);},'trash'));
      top.append(actions);card.append(top,element('p','',memory.content));
      card.append(element('p','help',(memory.topic?memory.topic+' · ':'')+(memory.source||'Memória anterior')+' · '+dateText(memory.updated_at,{day:'2-digit',month:'2-digit',year:'numeric'})));
      if(memory.valid_until)card.append(element('p','help','Válida até '+memory.valid_until+'. Depois dessa data é excluída das consultas ao modelo.'));
      if(memory.revision>1){
        const history=element('button','text-link','Ver correções');history.type='button';
        history.addEventListener('click',()=>safe(async()=>{history.disabled=true;try{const data=await api('/memories/'+memory.id+'/history');const details=element('details');details.open=true;details.append(element('summary','','Versões anteriores · '+data.history.length));for(const old of data.history)details.append(element('p','help',dateText(old.changed_at,{day:'2-digit',month:'2-digit',year:'numeric'})+' · '+old.content));card.append(details);history.hidden=true;}finally{history.disabled=false;}}));card.append(history);
      }
      list.append(card);
    });
  }
  search.addEventListener('input',render);render();
}
function openDocuments(){
  const body=setDrawer('Os teus documentos');
  body.append(element('p','help','Adiciona notas e documentos de texto para o Jarvis consultar excertos relevantes. Formatos TXT, Markdown e CSV, em UTF-8.'));
  const file=element('input');file.type='file';file.accept='.txt,.md,.csv';file.setAttribute('aria-label','Escolher documento de texto');file.style.maxWidth='100%';
  const upload=element('button','gold-button','Importar documento');upload.type='button';upload.style.marginTop='15px';
  upload.addEventListener('click',()=>safe(async()=>{const selected=file.files[0];if(!selected)throw Error('Escolhe primeiro um ficheiro TXT, MD ou CSV.');if(!/\.(txt|md|csv)$/i.test(selected.name)||selected.size>900000)throw Error('Usa um ficheiro de texto TXT, MD ou CSV com menos de 900 KB.');const text=await selected.text();if(text.length>200000)throw Error('O documento excede o limite de 200 000 caracteres.');upload.disabled=true;try{await api('/documents',{action:'document_add',name:selected.name,content:text});await refresh();openDocuments();notify('Documento adicionado à memória documental do Jarvis.');}finally{upload.disabled=false;}}));body.append(file,upload);
  if(!state.documents.length)body.append(element('p','help','Ainda não há documentos nesta base. Os anexos anteriores do Open WebUI continuam no histórico dessa interface.'));
  state.documents.forEach(doc=>{const card=element('article','document-card');const row=element('div','row');const title=element('div');title.append(element('strong','',doc.name),element('small','',new Intl.NumberFormat('pt-PT').format(doc.characters)+' caracteres'));row.append(title,actionButton('Retirar documento',async()=>{if(!confirm('Retirar «'+doc.name+'» desta base?'))return;await api('/documents',{action:'document_delete',id:doc.id});await refresh();openDocuments();},'trash'));const ask=element('button','text-link','Perguntar sobre este documento');ask.type='button';ask.append(icon('arrow'));ask.addEventListener('click',()=>{$('drawer').close();$('message').value='Resume o documento '+doc.name+'.';$('message').focus();});card.append(row,ask);body.append(card);});
}
function openSettings(){
  const body=setDrawer('Ao teu ritmo');
  const intelligence=element('button','gold-button','Inteligência local');intelligence.type='button';intelligence.addEventListener('click',()=>safe(openIntelligence));body.append(intelligence);
  body.append(element('p','help','Escolhe o modo de resposta e compara modelos no teu computador. As contas e os horários têm ferramentas de cálculo local.'));
  const voiceRow=element('div');voiceRow.append(element('label','','Voz do Jarvis'));
  const select=element('select');select.setAttribute('aria-label','Voz do Jarvis');[['pt-PT-DuarteNeural','Duarte · português de Portugal'],['pt-PT-RaquelNeural','Raquel · português de Portugal']].forEach(([id,name])=>{const option=element('option','',name);option.value=id;select.append(option);});select.value=state.status?.voice||'pt-PT-DuarteNeural';voiceRow.append(select);body.append(voiceRow);
  select.addEventListener('change',()=>safe(async()=>{await api('/voice',{voice:select.value});await refresh();notify('Voz guardada.');}));
  const test=element('button','subtle-button','Ouvir a voz');test.addEventListener('click',()=>safe(()=>speak('Olá, meu rei. Sou o Jarvis. O teu universo está aqui, e vamos tratar de uma coisa de cada vez.')));body.append(test);
  body.append(element('p','help','Duarte e Raquel usam o serviço de voz online Microsoft Edge. O texto a ler é enviado para esse serviço; a inteligência continua no teu computador.'));
  const auto=element('input');auto.type='checkbox';auto.checked=prefs.voiceAuto;auto.setAttribute('aria-label','Ler respostas automaticamente');auto.addEventListener('change',()=>{prefs.voiceAuto=auto.checked;savePrefs();if(!prefs.voiceAuto)stopSpeech();updateSoundUI();});
  const autoRow=element('label','setting-row');autoRow.append(element('span','','Ler respostas automaticamente'),auto);body.append(autoRow);
  const motion=element('input');motion.type='checkbox';motion.checked=prefs.reduced;motion.setAttribute('aria-label','Reduzir movimento');motion.addEventListener('change',()=>{prefs.reduced=motion.checked;document.body.classList.toggle('reduced-motion',prefs.reduced);savePrefs();});const motionRow=element('label','setting-row');motionRow.append(element('span','','Reduzir o movimento dos anéis'),motion);body.append(motionRow);
  body.append(element('h3','drawer-section-title','OS TEUS DADOS'));
  const backup=element('button','subtle-button','Criar cópia de segurança');backup.addEventListener('click',()=>safe(async()=>{backup.disabled=true;try{const result=await api('/backup',{});notify('Cópia criada em:\n'+result.path);}finally{backup.disabled=false;}}));body.append(backup);
  body.append(element('p','help','Inclui a base de memórias, tarefas e conversas deste painel. As conversas anteriores do Open WebUI mantêm-se na sua base própria.'));
  const old=element('a','external-link','Abrir conversas anteriores do Open WebUI ↗');old.href='http://127.0.0.1:8088';old.target='_blank';old.rel='noopener';body.append(old);
  const exportChat=element('button','text-link','Exportar a conversa atual');exportChat.type='button';exportChat.append(icon('download'));exportChat.addEventListener('click',()=>{if(!state.messages.length){notify('Ainda não há mensagens nesta conversa.');return;}const blob=new Blob([JSON.stringify({title:state.chat?.title||'Jarvis',messages:state.messages},null,2)],{type:'application/json'});const a=element('a');a.href=URL.createObjectURL(blob);a.download='Jarvis_conversa_'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});body.append(exportChat);
  body.append(element('h3','drawer-section-title','OS TEUS MONITORES'));
  const screens=element('a','external-link','Organizar os meus ecrãs ↗');screens.href='/screens';screens.target='_blank';screens.rel='noopener';body.append(screens);
  body.append(element('p','help','Abre janelas próprias para a agenda, os pendentes, as notas da Rucodel e o núcleo do Jarvis. Arrasta cada janela para o monitor que quiseres.'));
  body.append(element('h3','drawer-section-title','LIGAÇÕES'));
  const notion=element('button','gold-button','Ligar Notion');notion.type='button';notion.addEventListener('click',()=>safe(openNotion));body.append(notion);
  const google=element('button','gold-button','Ligar Google Agenda');google.type='button';google.addEventListener('click',()=>safe(openGoogle));body.append(google);
  const daily=element('button','subtle-button','Ver resumo do dia');daily.type='button';daily.addEventListener('click',()=>safe(openDaily));body.append(daily);
  body.append(element('p','help','Notion e Google Agenda têm autorizações próprias. As credenciais ficam protegidas pelo teu Windows.'));

  const autoDaily=element('input');autoDaily.type='checkbox';autoDaily.checked=prefs.dailyAuto!==false;autoDaily.addEventListener('change',()=>{prefs.dailyAuto=autoDaily.checked;savePrefs();});const dailyRow=element('label','setting-row');dailyRow.append(element('span','','Mostrar resumo ao abrir, uma vez por dia'),autoDaily);body.append(dailyRow);
}
let intelligenceView=0;
async function openIntelligence(){
  const view=++intelligenceView;
  const body=setDrawer('Inteligência local');
  const active=()=>view===intelligenceView&&$('drawer').open&&$('drawer-title').textContent==='Inteligência local';
  body.append(element('p','help','Tudo corre no Ollama deste computador. Equilibrado mantém o raciocínio com respostas mais concisas. Aprofundado permite gerar mais texto antes de concluir. Direto desativa o raciocínio para responder mais depressa; as ferramentas de cálculo continuam disponíveis.'));
  const info=await api('/intelligence');
  if(!active())return;
  const installed=(state.status?.models||[]).filter(m=>/^qwen3(?:\.(?:5|6|8))?:[\w.\-]+$/.test(m)&&!m.toLowerCase().includes('cloud'));
  const model=element('select');model.setAttribute('aria-label','Modelo local');
  installed.forEach(name=>{const o=element('option','',name);o.value=name;model.append(o);});model.value=info.model;
  const profile=element('select');profile.setAttribute('aria-label','Modo de resposta');
  [['balanced','Equilibrado · raciocínio e resposta concisa'],['deep','Aprofundado · mais tempo para concluir'],['direct','Direto · mais rápido, sem raciocínio']].forEach(([id,title])=>{const o=element('option','',title);o.value=id;profile.append(o);});profile.value=info.profile;
  body.append(element('label','','Modelo instalado'),model,element('label','','Modo de resposta'),profile);
  const save=element('button','gold-button','Guardar inteligência');save.type='button';body.append(save);
  save.addEventListener('click',()=>safe(async()=>{save.disabled=true;try{await api('/intelligence',{action:'configure',model:model.value,profile:profile.value});await refresh();notify('Modelo e modo guardados neste computador.');}finally{save.disabled=false;}}));
  const last=element('p','help');body.append(last);
  if(info.last_run){const run=info.last_run;last.textContent='Última resposta do modelo: '+run.seconds+' s · '+run.model+(run.tools.length?' · ferramentas: '+run.tools.join(', '):'')+'.';}
  else last.textContent='Depois de uma pergunta ao modelo, aparece aqui o tempo real e as ferramentas utilizadas.';
  body.append(element('h3','drawer-section-title','COMPARAR SEM ADIVINHAR'));
  body.append(element('p','help','Três testes sintéticos do modelo, sem ferramentas: conflito de horários, desconto e correção em conversa. Medem acerto e tempo nesta máquina, incluindo o carregamento do modelo; não garantem todas as respostas. A comparação não lê memórias nem cria tarefas. Enquanto corre, o modelo fica ocupado.'));
  const second=element('select');second.setAttribute('aria-label','Segundo modelo para comparar');
  const none=element('option','','Testar só o modelo escolhido');none.value='';second.append(none);
  installed.forEach(name=>{const o=element('option','',name);o.value=name;second.append(o);});second.value='';body.append(second);
  const test=element('button','subtle-button','Iniciar testes locais');test.type='button';body.append(test);
  const progress=element('p','help'),results=element('div','intelligence-results');progress.setAttribute('role','status');body.append(progress,results);
  let timer;
  const show=job=>{
    const running=job.state==='running';test.disabled=running;save.disabled=running;
    progress.textContent=job.current+' · '+job.results.length+'/'+job.total+(running?' · pode demorar alguns minutos':'')+(job.error?' · '+job.error:'');
    results.replaceChildren();
    for(const name of job.models){
      const rows=job.results.filter(r=>r.model===name);if(!rows.length)continue;
      const summary=element('article','memory-card');summary.append(element('strong','',name+' · '+rows.filter(r=>r.passed).length+'/'+rows.length+' testes certos · '+rows.reduce((sum,r)=>sum+r.seconds,0).toFixed(1)+' s no total'));
      for(const row of rows){
        const item=element('details','benchmark-case');item.append(element('summary','',row.title+' · '+(row.passed?'Certo':row.error?'Sem resultado':'Falhou')+' · '+row.seconds+' s'),element('p','help','Esperado: '+JSON.stringify(row.expected)),element('p','help',row.error?'Erro: '+row.error:'Obtido: '+JSON.stringify(row.answer)));summary.append(item);
      }
      results.append(summary);
    }
    if(!running){prefs.localBenchmark=null;savePrefs();}
  };
  const poll=async id=>{
    if(!active())return;
    try{const job=await api('/intelligence/tests/'+id);if(!active())return;show(job);if(job.state==='running')timer=setTimeout(()=>poll(id),1500);}
    catch(e){if(active()){progress.textContent=e.message;test.disabled=false;save.disabled=false;prefs.localBenchmark=null;savePrefs();}}
  };
  test.addEventListener('click',()=>safe(async()=>{
    const models=[model.value];if(second.value&&second.value!==model.value)models.push(second.value);
    test.disabled=true;save.disabled=true;progress.textContent='A iniciar a comparação no teu computador…';
    try{const job=await api('/intelligence',{action:'test',models,profile:profile.value});prefs.localBenchmark=job.id;savePrefs();show(job);clearTimeout(timer);if(job.state==='running')timer=setTimeout(()=>poll(job.id),1000);}
    catch(e){test.disabled=false;save.disabled=false;progress.textContent=e.message;throw e;}
  }));
  if(prefs.localBenchmark)poll(prefs.localBenchmark);
  body.append(element('h3','drawer-section-title','OUTRO MODELO LOCAL · OPCIONAL'));
  body.append(element('p','help','Para comparar um modelo mais recente, atualiza o Ollama e descarrega o Qwen3.5 9B Q4 pelo PowerShell. O ficheiro ocupa cerca de 6,6 GB; o funcionamento exige memória adicional. Numa gráfica de 8 GB pode usar também RAM e ficar mais lento. Depois carrega em Atualizar modelos e compara com o atual. O download não muda o modelo ativo.'));
  body.append(element('code','model-command','ollama pull qwen3.5:9b-q4_K_M'));
  body.append(element('p','help','Aceita modelos locais Qwen3, Qwen3.5, Qwen3.6 e Qwen3.8 instalados. O chat continua a receber texto: escolher um modelo com visão não ativa a leitura do ecrã. Os testes usam os mesmos parâmetros de amostragem para comparação; a conversa respeita os valores do modelo nas gerações mais recentes.'));
  const reload=element('button','subtle-button','Atualizar modelos');reload.type='button';reload.addEventListener('click',()=>safe(async()=>{await refresh();await openIntelligence();}));body.append(reload);
}
async function openNotion(){
  const body=setDrawer('Ligar Notion');
  body.append(element('p','help','Conexão: Jarvis Rucodel. Copia o token de API no Notion e cola-o aqui. Fica protegido pelo teu utilizador Windows neste computador.'));
  const status=element('p','help','A verificar a configuração…');body.append(status);
  const token=element('input');token.type='password';token.autocomplete='off';token.spellcheck=false;token.placeholder='Token de API do Notion';token.setAttribute('aria-label','Token de API do Notion');token.style.width='100%';body.append(token);
  const save=element('button','gold-button','Guardar e testar ligação');save.type='button';body.append(save);
  const test=element('button','subtle-button','Testar ligação guardada');test.type='button';body.append(test);
  const disconnect=element('button','text-link','Desligar Notion neste computador');disconnect.type='button';body.append(disconnect);
  const show=data=>{status.textContent=data.verified?'Ligação testada: acesso ao Índice e ao Diário confirmado.':data.configured?'Token guardado. Testa a ligação para confirmar o acesso atual.':'Ainda não há token guardado neste Jarvis.';test.disabled=!data.configured;disconnect.hidden=!data.configured;};
  show(await api('/connections/notion'));
  save.addEventListener('click',()=>safe(async()=>{save.disabled=true;status.textContent='A testar o acesso ao Índice e ao Diário…';const value=token.value;token.value='';try{show(await api('/connections/notion',{action:'connect',token:value}));notify('Notion ligado. Já podes criar tarefas datadas no Diário.');}catch(e){status.textContent='Ligação não guardada: '+e.message;throw e;}finally{save.disabled=false;}}));
  test.addEventListener('click',()=>safe(async()=>{test.disabled=true;try{show(await api('/connections/notion',{action:'test'}));}catch(e){status.textContent='Não consegui confirmar o acesso: '+e.message;throw e;}finally{test.disabled=false;}}));
  disconnect.addEventListener('click',()=>safe(async()=>{show(await api('/connections/notion',{action:'disconnect'}));notify('Credencial removida deste Jarvis.');}));
  body.append(element('h3','drawer-section-title','NO DIÁRIO CERTO'));
  body.append(element('p','help','As tarefas são adicionadas como caixas por concluir ao registo do dia em Índice → Diário → Registos do diário. O Jarvis utiliza os campos Dia e Data existentes.'));
  const title=element('input');title.type='text';title.placeholder='Descrição da tarefa';title.setAttribute('aria-label','Descrição da tarefa no Notion');title.style.width='100%';
  const day=element('input');day.type='date';day.setAttribute('aria-label','Data da tarefa');const now=lisbonParts();day.value=now.year+'-'+String(now.month).padStart(2,'0')+'-'+String(now.day).padStart(2,'0');
  const create=element('button','gold-button','Criar tarefa no Notion');create.type='button';create.addEventListener('click',()=>safe(async()=>{if(!title.value.trim())throw Error('Escreve a tarefa.');create.disabled=true;try{const result=await api('/notion/tasks',{title:title.value,date:day.value});title.value='';notify('Tarefa criada no Diário de '+result.date+'.');}finally{create.disabled=false;}}));body.append(title,day,create);
  body.append(element('p','help','Também podes escrever na conversa: Cria uma tarefa para amanhã: telefonar ao fornecedor. Para consultar: Resumo do dia. O acesso ao Índice fica disponível para futuras ligações aos projetos; esta atualização consulta o Diário.'));
  const daily=element('button','subtle-button','Ver resumo do dia');daily.type='button';daily.addEventListener('click',()=>safe(openDaily));body.append(daily);
}
function googleEventTime(event){
  return event.all_day?'Todo o dia':dateText(event.start,{hour:'2-digit',minute:'2-digit'});
}
function appendGoogleEvents(body,data){
  body.append(element('p','help',data.calendar_name+' · '+data.date+' · horas de Lisboa'));
  if(!data.events.length)body.append(element('p','help','Sem compromissos nesta agenda para este dia.'));
  data.events.forEach(event=>{
    const card=element('article','document-card');card.append(element('strong','',googleEventTime(event)+' · '+event.title));
    if(event.location)card.append(element('p','help',event.location));
    if(/^https:\/\/(?:calendar\.google\.com|www\.google\.com)\//.test(event.url)){const link=element('a','external-link','Abrir na Google Agenda ↗');link.href=event.url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
    body.append(card);
  });
  if(data.partial)body.append(element('p','help','Consulta parcial: existem mais eventos por consultar.'));
}
async function openGoogle(){
  const body=setDrawer('Ligar Google Agenda');
  body.append(element('p','help','Escolhe o ficheiro JSON do cliente «App para computador» que criaste no projeto Jarvis Rucodel. A autorização abre no Google; o ficheiro e a credencial ficam neste computador.'));
  const status=element('p','help','A consultar a configuração…');status.setAttribute('role','status');body.append(status);
  const file=element('input');file.type='file';file.accept='.json,application/json';file.setAttribute('aria-label','JSON do cliente Google para computador');file.style.maxWidth='100%';body.append(file);
  const connect=element('button','gold-button','Preparar autorização Google');connect.type='button';body.append(connect);
  const authorize=element('a','external-link','Autorizar no Google ↗');authorize.target='_blank';authorize.rel='noopener noreferrer';authorize.hidden=true;body.append(authorize);
  const test=element('button','subtle-button','Testar e carregar agendas');test.type='button';body.append(test);
  const disconnect=element('button','text-link','Desligar Google neste computador');disconnect.type='button';body.append(disconnect);
  const select=element('select');select.setAttribute('aria-label','Agenda Google a utilizar');select.hidden=true;body.append(select);
  const description=element('p','help','O resumo usa a agenda selecionada. Os eventos novos são criados nessa mesma agenda.');body.append(description);
  const title=element('input');title.type='text';title.placeholder='Título do compromisso';title.maxLength=500;title.setAttribute('aria-label','Título do evento Google');
  const start=element('input');start.type='datetime-local';start.setAttribute('aria-label','Início do evento em Lisboa');
  const end=element('input');end.type='datetime-local';end.setAttribute('aria-label','Fim do evento em Lisboa');
  const create=element('button','gold-button','Criar evento na agenda');create.type='button';create.disabled=true;
  body.append(element('h3','drawer-section-title','NOVO COMPROMISSO'),title,element('label','','Início · hora de Lisboa'),start,element('label','','Fim · hora de Lisboa'),end,create);
  body.append(element('p','help','Este formulário cria um evento na agenda selecionada, sem convidados. Repetir o mesmo título e horário reutiliza o evento. Também podes escrever: Cria um evento para amanhã das 09:00 às 10:00: telefonar ao fornecedor.'));
  let calendars=[],waiting=false,configured=false;
  function show(data){
    configured=data.configured;
    status.textContent=data.error|| (data.pending?'Autorização preparada. Abre a ligação abaixo e termina no Google.':data.verified?'Ligação testada: acesso à agenda «'+data.calendar_name+'» confirmado.':data.configured?'Autorização Google guardada. Carrega em Testar e carregar agendas.':'A Google Agenda ainda não está ligada. Escolhe o ficheiro JSON para começar.');
    test.disabled=!data.configured;disconnect.hidden=!data.configured&&!data.pending;connect.disabled=data.pending&&!authorize.hidden;select.hidden=!data.configured;
    if(!data.configured){create.disabled=true;select.replaceChildren();calendars=[];}
    if(data.calendars){
      calendars=data.calendars;select.replaceChildren();
      calendars.forEach(c=>{const option=element('option','',c.name+(c.primary?' · principal':'')+(!['owner','writer'].includes(c.role)?' · só leitura':''));option.value=c.id;select.append(option);});
    }
    if(data.configured){select.value=data.calendar_id;const chosen=calendars.find(c=>c.id===data.calendar_id);create.disabled=!chosen||!['owner','writer'].includes(chosen.role);}
  }
  async function refreshConnection(){show(await api('/connections/google',{action:'test'}));}
  async function poll(){
    if(!$('drawer').open||$('drawer-title').textContent!=='Ligar Google Agenda'){waiting=false;return;}
    try{
      const data=await api('/connections/google');show(data);
      if(data.pending){setTimeout(poll,2000);return;}
      waiting=false;authorize.hidden=true;
      if(data.configured&&!data.error){await refreshConnection();notify('Google Agenda ligada. Já podes consultar os compromissos no resumo do dia.');}
    }catch(e){waiting=false;connect.disabled=false;status.textContent=e.message;}
  }
  show(await api('/connections/google'));
  connect.addEventListener('click',()=>safe(async()=>{
    connect.disabled=true;
    try{
      let client_json;const selected=file.files?.[0];
      if(!selected&&!configured)throw Error('Escolhe primeiro o ficheiro JSON que descarregaste do Google.');
      if(selected){if(selected.size>20000)throw Error('Escolhe o pequeno ficheiro JSON do cliente Google.');client_json=await selected.text();}
      const result=await api('/connections/google',{action:'start',...(client_json===undefined?{}:{client_json})});
      file.value='';authorize.href=result.url;authorize.hidden=false;status.textContent='Agora carrega em Autorizar no Google, escolhe a conta e aceita as permissões de agenda.';
      if(!waiting){waiting=true;setTimeout(poll,2000);}
    }catch(e){connect.disabled=false;throw e;}
  }));
  test.addEventListener('click',()=>safe(async()=>{test.disabled=true;try{await refreshConnection();}finally{test.disabled=false;}}));
  disconnect.addEventListener('click',()=>safe(async()=>{show(await api('/connections/google',{action:'disconnect'}));authorize.hidden=true;notify('Credencial Google removida deste computador. Os eventos existentes foram mantidos.');}));
  select.addEventListener('change',()=>safe(async()=>{await api('/connections/google',{action:'select',calendar_id:select.value});await refreshConnection();}));
  create.addEventListener('click',()=>safe(async()=>{
    if(!title.value.trim()||!start.value||!end.value)throw Error('Preenche o título, o início e o fim.');
    create.disabled=true;
    try{const result=await api('/google/events',{title:title.value,start:start.value,end:end.value});title.value='';notify(result.created?'Evento criado na agenda «'+result.calendar_name+'».':'Este evento já estava na agenda; foi reutilizado.');}
    finally{const c=calendars.find(c=>c.id===select.value);create.disabled=!c||!['owner','writer'].includes(c.role);}
  }));
  const daily=element('button','subtle-button','Ver resumo do dia');daily.type='button';daily.addEventListener('click',()=>safe(openDaily));body.append(daily);
}
async function openDaily(startup=false){
  const data=await api('/daily');
  const body=setDrawer('O teu resumo · '+data.date);
  body.append(element('h3','drawer-section-title','PENDENTES LOCAIS'));
  if(!data.local.length)body.append(element('p','help','Sem tarefas locais pendentes.'));
  data.local.forEach(t=>body.append(element('p','', '◦ '+t.title)));
  body.append(element('h3','drawer-section-title','NOTION · DIÁRIO'));
  if(data.notion){
    body.append(element('p','help',data.notion.scope));
    if(!data.notion.tasks.length)body.append(element('p','help','Sem caixas pendentes nos registos consultados.'));
    data.notion.tasks.forEach(t=>{const row=element('p');const link=element('a','external-link',t.date+' · '+t.title);link.href=t.url;link.target='_blank';link.rel='noopener';row.append(link);body.append(row);});
    if(data.notion.partial)body.append(element('p','help','Consulta parcial: há registos ou blocos adicionais por consultar.'));
  }else if(!data.errors.length)body.append(element('p','help','Liga o Notion nas Definições para incluir o Diário.'));
  data.errors.forEach(error=>body.append(element('p','help',error)));
  body.append(element('h3','drawer-section-title','COMPROMISSOS'));
  if(data.calendar)appendGoogleEvents(body,data.calendar);
  else body.append(element('p','help',data.calendar_connected?'Não consegui consultar os compromissos; vê o erro acima.':'Google Agenda ainda por ligar. Os compromissos não foram consultados.'));
  if(startup&&!data.errors.length){prefs.dailySeen=data.date;savePrefs();}
}
async function startupDaily(){
  if(prefs.dailyAuto===false)return;
  const now=lisbonParts(),day=now.year+'-'+String(now.month).padStart(2,'0')+'-'+String(now.day).padStart(2,'0');
  if(prefs.dailySeen===day)return;
  const [notion,google]=await Promise.all([api('/connections/notion'),api('/connections/google')]);
  if(notion.configured||google.configured)await openDaily(true);
}
async function openHistory(){
  const body=setDrawer('As nossas conversas');body.append(element('p','help','Retoma uma conversa guardada neste painel. As novas mensagens são guardadas no teu computador.'));
  const data=await api('/chats');
  if(!data.chats.length)body.append(element('p','help','A primeira conversa começa com a tua próxima mensagem.'));
  data.chats.forEach(chat=>{const b=element('button','history-card');b.type='button';b.append(element('strong','',chat.title),element('small','',dateText(chat.updated_at)));b.addEventListener('click',()=>safe(async()=>{if(state.busy)return;stopSpeech();const result=await api('/chats/'+chat.id);state.chat=result.chat;state.messages=result.messages;prefs.chat=chat.id;savePrefs();renderMessages();$('drawer').close();}));body.append(b);});
}
function openPanel(which){if(which==='memory')openMemory();if(which==='tasks')openTasks();if(which==='documents')openDocuments();if(which==='settings')openSettings();}

function formattedText(container,text){
  // Only a small text formatter. User/model content is never interpreted as HTML.
  // Lists generated by the Jarvis (/relatorios/…pdf|xlsx) become buttons to open them.
  const pattern=/(\*\*[^*]+\*\*|`[^`\n]+`|\/relatorios\/[\w-]+\.(?:pdf|xlsx))/g;let start=0;
  for(const match of text.matchAll(pattern)){container.append(document.createTextNode(text.slice(start,match.index)));start=match.index+match[0].length;
    if(match[0].startsWith('/relatorios/')){const pdf=match[0].endsWith('.pdf');const link=element('a','external-link',pdf?'Abrir lista em PDF ↗':'Descarregar em Excel ↓');link.href=match[0];if(pdf){link.target='_blank';link.rel='noopener';}else link.download='';container.append(link);continue;}
    const strong=match[0].startsWith('**');container.append(element(strong?'strong':'code','',match[0].slice(strong?2:1,strong?-2:-1)));}
  container.append(document.createTextNode(text.slice(start)));
}
function renderMessages(){
  const list=$('messages');list.replaceChildren();
  if(!state.messages.length){
    const welcome=element('div','welcome');welcome.append(element('span','mini-core'),element('span','eyebrow','ESTOU AQUI, MEU REI'),element('h3','','O que vamos\nresolver hoje?'),element('p','','As tuas ideias, os teus assuntos e o próximo passo. Vamos pôr tudo em ordem.'));
    [['O que tenho pendente?','Que tarefas tenho pendentes?'],['O que sabes sobre mim?','Que memórias tens guardadas sobre mim?'],['Vamos organizar o dia','Ajuda-me a organizar o dia com as tarefas que tenho pendentes.']].forEach(([label,prompt])=>{const b=element('button','suggestion',label);b.type='button';b.append(icon('arrow'));b.addEventListener('click',()=>{if(state.busy)return;$('message').value=prompt;$('composer').requestSubmit();});welcome.append(b);});list.append(welcome);
  }
  state.messages.forEach(message=>{const box=element('article','chat-message '+message.role);const label=element('div','message-label',message.role==='user'?'Tu':'✦ Jarvis');if(message.created_at)label.append(element('time','',dateText(message.created_at,{hour:'2-digit',minute:'2-digit'})));const content=element('div','message-content');formattedText(content,message.content);box.append(label,content);if(message.role==='assistant'){const actions=element('div','message-actions');actions.append(actionButton('Ouvir esta resposta',()=>speak(message.content),'sound'));box.append(actions);}list.append(box);});
  list.scrollTop=list.scrollHeight;
}
async function sendMessage(){
  const text=$('message').value.trim();if(!text||state.busy)return;
  if(!state.connected)throw Error('A Central ainda não está ligada. Carrega em Atualizar dados.');
  prepareAudio();stopSpeech();const previous=state.messages.slice();
  state.messages.push({role:'user',content:text,created_at:new Date().toISOString()});$('message').value='';$('message').style.height='';setBusy(true);renderMessages();
  try{
    if(!state.chat){const created=await api('/chats',{});state.chat=created.chat;}
    const result=await api('/panel/chat',{chat_id:state.chat.id,text});
    state.chat=result.chat;state.messages=result.messages;prefs.chat=result.chat.id;savePrefs();renderMessages();setBusy(false);
    await refresh(true);
    if(prefs.voiceAuto)safe(()=>speak(result.answer));
  }catch(e){state.messages=previous;renderMessages();if(!$('message').value)$('message').value=text;throw e;}
  finally{setBusy(false);}
}
async function loadChat(){
  const data=await api('/chats');let chosen=data.chats.find(c=>c.id===prefs.chat)||data.chats[0];
  if(chosen){const result=await api('/chats/'+chosen.id);state.chat=result.chat;state.messages=result.messages;prefs.chat=chosen.id;savePrefs();}renderMessages();
}
let audioContext=null,audioSource=null,speechController=null,speechSequence=0,envelope=null,avatar=null;
function prepareAudio(){
  try{if(!audioContext){const Type=window.AudioContext||window.webkitAudioContext;if(Type)audioContext=new Type();}if(audioContext?.state==='suspended')audioContext.resume().catch(()=>{});}catch{/* Report a clear error when speech is requested. */}
}
function stopSpeech(){speechSequence++;speechController?.abort();speechController=null;if(audioSource){try{audioSource.stop();}catch{}audioSource=null;}envelope=null;avatar?.stopSpeech();state.speaking=false;state.audioLoading=false;updateActivity();}
function speechChunks(text){
  // Short first chunk (first sentence) so the voice starts quickly; then groups of sentences.
  // Splits only after . ! ? … followed by a space, so 12.50 or 9.30 are never cut.
  const plain=text.replace(/https?:\/\/\S+|\/relatorios\/\S+/g,'').replace(/\*\*|#{1,6}\s|`/g,'').replace(/^\s*[-*•]\s+/gm,'').trim();if(!plain)return [];
  const sentences=plain.split(/(?<=[.!?…])\s+|\n+/).map(x=>x.trim()).filter(Boolean);const chunks=[];let current='';
  for(const sentence of sentences){
    const limit=chunks.length?420:160;
    if(current&&(current.length+sentence.length+1>limit||(!chunks.length&&current.length>=25))){chunks.push(current);current='';}
    current=current?current+' '+sentence:sentence;
    while(current.length>3400){let cut=current.lastIndexOf(' ',3400);if(cut<1)cut=3400;chunks.push(current.slice(0,cut));current=current.slice(cut).trim();}
  }
  if(current)chunks.push(current);return chunks;
}
function audioEnvelope(buffer){const data=buffer.getChannelData(0),sliceLength=40,step=Math.max(1,Math.floor(buffer.sampleRate*sliceLength/1000)),values=[];for(let start=0;start<data.length;start+=step){let sum=0,count=0;for(let i=start;i<Math.min(start+step,data.length);i+=4){sum+=data[i]*data[i];count++;}values.push(Math.min(1,Math.sqrt(sum/Math.max(1,count))*8));}return {values,sliceLength};}
async function speak(text){
  prepareAudio();if(!audioContext)throw Error('Este navegador não permite reproduzir áudio.');
  stopSpeech();const sequence=speechSequence;
  try{
    await audioContext.resume();
    const chunks=speechChunks(text);speechController=new AbortController();const signal=speechController.signal;
    // Each sentence group is synthesised while the previous one is playing.
    const synth=chunk=>fetch('/v1/audio/speech',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',signal,body:JSON.stringify({input:chunk,voice:state.status?.voice})})
      .then(async response=>{if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error?.message||'A voz não ficou disponível.');}return audioContext.decodeAudioData(await response.arrayBuffer());});
    let next=chunks.length?synth(chunks[0]):null;next?.catch(()=>{});
    for(let index=0;index<chunks.length;index++){
      if(sequence!==speechSequence)return;if(!state.speaking){state.audioLoading=true;updateActivity();}
      const buffer=await next;
      next=index+1<chunks.length?synth(chunks[index+1]):null;next?.catch(()=>{});
      if(sequence!==speechSequence)return;
      const source=audioContext.createBufferSource();source.buffer=buffer;source.connect(audioContext.destination);audioSource=source;
      const shape=audioEnvelope(buffer);const startTime=audioContext.currentTime;
      envelope={...shape,startTime,duration:buffer.duration};state.audioLoading=false;state.speaking=true;updateActivity();
      avatar?.setSpeech(shape.values,shape.sliceLength,audioContext,startTime,buffer.duration);
      const ended=new Promise(resolve=>source.onended=resolve);source.start();await ended;
    }
  }catch(e){if(sequence===speechSequence&&e.name!=='AbortError')throw Error(e.message+' Podes continuar a conversar por texto.');}
  finally{if(sequence===speechSequence){audioSource=null;envelope=null;avatar?.stopSpeech();state.speaking=false;state.audioLoading=false;updateActivity();}}
}
function currentVolume(){if(!envelope||!audioContext)return 0;const elapsed=audioContext.currentTime-envelope.startTime;return envelope.values[Math.floor(elapsed*1000/envelope.sliceLength)]||0;}
async function changeView(mode){
  state.mode=mode;prefs.view=mode;savePrefs();$('mode-core').classList.toggle('selected',mode==='core');$('mode-avatar').classList.toggle('selected',mode==='avatar');$('mode-core').setAttribute('aria-pressed',String(mode==='core'));$('mode-avatar').setAttribute('aria-pressed',String(mode==='avatar'));$('avatar').hidden=mode!=='avatar';$('orbit-nodes').hidden=mode==='avatar';$('cosmos').hidden=mode==='avatar';$('stage').classList.toggle('avatar-view',mode==='avatar');
  // «Personagem» is now the Jarvis portrait (image), animated with the voice and state. The 3D model is no longer loaded.
  $('avatar').hidden=true;$('persona').hidden=mode!=='avatar';$('avatar-loading').hidden=true;return;
  $('avatar-loading').hidden=false;
  try{
    const {JarvisAvatar}=await import('/avatar.js?v=5');
    await new Promise((resolve,reject)=>{avatar=new JarvisAvatar($('avatar'),resolve,reject);});
    $('avatar-loading').hidden=true;
    if(envelope)avatar.setSpeech(envelope.values,envelope.sliceLength,audioContext,envelope.startTime,envelope.duration);
    if(state.mode!=='avatar')avatar.setActive(false);
  }catch(e){avatar?.dispose();avatar=null;$('avatar').replaceChildren();$('avatar-loading').hidden=true;await changeView('core');notify('A personagem 3D não carregou neste navegador. O núcleo e a conversa continuam disponíveis.',true);}
}

class Cosmos{
  constructor(canvas){this.canvas=canvas;this.ctx=canvas.getContext('2d');let seed=471931;const random=()=>{seed=(seed*16807)%2147483647;return(seed-1)/2147483646;};this.particles=Array.from({length:820},()=>({angle:random()*Math.PI*2,r:.26+random()*.74,size:.35+random()*1.25,speed:.4+random()*.6,tone:random()}));this.stars=Array.from({length:100},()=>({x:random(),y:random(),size:.3+random()*.6,alpha:.08+random()*.2}));this.last=0;this.start=performance.now();this.observer=new ResizeObserver(()=>this.resize());this.observer.observe($('stage'));this.resize();requestAnimationFrame(t=>this.frame(t));}
  resize(){const rect=$('stage').getBoundingClientRect();this.width=rect.width;this.height=rect.height;const dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.round(rect.width*dpr);this.canvas.height=Math.round(rect.height*dpr);this.ctx.setTransform(dpr,0,0,dpr,0,0);}
  frame(time){requestAnimationFrame(t=>this.frame(t));if(document.hidden||time-this.last<33||!this.canvas.offsetParent)return;this.last=time;const reduced=prefs.reduced||matchMedia('(prefers-reduced-motion: reduce)').matches;const seconds=reduced?20:(time-this.start)/1000;const volume=currentVolume();const persona=$('persona');if(persona&&!persona.hidden){persona.style.setProperty('--voz',(state.speaking?volume:0).toFixed(3));persona.classList.toggle('busy',state.busy);persona.classList.toggle('speaking',state.speaking);persona.classList.toggle('listening',!!(handsFree&&handsFree.on));drawPersona(volume);}const bars=$('pulse').children;for(let i=0;i<bars.length;i++){const baseline=3+Math.sin(i*.8)*2;const movement=state.speaking?volume*(10+Math.sin(i*1.4+time*.008)*9):state.busy?5+Math.sin(time*.003+i*.6)*4:0;bars[i].style.height=Math.max(2,baseline+movement)+'px';}
    if(state.mode!=='core')return;this.draw(seconds,volume);
  }
  draw(t,volume){
    const {ctx:c,width:w,height:h}=this;if(!w||!h||!c)return;c.clearRect(0,0,w,h);
    const x=w*.49,y=h*.49,r=Math.min(w*.43,h*.48),core=r*.165;
    for(const s of this.stars){c.fillStyle=`rgba(214,207,181,${s.alpha})`;c.fillRect(s.x*w,s.y*h,s.size,s.size);}
    const haze=c.createRadialGradient(x,y,core,x,y,r*1.18);haze.addColorStop(0,'rgba(235,191,106,.11)');haze.addColorStop(.34,'rgba(190,150,76,.045)');haze.addColorStop(.72,'rgba(141,123,83,.018)');haze.addColorStop(1,'rgba(0,0,0,0)');c.fillStyle=haze;c.fillRect(0,0,w,h);
    state.groups.forEach((g,i)=>{const endX=coordinates[i][0]/100*w,endY=coordinates[i][1]/100*h;c.beginPath();c.moveTo(x+core*.9,y-core*.5);c.quadraticCurveTo(x+r*.82,y-r*.73,endX,endY);c.strokeStyle='rgba(220,190,127,.09)';c.lineWidth=.65;c.stroke();});
    c.save();c.translate(x,y);c.rotate(-.42);c.scale(1,.83);
    for(let i=0;i<55;i++){const radius=r*(.23+i*.0143);c.beginPath();c.ellipse(0,0,radius,radius*(.91+Math.sin(i*.7)*.025),.045*Math.sin(i),0,Math.PI*2);c.strokeStyle=`rgba(205,176,121,${.032+(i%7===0?.055:0)})`;c.lineWidth=i%7===0?.85:.5;c.stroke();}
    for(const p of this.particles){const angle=p.angle+t*.045*p.speed/(p.r+.24),radius=r*p.r;const px=Math.cos(angle)*radius,py=Math.sin(angle)*radius*(.91+Math.sin(p.angle*3)*.025);const alpha=(.16+Math.max(0,Math.cos(angle-.7))*.6)*(p.r>.95?.6:1);c.fillStyle=p.tone>.92?`rgba(249,241,213,${Math.min(1,alpha+.2)})`:`rgba(215,184,121,${alpha})`;c.beginPath();c.arc(px,py,p.size*(.8+volume*.3),0,Math.PI*2);c.fill();}
    c.save();c.globalCompositeOperation='screen';
    for(let i=0;i<20;i++){const radius=r*(.24+i*.025);c.beginPath();c.arc(0,0,radius,-.55-i*.014,1.55+i*.019);c.strokeStyle=`rgba(230,193,125,${.08+(20-i)*.003})`;c.lineWidth=.65;c.stroke();}
    c.restore();c.restore();
    this.drawDigitalFace(c,x,y,core*2.15,t,volume);
    c.beginPath();c.ellipse(x,y,r*1.075,r*.96,-.42,-.15,Math.PI*1.1);c.strokeStyle='rgba(213,185,128,.15)';c.lineWidth=.65;c.stroke();
    const orbit=t*.04-1.3,ox=x+Math.cos(orbit)*r*1.04,oy=y+Math.sin(orbit)*r*.9;c.beginPath();c.arc(ox,oy,2,0,Math.PI*2);c.fillStyle='#dbbb7c';c.shadowColor='#dfbc78';c.shadowBlur=10;c.fill();c.shadowBlur=0;
  }
  buildFace(){
    const rows=36,columns=40,points=[],edges=[],facets=Array.from({length:12},()=>[]);
    const bump=(x,y,cx,cy,sx,sy)=>Math.exp(-(((x-cx)/sx)**2+((y-cy)/sy)**2));
    for(let row=0;row<=rows;row++){
      const latitude=Math.PI*(.035+.93*row/rows),y=-1.18*Math.cos(latitude);
      const jaw=y>.38?1-.28*(y-.38)/.8:1;
      for(let col=0;col<=columns;col++){
        const angle=(col/columns-.5)*Math.PI*.94;
        const x=Math.sin(latitude)*Math.sin(angle)*.83*jaw;
        let z=Math.sin(latitude)*Math.cos(angle)*.52;
        z+=.31*bump(x,y,0,.08,.11,.20)+.14*bump(x,y,0,-.22,.10,.35);
        z+=.10*bump(x,y,-.42,.12,.20,.25)+.10*bump(x,y,.42,.12,.20,.25);
        z-=.14*bump(x,y,-.31,-.28,.19,.13)+.14*bump(x,y,.31,-.28,.19,.13);
        z+=.065*bump(x,y,0,.48,.30,.09)+.07*bump(x,y,0,.88,.22,.19);
        points.push({x,y,z});
        const n=row*(columns+1)+col;
        if(col)edges.push([n-1,n]);
        if(row)edges.push([n-columns-1,n]);
        if(row&&col&&(row+col)%2===0)edges.push([n-columns-2,n]);
      }
    }
    const facet=(a,b,d)=>{
      const A=points[a],B=points[b],D=points[d],u=[B.x-A.x,B.y-A.y,B.z-A.z],v=[D.x-A.x,D.y-A.y,D.z-A.z];
      const normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...normal)||1;
      const light=Math.max(0,Math.min(1,(-normal[0]*.35-normal[1]*.45+normal[2]*.82)/length));
      facets[Math.min(11,Math.floor(light*12))].push([a,b,d]);
    };
    for(let row=1;row<=rows;row++)for(let col=1;col<=columns;col++){
      const n=row*(columns+1)+col;facet(n-columns-2,n-columns-1,n);facet(n-columns-2,n,n-1);
    }
    return {points,edges,facets};
  }
  drawRosto(c,x,y,size,t,volume){
    // The Jarvis portrait in the core: breathes, glows with the voice and pulses while thinking.
    const image=this.portrait,iw=image.naturalWidth||image.width,ih=image.naturalHeight||image.height;
    const h=size*3.0,w=h*iw/ih,think=state.busy?(.5+Math.sin(t*3.6)*.5):0;
    c.save();c.translate(x,y-h*.1+Math.sin(t*.55)*size*.012);
    const glow=c.createRadialGradient(0,-h*.08,h*.05,0,0,h*.62);
    glow.addColorStop(0,`rgba(63,198,255,${.10+volume*.35+think*.12})`);glow.addColorStop(1,'rgba(0,0,0,0)');
    c.fillStyle=glow;c.fillRect(-h,-h,h*2,h*2);
    const extra=Math.min(.45,volume*.9+think*.18),open=mouthOpening(volume,h);
    rostoImage=image;drawRostoAt(c,-w/2,-h/2,w,h,open);
    if(extra>.01){c.globalCompositeOperation='lighter';c.globalAlpha=extra*.6;drawRostoAt(c,-w/2,-h/2,w,h,open);c.globalAlpha=1;c.globalCompositeOperation='source-over';}
    c.restore();
  }
  drawPortrait(c,x,y,size,t,volume){
    const image=this.portrait,d=size*3.25,w=image.naturalWidth||image.width,h=image.naturalHeight||image.height;
    c.save();c.translate(x,y+Math.sin(t*.55)*size*.012);c.rotate(Math.sin(t*.26)*.006);
    c.translate(-d/2,-d/2);
    const glow=c.createRadialGradient(d*.5,d*.5,d*.12,d*.5,d*.5,d*.58);
    glow.addColorStop(0,`rgba(73,210,210,${.035+volume*.08})`);glow.addColorStop(1,'rgba(0,0,0,0)');
    c.fillStyle=glow;c.fillRect(0,0,d,d);c.drawImage(image,0,0,d,d);
    // This is an animated image: local patches move with the real audio level.
    // The source face and its circuit details are preserved when at rest.
    const phase=t%5.7,lid=phase<.18?Math.max(.08,Math.abs(phase-.09)/.09):1;
    if(lid<.98)for(const center of [.389,.611]){
      c.save();c.beginPath();c.ellipse(center*d,.435*d,.064*d,.028*d,0,0,Math.PI*2);c.clip();
      c.fillStyle='#09191d';c.fillRect((center-.066)*d,.402*d,.132*d,.066*d);
      c.drawImage(image,(center-.066)*w,.402*h,.132*w,.066*h,(center-.066)*d,(.435-.033*lid)*d,.132*d,.066*d*lid);
      c.strokeStyle='rgba(133,225,218,.7)';c.lineWidth=d*.0015;c.beginPath();c.moveTo((center-.052)*d,.435*d);c.quadraticCurveTo(center*d,(.435-.012*lid)*d,(center+.052)*d,.435*d);c.stroke();c.restore();
    }
    if(volume>.025){
      const opening=Math.min(.024,volume*.028)*d,split=.673;
      c.save();c.beginPath();c.ellipse(d*.5,d*.675,d*.089,d*.016+opening*.8,0,0,Math.PI*2);c.clip();
      c.fillStyle='#041014';c.fillRect(d*.38,d*.60,d*.24,d*.16);
      c.drawImage(image,w*.38,h*.60,w*.24,h*(split-.60),d*.38,d*.60-opening/2,d*.24,d*(split-.60));
      c.drawImage(image,w*.38,h*split,w*.24,h*(.76-split),d*.38,d*split+opening/2,d*.24,d*(.76-split));
      c.restore();
    }
    c.restore();
  }
  drawDigitalFace(c,x,y,size,t,volume){
    if(!this.portraitRequested&&typeof Image!=='undefined'){
      this.portraitRequested=true;this.portrait=new Image();this.portrait.src='/assets/jarvis-rosto.png?v=1';
    }
    if(this.portrait?.complete&&(this.portrait.naturalWidth||this.portrait.width)>0){this.drawRosto(c,x,y,size,t,volume);return;}
    this.faceMesh??=this.buildFace();
    c.save();c.translate(x,y+Math.sin(t*.55)*size*.012);c.scale(size,size);
    const glow=c.createRadialGradient(0,-.08,.12,0,0,1.8);
    glow.addColorStop(0,'rgba(86,211,213,.17)');glow.addColorStop(.60,'rgba(37,128,139,.04)');glow.addColorStop(1,'rgba(0,0,0,0)');
    c.fillStyle=glow;c.fillRect(-2,-2,4,4);
    // Fine circuit traces surround an anatomical mesh, inspired by the reference.
    for(const side of [-1,1])for(let i=0;i<11;i++){
      const yy=-1.22+i*.236,xx=side*(.78+(i%3)*.12),out=side*(1.35+(i%4)*.12);
      c.beginPath();c.moveTo(side*.65,yy*.72);c.lineTo(xx,yy*.72);c.lineTo(xx,yy);c.lineTo(out,yy);
      c.strokeStyle=`rgba(119,198,198,${.10+(i%3)*.04})`;c.lineWidth=.005;c.stroke();
      c.beginPath();c.arc(out,yy,.022+(i%2)*.012,0,Math.PI*2);c.strokeStyle='rgba(159,224,222,.48)';c.lineWidth=.007;c.stroke();
      c.beginPath();c.arc(xx,yy*.72,.011,0,Math.PI*2);c.fillStyle='rgba(183,248,241,.7)';c.fill();
      if(!prefs.reduced){const pos=(t*.10+i*.139)%1;c.beginPath();c.arc(xx+(out-xx)*pos,yy,.012,0,Math.PI*2);c.fillStyle='rgba(157,243,237,.65)';c.fill();}
    }
    const rotation=Math.sin(t*.26)*.045,cos=Math.cos(rotation),sin=Math.sin(rotation);
    const project=(px,py,pz)=>({x:(px*cos+pz*sin)*(1+pz*.16),y:py*(1+pz*.08)+(py>.46?(py-.46)*volume*.13:0),z:pz*cos-px*sin});
    const vertices=this.faceMesh.points.map(p=>project(p.x,p.y,p.z));
    // A dark silhouette keeps the facial geometry legible over the orbit lines.
    c.beginPath();c.ellipse(0,0,.82,1.18,0,0,Math.PI*2);c.fillStyle='rgba(5,15,20,.93)';c.fill();
    this.faceMesh.facets.forEach((facets,light)=>{
      c.beginPath();for(const [a,b,d] of facets){c.moveTo(vertices[a].x,vertices[a].y);c.lineTo(vertices[b].x,vertices[b].y);c.lineTo(vertices[d].x,vertices[d].y);c.closePath();}
      c.fillStyle=`rgba(123,224,214,${.015+Math.pow(light/11,3)*.24})`;c.fill();
    });
    c.beginPath();for(const [a,b] of this.faceMesh.edges){c.moveTo(vertices[a].x,vertices[a].y);c.lineTo(vertices[b].x,vertices[b].y);}
    c.strokeStyle='rgba(116,223,218,.20)';c.lineWidth=.004;c.stroke();
    for(let group=0;group<3;group++){
      c.beginPath();vertices.forEach((p,i)=>{if(i%3!==group)return;const r=.006+(p.z>.5?.002:0);c.moveTo(p.x+r,p.y);c.arc(p.x,p.y,r,0,Math.PI*2);});
      c.fillStyle=['rgba(180,248,237,.70)','rgba(91,198,197,.37)','rgba(136,222,213,.49)'][group];c.fill();
    }
    // Soft modelling of the nose bridge, cheek planes and brow.
    c.lineWidth=.009;c.strokeStyle='rgba(180,242,229,.6)';
    const shift=.55*sin;c.beginPath();c.moveTo(shift,-.40);c.bezierCurveTo(shift-.025,-.12,shift-.07,.07,shift-.11,.16);c.quadraticCurveTo(shift,.23,shift+.12,.16);c.stroke();
    const phase=t%5.7,lid=phase<.18?Math.max(.08,Math.abs(phase-.09)/.09):1;
    for(const side of [-1,1]){
      const eye=project(side*.31,-.28,.46);c.save();c.translate(eye.x,eye.y);
      c.fillStyle='#071417';c.beginPath();c.ellipse(0,0,.205,.102,side*.08,0,Math.PI*2);c.fill();
      c.beginPath();c.moveTo(-.18,0);c.quadraticCurveTo(0,-.105*lid,.18,0);c.quadraticCurveTo(0,.066*lid,-.18,0);
      c.strokeStyle='rgba(169,249,237,.93)';c.lineWidth=.013;c.shadowColor='#8de8e2';c.shadowBlur=5;c.stroke();
      if(lid>.3){c.beginPath();c.ellipse(0,-.005,.038,.041*lid,0,0,Math.PI*2);c.fillStyle='#b5f6e8';c.fill();}
      c.shadowBlur=0;c.restore();
    }
    const opening=.008+volume*.10,mouth=project(0,.49,.59);
    c.beginPath();c.ellipse(mouth.x,mouth.y,.235,opening+.018,0,0,Math.PI*2);c.fillStyle='#061014';c.fill();
    c.beginPath();c.moveTo(mouth.x-.235,mouth.y);c.bezierCurveTo(mouth.x-.10,mouth.y-.025-opening,mouth.x-.06,mouth.y-.04-opening,mouth.x,mouth.y-.018-opening);c.bezierCurveTo(mouth.x+.06,mouth.y-.04-opening,mouth.x+.11,mouth.y-.025-opening,mouth.x+.235,mouth.y);c.quadraticCurveTo(mouth.x,mouth.y+.035+opening,mouth.x-.235,mouth.y);
    c.lineWidth=.009;c.strokeStyle='rgba(161,235,223,.78)';c.stroke();
    c.restore();
  }
}

const lisbonParts=()=>{const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Lisbon',year:'numeric',month:'numeric',day:'numeric',hour:'numeric',hour12:false}).formatToParts(new Date());return Object.fromEntries(parts.filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));};
let calendarDate;
// Calendário em faixa horizontal (por baixo da barra de cima): o dia escolhido fica sempre ao centro,
// com alguns dias para trás e para a frente; o mês aparece em cima e muda-se com as setas.
function renderCalendar(){
  const t=lisbonParts(),today=new Date(t.year,t.month-1,t.day);if(!calendarDate)calendarDate=new Date(today);
  const sel=new Date(calendarDate.getFullYear(),calendarDate.getMonth(),calendarDate.getDate());
  $('calendar-title').textContent=new Intl.DateTimeFormat('pt-PT',{month:'long',year:'numeric'}).format(sel).replace(' de ',' ');
  const letters=['D','S','T','Q','Q','S','S'],months=new Intl.DateTimeFormat('pt-PT',{month:'short'});
  const strip=$('calendar');strip.replaceChildren();
  for(let i=-24;i<=24;i++){
    const d=new Date(sel.getFullYear(),sel.getMonth(),sel.getDate()+i);
    const cell=element('button','ds-day');cell.type='button';
    if(d.getDay()===0||d.getDay()===6)cell.classList.add('weekend');
    if(d.getMonth()!==sel.getMonth())cell.classList.add('other');
    if(+d===+today){cell.classList.add('today');cell.setAttribute('aria-current','date');}
    if(i===0){cell.classList.add('selected');cell.setAttribute('aria-pressed','true');}
    if(d.getDate()===1)cell.classList.add('first');
    cell.append(element('small','',d.getDate()===1?months.format(d).replace('.',''):letters[d.getDay()]),element('b','',String(d.getDate())));
    cell.setAttribute('aria-label',new Intl.DateTimeFormat('pt-PT',{weekday:'long',day:'numeric',month:'long'}).format(d)+(+d===+today?' (hoje)':''));
    cell.addEventListener('click',()=>{calendarDate=d;renderCalendar();});
    strip.append(cell);
  }
}
function shiftCalendar(months){const d=calendarDate,day=d.getDate(),n=new Date(d.getFullYear(),d.getMonth()+months,1);n.setDate(Math.min(day,new Date(n.getFullYear(),n.getMonth()+1,0).getDate()));calendarDate=n;renderCalendar();}
function updateDate(){const today=lisbonParts();$('greeting').replaceChildren(document.createTextNode((today.hour<12?'Bom dia':today.hour<20?'Boa tarde':'Boa noite')+', Simão'),element('span','','.'));$('today-label').textContent=new Intl.DateTimeFormat('pt-PT',{timeZone:'Europe/Lisbon',weekday:'long',day:'numeric',month:'long'}).format(new Date());$('clock').textContent=new Intl.DateTimeFormat('pt-PT',{timeZone:'Europe/Lisbon',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date());}
document.querySelectorAll('[data-panel]').forEach(b=>b.addEventListener('click',()=>openPanel(b.dataset.panel)));
$('drawer-close').addEventListener('click',()=>$('drawer').close());
$('drawer').addEventListener('click',e=>{if(e.target===$('drawer')){const r=$('drawer').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('drawer').close();}});
$('nav-home').addEventListener('click',()=>{$('drawer').close();$('stage').scrollIntoView({behavior:prefs.reduced?'instant':'smooth',block:'center'});});
$('refresh').addEventListener('click',()=>safe(()=>refresh()));
$('composer').addEventListener('submit',e=>{e.preventDefault();safe(sendMessage);});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('composer').requestSubmit();}});
$('message').addEventListener('input',()=>{$('message').style.height='auto';$('message').style.height=Math.min(120,$('message').scrollHeight)+'px';});
$('production-refresh').addEventListener('click',()=>refreshProduction());$('notes-alert-ok').addEventListener('click',()=>$('notes-alert').close());loadNotes().then(()=>remindNotes());setInterval(()=>{loadNotes().then(()=>remindNotes());},5*60*1000);loadAcoes();setInterval(()=>{if(!document.hidden)loadAcoes();},60*1000);loadSeguranca();setInterval(()=>{if(!document.hidden)loadSeguranca();},5*60*1000);loadAlerts();setInterval(()=>{if(!document.hidden)loadAlerts();},60*1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadAcoes();});loadProduction();setInterval(()=>{if(!document.hidden)loadProduction();},15*60*1000);
$('chat-close').addEventListener('click',closeChat);
$('message').addEventListener('focus',()=>{if(state.messages.length)openChat();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('chat-pop').hidden&&!$('drawer').open)closeChat();});
document.addEventListener('pointerdown',e=>{if(!$('chat-pop').hidden&&!$('chat-panel').contains(e.target)&&!e.target.closest('dialog'))armChatClose();},true);
setInterval(()=>document.body.classList.toggle('jarvis-speaking',!!state.speaking),250);
$('new-chat').addEventListener('click',()=>{if(state.busy)return;stopSpeech();state.chat=null;state.messages=[];prefs.chat=null;savePrefs();renderMessages();$('message').focus();});
$('history-button').addEventListener('click',()=>safe(openHistory));
$('sound').addEventListener('click',()=>{prepareAudio();prefs.voiceAuto=!prefs.voiceAuto;savePrefs();if(!prefs.voiceAuto)stopSpeech();updateSoundUI();notify(prefs.voiceAuto?'Voz automática ligada.':'Voz automática desligada.');});
$('stop-voice').addEventListener('click',stopSpeech);
$('mode-core').addEventListener('click',()=>safe(()=>changeView('core')));
$('mode-avatar').addEventListener('click',()=>safe(()=>changeView('avatar')));
$('fullscreen').addEventListener('click',()=>safe(async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}));
$('previous-month').addEventListener('click',()=>shiftCalendar(-1));$('next-month').addEventListener('click',()=>shiftCalendar(1));$('calendar-title').addEventListener('click',()=>{calendarDate=null;renderCalendar();});
$('calendar').addEventListener('wheel',e=>{const v=Math.abs(e.deltaY)>Math.abs(e.deltaX)?e.deltaY:e.deltaX;if(!v)return;e.preventDefault();calendarDate=new Date(calendarDate.getFullYear(),calendarDate.getMonth(),calendarDate.getDate()+(v>0?1:-1));renderCalendar();},{passive:false});
setInterval(()=>{const t=lisbonParts(),now=t.year*1e4+t.month*100+t.day;if(renderCalendar.day&&renderCalendar.day!==now)renderCalendar();renderCalendar.day=now;},60000);
let recognition=null,recording=false;
$('microphone').addEventListener('click',()=>safe(()=>{
  if(recording){recognition.stop();return;}
  const Type=window.SpeechRecognition||window.webkitSpeechRecognition;if(!Type)throw Error('O ditado não está disponível neste navegador. Podes continuar a escrever as mensagens.');
  recognition=new Type();recognition.lang='pt-PT';recognition.interimResults=true;recognition.continuous=false;const initial=$('message').value;
  recognition.onstart=()=>{recording=true;$('microphone').classList.add('recording');$('microphone').setAttribute('aria-label','Parar ditado');};
  recognition.onresult=e=>{$('message').value=initial+(initial?' ':'')+Array.from(e.results).map(r=>r[0].transcript).join(' ');};
  recognition.onend=()=>{recording=false;$('microphone').classList.remove('recording');$('microphone').setAttribute('aria-label','Ditar uma mensagem');$('message').focus();};
  recognition.onerror=e=>{if(e.error!=='no-speech'&&e.error!=='aborted')notify('O microfone não ficou disponível. Verifica a permissão do navegador ou escreve a mensagem.',true);};recognition.start();
}));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)safe(()=>refresh(true));});
document.body.classList.toggle('reduced-motion',prefs.reduced);new Cosmos($('cosmos'));updateSoundUI();updateDate();renderCalendar();renderMessages();
setInterval(updateDate,1000);setInterval(()=>{if(!document.hidden)safe(()=>refresh(true));},20000);
if(displayChannel)displayChannel.onmessage=e=>{if(e.data?.kind==='data'&&!document.hidden&&!state.busy)safe(()=>refresh(true));};
safe(async()=>{await refresh();if(!coreOnly){await loadChat();await startupDaily();}});

// ── Mãos-livres: «Jarvis, …». O navegador só corta excertos com voz; a transcrição é feita no PC (Whisper local).
// Enquanto o Jarvis pensa ou fala, a escuta fica em pausa para não se ouvir a si próprio.
var handsFree={on:false,stream:null,ctx:null,node:null,source:null,awakeUntil:0,frames:[],preroll:[],speaking:false,silence:0,voiced:0,spoken:0,noise:0.004,sending:false,wakeLock:null};
const HF_RATE=16000;
function hfDownsample(input,rate){const ratio=rate/HF_RATE,out=new Float32Array(Math.floor(input.length/ratio));for(let i=0;i<out.length;i++){const start=Math.floor(i*ratio),end=Math.min(input.length,Math.floor((i+1)*ratio));let sum=0;for(let j=start;j<end;j++)sum+=input[j];out[i]=sum/Math.max(1,end-start);}return out;}
function hfWav(chunks){let length=0;for(const c of chunks)length+=c.length;const buffer=new ArrayBuffer(44+length*2),view=new DataView(buffer),text=(o,s)=>{for(let i=0;i<s.length;i++)view.setUint8(o+i,s.charCodeAt(i));};text(0,'RIFF');view.setUint32(4,36+length*2,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,HF_RATE,true);view.setUint32(28,HF_RATE*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,length*2,true);let o=44;for(const c of chunks)for(let i=0;i<c.length;i++,o+=2){const v=Math.max(-1,Math.min(1,c[i]));view.setInt16(o,v<0?v*0x8000:v*0x7fff,true);}return new Blob([buffer],{type:'audio/wav'});}
function hfReset(){handsFree.frames=[];handsFree.speaking=false;handsFree.silence=0;handsFree.voiced=0;handsFree.spoken=0;}
function hfFrame(input,rate){
  if(!handsFree.on)return;
  const chunk=hfDownsample(input,rate),seconds=chunk.length/HF_RATE;let sum=0;for(let i=0;i<input.length;i++)sum+=input[i]*input[i];const rms=Math.sqrt(sum/input.length);
  if(state.busy||state.speaking||state.audioLoading||handsFree.sending){hfReset();handsFree.preroll=[];return;}
  const loud=rms>Math.max(0.012,handsFree.noise*3.5);
  if(!handsFree.speaking){
    handsFree.preroll.push(chunk);if(handsFree.preroll.length>8)handsFree.preroll.shift();
    if(loud){handsFree.voiced++;if(handsFree.voiced>=3){handsFree.speaking=true;handsFree.frames=handsFree.preroll.slice();handsFree.spoken=0;handsFree.silence=0;}}
    else{handsFree.voiced=0;handsFree.noise=handsFree.noise*0.95+rms*0.05;}
    return;
  }
  handsFree.frames.push(chunk);handsFree.spoken+=seconds;handsFree.silence=loud?0:handsFree.silence+seconds;
  if(handsFree.silence>=0.8||handsFree.spoken>=12){const frames=handsFree.frames,length=handsFree.spoken-handsFree.silence;hfReset();handsFree.preroll=[];if(length>=0.35)safe(()=>hfSend(frames));}
}
function hfBeep(){try{prepareAudio();if(!audioContext)return;const o=audioContext.createOscillator(),g=audioContext.createGain();o.frequency.value=880;g.gain.setValueAtTime(0.0001,audioContext.currentTime);g.gain.exponentialRampToValueAtTime(0.15,audioContext.currentTime+0.02);g.gain.exponentialRampToValueAtTime(0.0001,audioContext.currentTime+0.18);o.connect(g);g.connect(audioContext.destination);o.start();o.stop(audioContext.currentTime+0.2);}catch{}}
async function hfSend(frames){
  const mode=Date.now()<handsFree.awakeUntil?'comando':'wake';handsFree.sending=true;updateActivity();
  try{
    const response=await fetch('/voice/listen?modo='+mode,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'audio/wav'},body:hfWav(frames)});
    const data=await response.json();
    if(!response.ok){if(response.status>=500||response.status===401||response.status===403)hfStop();throw Error(data.error?.message||data.error||'O reconhecimento de voz falhou.');}
    if(!data.ativado)return;
    if(data.parar){handsFree.awakeUntil=0;stopSpeech();return;}
    if(data.comando){handsFree.awakeUntil=0;for(let i=0;state.busy&&i<240;i++)await new Promise(r=>setTimeout(r,250));if(state.busy||!handsFree.on)return;$('message').value=data.comando;safe(sendMessage);return;}
    handsFree.awakeUntil=Date.now()+8000;hfBeep();setTimeout(updateActivity,8100);
  }finally{handsFree.sending=false;updateActivity();}
}
async function hfWakeLock(){try{if(handsFree.on&&navigator.wakeLock&&!document.hidden)handsFree.wakeLock=await navigator.wakeLock.request('screen');}catch{/* the screen may still turn off */}}
function updateHandsFreeUI(){const b=$('handsfree');if(b){b.classList.toggle('recording',handsFree.on);b.setAttribute('aria-pressed',String(handsFree.on));b.title=handsFree.on?'Mãos-livres ligado: diz «Jarvis» e o teu pedido':'Mãos-livres: diz «Jarvis» e o teu pedido (reconhecido no teu PC)';}updateActivity();}
async function hfStart(){
  if(!navigator.mediaDevices?.getUserMedia)throw Error('Este navegador não permite usar o microfone aqui. Abre o Jarvis pelo endereço https.');
  const status=await api('/voice/status');if(!status.disponivel)throw Error(status.motivo||'O reconhecimento de voz local não está disponível no PC.');
  prepareAudio();
  handsFree.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
  const Type=window.AudioContext||window.webkitAudioContext;handsFree.ctx=new Type();await handsFree.ctx.resume();
  handsFree.source=handsFree.ctx.createMediaStreamSource(handsFree.stream);handsFree.node=handsFree.ctx.createScriptProcessor(2048,1,1);
  handsFree.node.onaudioprocess=e=>hfFrame(e.inputBuffer.getChannelData(0),handsFree.ctx.sampleRate);
  const mute=handsFree.ctx.createGain();mute.gain.value=0;handsFree.source.connect(handsFree.node);handsFree.node.connect(mute);mute.connect(handsFree.ctx.destination);
  handsFree.on=true;hfReset();handsFree.preroll=[];hfWakeLock();updateHandsFreeUI();notify('Mãos-livres ligado. Diz «Jarvis» e o teu pedido.');
}
function hfStop(){
  handsFree.on=false;try{handsFree.node?.disconnect();handsFree.source?.disconnect();}catch{}handsFree.stream?.getTracks().forEach(t=>t.stop());handsFree.ctx?.close().catch(()=>{});
  handsFree.wakeLock?.release?.().catch(()=>{});Object.assign(handsFree,{stream:null,ctx:null,node:null,source:null,awakeUntil:0,wakeLock:null,sending:false});hfReset();updateHandsFreeUI();
}
$('handsfree')?.addEventListener('click',()=>safe(async()=>{if(handsFree.on)hfStop();else await hfStart();}));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)hfWakeLock();});

// Private access from outside (Tailscale): end the session on this device or on every device.
(async()=>{try{const s=await (await fetch('/remote/status',{credentials:'same-origin',cache:'no-store'})).json();if(!s.remoto||!s.autenticado)return;
  const bar=document.createElement('div');bar.style.cssText='position:fixed;right:12px;bottom:12px;z-index:50;display:flex;gap:8px;font:13px system-ui';
  const mk=(t,fn)=>{const b=document.createElement('button');b.type='button';b.textContent=t;b.style.cssText='padding:8px 12px;border-radius:10px;border:1px solid #ddbd8055;background:#11151ecc;color:#ddbd80;cursor:pointer';b.onclick=fn;return b;};
  const post=p=>fetch(p,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});
  bar.append(mk('Terminar sessão',async()=>{await post('/remote/sair');location.reload();}),
    mk('Terminar em todos os aparelhos',async()=>{if(!confirm('Terminar a sessão em todos os aparelhos (telemóveis, tablets)? Vão ter de voltar a pôr o PIN.'))return;await post('/remote/revogar');await post('/remote/sair');location.reload();}));
  document.body.append(bar);}catch{}})();
