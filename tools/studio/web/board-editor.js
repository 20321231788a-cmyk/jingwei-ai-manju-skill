'use strict';
// Keep the original generated storyboard; enhance its existing text in place.
const boardData=JSON.parse(document.querySelector('#board-editor-data').textContent);
const boardRecords=new Map();
document.documentElement.classList.toggle('board-embedded',parent!==window);
let boardToken='',boardPolling=false;
const boardBoot=fetch('/api/bootstrap').then(r=>r.json()).then(b=>boardToken=b.csrf);
async function boardApi(path,data){
 await boardBoot;
 const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':boardToken},body:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw new Error(body.error||'操作未完成');return body;
}
function pendingUnits(){return [...boardRecords.values()].filter(r=>r.dirty||r.unit.pending_sync);}
function updateBatchSyncButton(){
 const btn=document.getElementById('board-batch-sync');if(!btn)return;
 const count=pendingUnits().length;
 btn.textContent=count?`汇总待同步 (${count})`:'汇总待同步';
 btn.disabled=!count;btn.classList.toggle('accent',count>0);
}
function boardNotify(action,record,extra={}){
 updateBatchSyncButton();
 if(parent!==window)parent.postMessage({type:'storyboard-editor',action,episode_id:boardData.id,unit_id:record?.unit.id,dirty_units:[...boardRecords.values()].filter(r=>r.dirty).map(r=>r.unit.id),pending_units:pendingUnits().map(r=>r.unit.local_id),review_counts:window.__boardReview?window.__boardReview.counts():{total:boardRecords.size,ok:0,fix:0},...extra},location.origin);
}
function boardText(element){return element.innerText.replace(/\r/g,'').replace(/\u00a0/g,' ');}
function boardEditable(element,field,value,label){
 element.contentEditable='plaintext-only';element.spellcheck=false;element.setAttribute('role','textbox');
 element.setAttribute('aria-label',label);element.setAttribute('aria-multiline',field!=='title'&&field!=='duration_s'?'true':'false');
 element.dataset.inlineField=field;element.classList.add('board-editable');element.textContent=value??'';
 return element;
}
function boardParagraph(article,label,field,value){
 const paragraph=[...article.querySelectorAll(':scope > p')].find(p=>p.querySelector('strong')?.textContent===label);
 if(!paragraph)return;
 const strong=paragraph.querySelector('strong'),body=document.createElement('span');
 paragraph.replaceChildren(strong,document.createTextNode('　'),boardEditable(body,field,value,label));
}
function boardChinese(section,value,wan=false,modelLabel='Wan3'){
 const heading=document.createElement('h3');heading.textContent=wan?modelLabel+'分镜（中文）':'H3镜头（中文）';section.replaceChildren(heading);
 if(wan){const p=document.createElement('p');boardEditable(p,'chinese_description',value,modelLabel+'完整中文提示词与段内时间');p.dataset.descriptionIntro='true';section.append(p);return;}
 const matches=[...value.matchAll(/\[Shot \d+\](?:\s+At \d{2}:[0-5]\d\.\d{3},)?/g)];
 const intro=value.slice(0,matches[0]?.index??value.length).trim();
 const p=document.createElement('p');boardEditable(p,'chinese_description',intro,'中文镜头·画面风格');p.dataset.descriptionIntro='true';
 if(!intro)p.dataset.empty='true';section.append(p);
 matches.forEach((match,index)=>{
  const h=document.createElement('h4'),body=document.createElement('p');
  boardEditable(h,'chinese_description',match[0],'中文镜头·镜号与切点');h.dataset.descriptionHeader=String(index);
  boardEditable(body,'chinese_description',value.slice(match.index+match[0].length,matches[index+1]?.index??value.length).trim(),'中文镜头·镜头'+(index+1));body.dataset.descriptionBody=String(index);
  section.append(h,body);
 });
}
function boardReadChinese(article){
 const section=article.querySelector('.chinese-shots'),pieces=[];
 const intro=boardText(section.querySelector('[data-description-intro]')).trim();if(intro)pieces.push(intro);
 section.querySelectorAll('[data-description-header]').forEach(header=>pieces.push(boardText(header).trim()+' '+boardText(section.querySelector('[data-description-body="'+header.dataset.descriptionHeader+'"]')).trim()));
 return pieces.join('\n');
}
function boardApply(record,unit){
 record.unit=unit;record.values=structuredClone(unit.editable_values);record.starting=structuredClone(unit.editable_values);
 record.dirty=false;record.conflict=false;record.latest=null;
 const article=record.article,values=record.values;
 boardEditable(article.querySelector('h2'),'title',values.title,'镜头标题');
 const small=article.querySelector('.shot-head-bar > small, :scope > small')||article.querySelector('small');
 if(small){
  const duration=document.createElement('span'),framing=document.createElement('span');
  small.replaceChildren(document.createTextNode(unit.local_id+' · '),boardEditable(duration,'duration_s',values.duration_s,'时长（秒）'),document.createTextNode('秒 · '),boardEditable(framing,'framing',values.framing,'景别与切点'));
 }
 for(const [label,field] of Object.entries({'拍法概述':'directing_summary','场景':'scene','画面与表演':'action','摄影':'camera','声音':'sound','接点':'continuity'}))boardParagraph(article,label,field,values[field]);
 const section=article.querySelector('.chinese-shots');boardChinese(section,values.chinese_description||'',['wan3','seedance2'].includes(unit.model),unit.model==='seedance2'?'Seedance 2.0':'Wan3');
 if(['wan3','seedance2'].includes(unit.model)){
  const details=article.querySelector(':scope > details'),pre=details?.querySelector('pre'),summary=details?.querySelector('summary');
  const english=unit.prompt_language==='en';
  if(pre)pre.textContent=english?(unit.prompt_text_en||'英文正文待同步'):unit.prompt_text||'';
  if(summary)summary.textContent=unit.local_id+' · '+unit.duration_s+'秒 · 完整'+(unit.model==='seedance2'?'Seedance 2.0':'Wan3')+(english?'英文':'')+'提示词草稿';
 }
 let dialogue=article.querySelector('.board-dialogue');
 if(!dialogue){dialogue=document.createElement('div');dialogue.className='board-dialogue';const quotes=[...article.querySelectorAll(':scope > blockquote')];(quotes[0]||section).insertAdjacentElement(quotes.length?'beforebegin':'afterend',dialogue);quotes.forEach(q=>q.remove());}
 boardEditable(dialogue,'dialogue',(values.dialogue||[]).join('\n'),'对白（每行一句）');dialogue.dataset.placeholder='点击添加对白';
 boardControls(record);
}
function boardControls(record){
 const {article,unit,dirty,saving,conflict}=record;
 const q=boardData.requests.find(q=>q.unit_id===unit.id),task=record.task;
 article.querySelector('[data-board-action="save"]').disabled=!dirty||saving;
 article.querySelector('[data-board-action="save"]').textContent=saving?'保存中…':'保存中文';
 article.querySelector('[data-board-action="submit"]').disabled=dirty||saving||unit.pending_sync||!(q?.ready||q?.ready_for_approval);
 article.querySelector('[data-board-action="submit"]').textContent=task?.job_id?'重新提交':'提交生成';
 article.querySelector('[data-board-action="play"]').disabled=!record.videoCount;
 article.querySelector('[data-board-action="restore"]').disabled=!dirty&&!unit.pending_sync&&!conflict;
 const message=article.querySelector('.board-edit-status');
 message.textContent=conflict?'其他地方已更新此镜，你的输入已保留。可复制内容，或点击“还原/载入”查看最新版本。':dirty?'中文修改尚未保存。':unit.pending_sync?'中文已保存，等待同步英文提示词。':task?.state==='done'?'提示词已同步 · 视频已下载（'+record.videoCount+'个版本）':task&&['running','pending','sending','queued','submitted','waiting_key','capacity_wait','retry_wait'].includes(task.state)?'提示词已同步 · '+({running:'生成中',pending:'上游排队',sending:'提交中',queued:'待提交',submitted:'已提交',waiting_key:'等待密钥',capacity_wait:'等待空位',retry_wait:'等待重试'}[task.state]):'点击正文即可编辑；修改后保存中文。';
 message.classList.toggle('pending',dirty||unit.pending_sync||conflict);
 if(['wan3','seedance2'].includes(unit.model)&&!conflict){if(dirty||unit.pending_sync||q?.blocked_reason||!task)message.textContent=dirty?'中文修改尚未保存。':unit.pending_sync?'中文已保存，等待同步当前模型中文正文与段内切点。':q?.blocked_reason||'中文正文已同步，可点击编辑。';}
}
async function boardSave(record){
 if(!record.dirty||record.saving)return;
 const seq=record.seq,values=structuredClone(record.values);record.saving=true;boardControls(record);
 try{
  const result=await boardApi('unit-draft',{episode_id:boardData.id,unit_id:record.unit.id,base_revision:record.unit.edit_revision,changes:values});
  record.unit=result.unit;record.starting=structuredClone(result.unit.editable_values);record.conflict=false;
  if(record.seq===seq)record.dirty=false;else record.dirty=JSON.stringify(record.values)!==JSON.stringify(record.starting);
  boardNotify('saved',record);await boardPoll();
 }catch(error){record.error=error.message;if(error.message.includes('其他地方'))record.conflict=true;}
 finally{record.saving=false;boardControls(record);if(record.error){record.article.querySelector('.board-edit-status').textContent=record.error;record.error='';}}
}
async function boardRestore(record){
 if(!confirm(record.conflict?'放弃当前输入并载入此镜最新内容？':'放弃本镜未同步的中文修改，恢复上次已同步版本？'))return;
 try{
  if(record.conflict){const latest=await boardApi('episode/'+boardData.id);boardApply(record,latest.units.find(u=>u.id===record.unit.id));}
  else if(record.unit.pending_sync){const result=await boardApi('unit-draft',{episode_id:boardData.id,unit_id:record.unit.id,base_revision:record.unit.edit_revision,discard:true});boardApply(record,result.unit);}
  else boardApply(record,record.unit);
  boardNotify('saved',record);
 }catch(error){record.article.querySelector('.board-edit-status').textContent=error.message;}
}
 async function copyWithFallback(text){
 try{await navigator.clipboard.writeText(text);return true;}
 catch{
  const a=document.createElement('textarea');a.value=text;a.setAttribute('readonly','');a.style.position='fixed';a.style.opacity='0';
  document.body.appendChild(a);a.select();let ok=false;try{ok=document.execCommand('copy');}catch{}a.remove();return ok;
 }
}
async function boardBatchSync(){
 const dirty=[...boardRecords.values()].filter(r=>r.dirty);
 for(const r of dirty){await boardSave(r);if(r.conflict||r.dirty)return;}
 const list=[...boardRecords.values()].filter(r=>r.unit.pending_sync);
 if(!list.length){boardNotify('status-note',null);return;}
 const wanOrSd=list.some(r=>['wan3','seedance2'].includes(r.unit.model));
 const lines=list.map(r=>`- ${r.unit.local_id}（${r.unit.model==='seedance2'?'Seedance 2.0 15秒':r.unit.model==='wan3'?'Wan3 30秒':'H3'}）：${r.values.title||r.unit.title||r.unit.local_id}`).join('\n');
 const text=`请批量同步《${boardData.title}》以下 ${list.length} 个分镜的中文修改。读取 ${boardData.current_data} 中对应段的 editor_draft.values（含 chinese_description 完整中文正文），统一核对${wanOrSd?'模型正文、段内时间切点、对白、图片图序、动作与前后段接点':'英文H3六段提示词、对白、时长、切点与前后镜连续性'}，完成后清除全部草稿并更新看板。本次只同步，不触发付费提交。\n${lines}`;
 const firstStatus=list[0].article.querySelector('.board-edit-status');
 if(await copyWithFallback(text)){if(firstStatus)firstStatus.textContent=`已复制 ${list.length} 镜批量同步请求，直接粘贴到聊天即可。`;boardNotify('batch-copied',list[0],{count:list.length});}
 else{let box=document.querySelector('.board-batch-sync-box');if(!box){box=document.createElement('textarea');box.className='board-sync-text board-batch-sync-box';box.readOnly=true;document.querySelector('main>nav')?.after(box);}box.value=text;box.focus();box.select();}
}
async function boardSync(record){
 const text=['wan3','seedance2'].includes(record.unit.model)?`请同步《${boardData.title}》${record.unit.model==='seedance2'?'Seedance 2.0':'Wan3'}生成段 ${record.unit.local_id} 的中文修改。读取 ${boardData.current_data} 中 ${record.unit.model==='seedance2'?'seedance_groups':'generation_groups'} 对应段的 editor_draft.values（含 chinese_description 完整中文正文），按固定${record.unit.model==='seedance2'?15:30}秒核对并同步段内镜头时间、对白、图片图序、动作及前后段接点，完成后清除该段草稿并更新看板。本次只同步，不付费提交，不处理H3补镜。`:`请同步《${boardData.title}》镜头 ${record.unit.local_id} 的中文修改到英文H3提示词。读取 ${boardData.current_data} 中 editor_draft.values（含 chinese_description 中文镜头译文），核对对白、时长、切点、素材与前后镜连续性，完成后清除草稿并更新看板。本次只同步，不付费提交。`;
 if(await copyWithFallback(text)){record.article.querySelector('.board-edit-status').textContent='同步请求已复制，粘贴到当前聊天即可。';}
 else{let box=record.article.querySelector('.board-sync-text');if(!box){box=document.createElement('textarea');box.className='board-sync-text';box.readOnly=true;record.article.querySelector('.board-edit-toolbar').after(box);}box.value=text;box.focus();box.select();}
}
async function boardPoll(){
 if(boardPolling)return;boardPolling=true;
 try{
  const [latest,state]=await Promise.all([boardApi('episode/'+boardData.id),boardApi('state')]);boardData.requests=latest.requests;
  for(const unit of latest.units){const record=boardRecords.get(unit.id);if(!record)continue;
   record.task=state.tasks.find(t=>t.unit_id===unit.id);record.videoCount=state.videos.filter(v=>v.unit_id===unit.id).length;
   if(unit.edit_revision!==record.unit.edit_revision){if(record.dirty||record.saving){record.conflict=true;record.latest=unit;}else boardApply(record,unit);}
   boardControls(record);
  }
 }catch{ /* Retain input and last known status during temporary disconnection. */ }
 finally{boardPolling=false;}
}
for(const unit of boardData.units){
 const article=document.getElementById(unit.local_id);if(!article)continue;
 const record={unit,article,values:{},starting:{},dirty:false,saving:false,seq:0,videoCount:0};boardRecords.set(unit.id,record);
 const toolbar=document.createElement('div');toolbar.className='board-edit-toolbar';
 for(const [action,label] of Object.entries({save:'保存中文',submit:'提交 / 重提',play:'播放版本',sync:'复制同步请求',restore:'还原/载入'})){
  const button=document.createElement('button');button.type='button';button.dataset.boardAction=action;button.textContent=label;toolbar.append(button);
 }
 const status=document.createElement('p');status.className='board-edit-status';status.setAttribute('role','status');
 article.querySelector('h2').after(toolbar,status);boardApply(record,unit);
}
const navTools=document.querySelector('.board-nav-tools');
if(navTools){
 const batchBtn=document.createElement('button');batchBtn.type='button';batchBtn.id='board-batch-sync';batchBtn.className='board-tool-btn';batchBtn.textContent='汇总待同步';
 batchBtn.addEventListener('click',boardBatchSync);
 navTools.prepend(batchBtn);updateBatchSyncButton();
}
if(window.__boardReview){
 window.__boardReview.state.setRemote=async(localId,review)=>{
  await boardApi('annotations',{kind:'unit',id:boardData.id+'_'+localId,review});
  boardNotify('review',boardRecords.get(boardData.id+'_'+localId));
 };
 boardApi('annotations').then(data=>{
  const map={};const prefix=boardData.id+'_';
  for(const [k,v] of Object.entries(data?.units||{})){if(k.startsWith(prefix)&&v?.review)map[k.slice(prefix.length)]=v.review;}
  window.__boardReview.applyAll(map);boardNotify('review-init',null);
 }).catch(()=>{});
}
window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent)return;
 if(event.data?.type!=='studio-board-cmd')return;
 if(event.data.action==='batch-sync')boardBatchSync();
 if(event.data.action==='toggle-all')document.getElementById('board-toggle-all')?.click();
});
document.addEventListener('input',event=>{
 const element=event.target.closest('[data-inline-field]');if(!element)return;
 const article=element.closest('article'),record=[...boardRecords.values()].find(r=>r.article===article),field=element.dataset.inlineField;
 record.values[field]=field==='duration_s'?Number(boardText(element).trim()):field==='dialogue'?boardText(element).split('\n').filter(s=>s.trim()):field==='chinese_description'?boardReadChinese(article):boardText(element);
 record.seq++;record.dirty=JSON.stringify(record.values)!==JSON.stringify(record.starting);boardControls(record);boardNotify('dirty',record);
});
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-board-action]');if(!button)return;
 const record=[...boardRecords.values()].find(r=>r.article===button.closest('article'));
 const action=button.dataset.boardAction;
 if(action==='save')await boardSave(record);
 if(action==='restore')await boardRestore(record);
 if(action==='sync')await boardSync(record);
 if(action==='submit'||action==='play'){
  if(parent!==window)boardNotify(action,record);
  else window.open('/?view=script&unit='+encodeURIComponent(record.unit.local_id)+'&intent='+action,'_blank','noopener');
 }
});
addEventListener('beforeunload',event=>{if([...boardRecords.values()].some(r=>r.dirty)){event.preventDefault();event.returnValue='';}});
function boardPosition(){
 const article=document.querySelector('article:not([hidden])'),nav=document.querySelector('main>nav');
 if(article&&nav){document.querySelectorAll('article').forEach(a=>a.style.scrollMarginTop=(nav.offsetHeight+12)+'px');window.scrollTo({top:Math.max(0,article.offsetTop-nav.offsetHeight-12)});}
}
addEventListener('load',boardPosition,{once:true});
addEventListener('hashchange',()=>{boardPosition();const record=[...boardRecords.values()].find(r=>r.unit.local_id===location.hash.slice(1));if(record)boardNotify('select',record);});
boardPosition();
boardNotify('ready');boardPoll();setInterval(()=>{if(typeof document==='undefined'||!document.hidden)boardPoll();},12000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)boardPoll();});
