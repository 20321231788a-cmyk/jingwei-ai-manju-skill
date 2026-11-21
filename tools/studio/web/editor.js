 'use strict';
const unitDrafts=new Map(),unitSelections=new Map(),unitVideoVersions=new Map();
let monitorKey='',versionListSignature='',videoMonitorFullscreen=false;
function videoAnnotation(id){return (typeof annotations==='object'&&annotations?.videos?.[id])||{tag:'',note:''};}
function videoMarkPrefix(tag){return tag==='star'?'⭐ ':tag==='bad'?'❌ ':'';}
function syncVideoDialogMode(){
 const dialog=$('#video-dialog'),scriptView=$('#script-view'),toggle=$('#video-dock-toggle');
 if(!dialog)return false;
 const curView=typeof view==='string'?view:'script';
 const canDock=curView==='script'&&!videoMonitorFullscreen&&typeof dialog.show==='function';
 dialog.classList?.toggle?.('docked',canDock);
 scriptView?.classList?.toggle?.('has-docked-monitor',canDock);
 if(toggle)toggle.textContent=canDock?'居中大屏':'贴边对照';
 return canDock;
}
function hasUnsavedUnit(id){return !!unitDrafts.get(id)?.dirty;}
function selectedUnit(){return episode?.units.find(u=>u.id===unitSelections.get(eid));}
function activeScriptUnit(){
 if(!episode?.units?.length)return null;
 try{
  const hash=$('#script-frame')?.contentWindow?.location?.hash?.slice(1)||'';
  if(hash){
   const byHash=episode.units.find(u=>u.local_id===hash||u.id===hash);
   if(byHash){unitSelections.set(eid,byHash.id);return byHash;}
  }
 }catch{}
 return selectedUnit()||episode.units[0];
}
function updateScriptSubmitButtons(){
 const unitBtn=$('#script-submit-unit'),epBtn=$('#script-submit-episode');
 if(unitBtn){
  const u=activeScriptUnit();
  unitBtn.disabled=!episode||!u;
  unitBtn.title=u?`提交当前分镜生成：${u.local_id||u.id} · ${u.title||''}`:'暂无可提交分镜';
 }
 if(epBtn){
  epBtn.disabled=!episode||!(episode.requests||[]).length;
  epBtn.title=episode?`提交本集生成（共 ${(episode.requests||[]).length} 个分镜请求）`:'请先选择剧集';
 }
}
async function submitActiveScriptUnit(){
 if(!episode)return;
 const u=activeScriptUnit();
 if(!u){toast('请先在下方分镜中选择要提交的镜头');return;}
 if(hasUnsavedUnit(u.id)){toast('当前分镜有未保存的中文修改，请先点击“保存中文”后再提交。');return;}
 episode=await api('episode/'+eid);
 const q=requestForUnit(u.id);
 if(!q){toast('当前分镜暂不在可提交列表中');return;}
 if(!canRegenerate(q)){toast(q.blocked_reason||'请先保存中文、同步提示词并补齐参考图后再提交。');return;}
 await openRegen([q.request_id]);
}
async function submitActiveScriptEpisode(){
 if(!episode)return;
 if(episode.units.some(u=>hasUnsavedUnit(u.id))){toast('本集有未保存的中文修改，请先保存后再提交本集。');return;}
 episode=await api('episode/'+eid);
 if(!(episode.requests||[]).some(canRegenerate)){toast('本集暂无可提交的分镜，请先完成同步提示词并补齐参考图。');return;}
 await openRegen(episode.requests.map(q=>q.request_id));
}
function requestForUnit(id){return episode?.requests.find(q=>q.unit_id===id);}
function renderBoardFrame(){
 const frame=$('#script-frame');
 if(!episode){$('#script-title').textContent='暂无正式剧集';frame.removeAttribute('src');updateScriptSubmitButtons();return;}
 $('#script-title').textContent=episode.title;$('#board-open').href='/board/'+eid;
 if(frame.dataset.episode!==eid){
  const requested=new URL(location.href).searchParams.get('unit');
  const unit=episode.units.find(u=>u.id===requested||u.local_id===requested)||episode.units.find(u=>(u.local_id||u.id).includes('EP001_R2_U01'))||episode.units[0];
  unitSelections.set(eid,unit?.id);frame.src='/board/'+eid+(unit?'#'+encodeURIComponent(unit.local_id||unit.id):'');frame.dataset.episode=eid;
 }
 updateScriptSubmitButtons();
 if($('#video-dialog').open&&selectedUnit())renderUnitMonitor(selectedUnit());
}
function versionTime(v){return new Date(v.mtime*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});}
 function renderUnitMonitor(u){
 const q=requestForUnit(u.id),vs=q?variants(q):[],task=q&&currentTask(q);
 let chosen=vs.find(v=>v.id===unitVideoVersions.get(u.id))||vs.find(v=>videoAnnotation(v.id).tag==='star')||vs[0];
 if(chosen)unitVideoVersions.set(u.id,chosen.id);
 $('#unit-video-count').textContent=vs.length+'个版本';$('#unit-version').disabled=!vs.length;
 const videoAnns=typeof annotations==='object'&&annotations?.videos?annotations.videos:{};
 const versionSignature=JSON.stringify([u.id,chosen?.id,vs.map(v=>[v.id,v.mtime,v.seconds,videoAnnotation(v.id)])]);
 if(versionListSignature!==versionSignature){
  $('#unit-version').innerHTML=vs.map((v,i)=>{const a=videoAnnotation(v.id);return `<option value="${v.id}" ${v.id===chosen?.id?'selected':''}>${esc(videoMarkPrefix(a.tag))}${i?'历史版本':'最新版本'} · ${esc(versionTime(v))} · ${v.seconds}秒${a.note?' · '+esc(a.note.slice(0,18)):''}</option>`;}).join('')||'<option>尚无已下载视频</option>';
  $('#unit-history').innerHTML=vs.map((v,i)=>{const a=videoAnnotation(v.id);return `<button class="version-row ${v.id===chosen?.id?'selected':''}" data-unit-version="${v.id}"><strong>${esc(videoMarkPrefix(a.tag))}${i?'历史版本':'最新版本'}</strong><span>${esc(versionTime(v))} · ${v.seconds}秒${a.note?' · '+esc(a.note):''}</span></button>`;}).join('');versionListSignature=versionSignature;
 }
 const markBar=$('#unit-video-mark');
 const chosenAnn=chosen?videoAnnotation(chosen.id):{tag:'',note:''};
 if(markBar){
  markBar.hidden=!chosen;
  if(chosen){
   if(typeof document.querySelectorAll==='function')document.querySelectorAll('[data-video-tag]').forEach(btn=>btn.classList?.toggle?.('active',btn.dataset.videoTag===chosenAnn.tag));
  }
 }
 const generationState=task&&task.state!=='draft'&&task.state!=='ready'?label(task.state,task.downloaded)+(task.note?'<span>'+esc(task.note)+'</span>':''):'<span>尚未提交</span>';
 if($('#unit-generation-state').innerHTML!==generationState)$('#unit-generation-state').innerHTML=generationState;
 const video=$('#unit-video'),key=u.id+'|'+(chosen?.id||'');
 if(monitorKey!==key){
  video.pause();if(chosen){video.src=chosen.url;video.load();}else{video.removeAttribute('src');video.load();}monitorKey=key;
  const noteInput=$('#unit-video-note');if(noteInput)noteInput.value=chosenAnn.note||'';
 }
 $('#unit-video-empty').hidden=!!chosen;
 $('#unit-video-caption').textContent=chosen?(u.pending_sync?'此视频来自此前提交；中文草稿正在等待同步。':chosen.prompt_sha256&&chosen.prompt_sha256===q?.prompt_sha256?'此版本使用当前生效提示词。':'可切换历史版本对照；视频保留提交时的内容。'):'';
 const ctx=$('#unit-context-strip');
 if(ctx){
  const refsById=new Map((episode?.reference_assets||[]).map(r=>[r.id,r]));
  const unitRefs=(u.references||[]).map(rid=>refsById.get(rid)).filter(r=>r&&r.url);
  const lines=(u.editable_values?.dialogue?.length?u.editable_values.dialogue:u.dialogue)||[];
  if(!unitRefs.length&&!lines.length){ctx.hidden=true;ctx.innerHTML='';}
  else{
   ctx.hidden=false;
   const imgs=unitRefs.length?`<div class="ctx-thumbs">${unitRefs.map((r,idx)=>`<button type="button" class="ctx-thumb" data-open-ref-asset="${esc(r.id)}" title="${esc(r.id+' · '+r.purpose)}">${r.type==='video_reference'?`<span>视频 ${idx+1}</span>`:`<img src="${esc(r.url)}" alt="${esc(r.id)}">`}<span>${esc(r.id)}</span></button>`).join('')}</div>`:'';
   const dlg=lines.length?`<div class="ctx-lines">${lines.map(l=>`<p>${esc(l)}</p>`).join('')}</div>`:'';
   ctx.innerHTML=`<div class="monitor-heading"><h3>本镜参考对照</h3><span class="muted">${unitRefs.length} 图 · ${lines.length} 句对白</span></div>${imgs}${dlg}`;
  }
 }
}
function playUnit(id,videoId){
 const u=episode?.units.find(u=>u.id===id),q=u&&requestForUnit(id),vs=q?variants(q):[];
 const v=vs.find(v=>v.id===videoId)||vs.find(v=>videoAnnotation(v.id).tag==='star')||vs[0];if(!v)return;
 unitSelections.set(eid,id);unitVideoVersions.set(id,v.id);$('#video-dialog-title').textContent=u.title+' · 视频版本';renderUnitMonitor(u);
 const dialog=$('#video-dialog'),dock=syncVideoDialogMode();
 if(dialog.open&&typeof dialog.close==='function')dialog.close();
 if(dock)dialog.show();else if(!dialog.open&&typeof dialog.showModal==='function')dialog.showModal();
 $('#unit-video').play().catch(()=>toast('点击播放器即可继续播放'));
}
function collectProfile(){
 const existing=(profiles?.profiles||[]).find(p=>p.id===profileId);
 const sel=$('#profile-model-select'),input=$('#profile-model');
 const selectedModel=(sel&&!sel.hidden&&sel.value&&sel.value!=='__custom__')?sel.value.trim():(input?.value||'').trim();
 if(!selectedModel)throw new Error('请点击“获取模型”选择模型，或手动输入模型名称');
 const baseUrl=($('#profile-base')?.value||'').trim().replace(/\/+$/,'');
 if(!baseUrl)throw new Error('请填写接口地址');
 const urlChanged=!existing||existing.base_url!==baseUrl;
 let preset;
 const rawPreset=($('#preset-map')?.value||'').trim();
 if(rawPreset){
  try{preset=JSON.parse(rawPreset);}catch{throw new Error('预设名称映射须为有效 JSON');}
 }else{
  preset={reference:selectedModel,easy_15:selectedModel,dmad_20:selectedModel,dmad_30:selectedModel};
 }
 preset.reference=selectedModel;
 const p={
  id:profileId||('upstream-'+Date.now()),
  name:($('#profile-name')?.value||'').trim(),
  base_url:baseUrl,
  model:selectedModel,
  preset_map:preset,
  video_resolution:($('#profile-resolution')?.value||'1080p').trim(),
 };
 if(!urlChanged&&existing?.protocol)p.protocol=existing.protocol;
 for(const [field,id] of [['jobs_path','jobs-path'],['presign_path','presign-path'],['commit_path','commit-path'],['video_path','video-path']]){
  const val=($('#'+id)?.value||'').trim();
  if(val&&(!urlChanged||!existing||val!==existing[field]))p[field]=val;
 }
 const conc=Number($('#profile-concurrency')?.value);
 if(Number.isFinite(conc)&&conc>=1)p.max_concurrency=conc;
 if(typeof currentProfileModels!=='undefined'&&Array.isArray(currentProfileModels)&&currentProfileModels.length){
  p.available_models=currentProfileModels.map(m=>m.id||m).filter(Boolean);
 }
 const rawPrice=$('#profile-price')?.value?.trim();
 if(rawPrice){const n=Number(rawPrice);if(!Number.isFinite(n)||n<0||n>1000)throw new Error('每秒单价须在 0–1000 之间');if(n>0)p.price_per_second=Math.round(n*10000)/10000;}
 return p;
}
async function fetchProfileModels(){
 const button=$('#fetch-models');if(button){button.disabled=true;button.textContent='获取中…';}
 $('#profile-error').textContent='';
 const status=$('#profile-models-status');
 try{
  const baseUrl=($('#profile-base')?.value||'').trim().replace(/\/+$/,'');
  if(!baseUrl)throw new Error('请先填写接口地址');
  const existing=(profiles?.profiles||[]).find(p=>p.id===profileId);
  const sameBase=existing&&existing.base_url===baseUrl;
  const payload={base_url:baseUrl,key:$('#profile-key')?.value||'',profile:{id:profileId||'probe-models',base_url:baseUrl}};
  if(sameBase&&existing.protocol)payload.profile.protocol=existing.protocol;
  const result=await api('profiles/models',payload);
  const models=result.models||[];
  const selVal=$('#profile-model-select')&&!$('#profile-model-select').hidden&&$('#profile-model-select').value!=='__custom__'?$('#profile-model-select').value:$('#profile-model')?.value?.trim();
  if(typeof syncProfileModels==='function')syncProfileModels(models,selVal||models[0]?.id||'');
  if(status)status.textContent=result.message||`已获取 ${models.length} 个模型`;
 }catch(error){$('#profile-error').textContent=error.message;if(status)status.textContent='模型获取失败，请检查地址与密钥。';}
 finally{if(button){button.disabled=false;button.textContent='获取模型';}}
}
async function deleteCurrentProfile(){
 const list=profiles?.profiles||[];
 const existing=list.find(p=>p.id===profileId);
 if(!existing){if(typeof resetBlankProfile==='function')resetBlankProfile();return;}
 if(typeof window?.confirm==='function'&&!window.confirm(`确定删除已保存接口「${existing.name}」及已保存密钥？`))return;
 const button=$('#delete-profile');if(button)button.disabled=true;
 $('#profile-error').textContent='';
 try{
  profiles=await api('profiles/delete',{id:existing.id});
  if(typeof populateProfiles==='function')populateProfiles();
  const next=(profiles.profiles||[]).find(p=>p.id===profiles.active)||profiles.profiles?.[0]||null;
  if(typeof fillProfile==='function')fillProfile(next);
  toast('已删除接口及其保存的密钥');
 }catch(error){$('#profile-error').textContent=error.message;}
 finally{if(button)button.disabled=!(profiles?.profiles||[]).some(p=>p.id===profileId);}
}
async function testProfile(){
 const button=$('#profile-test');button.disabled=true;button.textContent='测试中…';$('#profile-error').textContent='';
 try{const result=await api('profiles/test',{profile:collectProfile(),key:$('#profile-key').value});$('#profile-key-status').textContent=result.message;if(result.models?.length&&typeof syncProfileModels==='function'){const cur=($('#profile-model-select')&&!$('#profile-model-select').hidden?$('#profile-model-select').value:$('#profile-model')?.value)||result.models[0].id;syncProfileModels(result.models,cur);}}
 catch(error){$('#profile-error').textContent=error.message;}
 finally{button.disabled=false;button.textContent='测试连接';}
}

async function saveCurrentVideoAnnotation(nextTag,nextNote){
 const u=selectedUnit();const vid=u&&unitVideoVersions.get(u.id);if(!u||!vid)return;
 const current=videoAnnotation(vid);
 const tag=nextTag!==undefined?nextTag:current.tag;
 const note=nextNote!==undefined?nextNote:($('#unit-video-note')?.value??current.note);
 const updated=await api('annotations',{kind:'video',id:vid,tag,note});
 if(typeof annotations==='object')annotations=updated;
 versionListSignature='';renderUnitMonitor(u);
 if(typeof renderLibrary==='function'){lastLibrarySignature='';renderLibrary();}
 toast(tag==='star'?'已标为 ⭐ 优先采用':tag==='bad'?'已标为 ❌ 穿帮':note?'备注已保存':'已清除版本标记');
}
window.addEventListener('message',async event=>{
 const frame=$('#script-frame'),message=event.data;
 if(event.origin!==location.origin||event.source!==frame.contentWindow||message?.type!=='storyboard-editor'||message.episode_id!==eid)return;
 for(const u of episode.units)unitDrafts.set(u.id,{dirty:(message.dirty_units||[]).includes(u.id)});
 if(message.unit_id)unitSelections.set(eid,message.unit_id);
 updateScriptSubmitButtons();
 const summary=$('#script-review-summary'),batchBtn=$('#batch-sync-btn');
 if(summary&&message.review_counts){
  const rc=message.review_counts;
  summary.textContent=`审阅 ${rc.ok||0}/${rc.total||episode.units.length}${rc.fix?` · 待改 ${rc.fix}`:''}`;
 }
 if(batchBtn&&Array.isArray(message.pending_units)){
  const n=message.pending_units.length;batchBtn.hidden=!n;batchBtn.textContent=n?`汇总待同步 (${n})`:'汇总待同步';
 }
 try{
  if(message.action==='saved'){episode=await api('episode/'+eid);await refresh();}
  if(message.action==='submit'){
   episode=await api('episode/'+eid);const q=requestForUnit(message.unit_id);
   if(q&&canRegenerate(q))await openRegen([q.request_id]);else toast('请先保存中文并同步提示词，再提交。');
  }
  if(message.action==='play')playUnit(message.unit_id);
  if(message.action==='batch-copied')toast(`已汇总复制 ${message.count||''} 个待同步修改，粘贴给 AI 即可`);
 }catch(error){toast(error.message);}
});
document.addEventListener('click',async event=>{
 const b=event.target.closest('button');if(!b)return;
 try{
  if(b.dataset.taskPlay){const v=videoById(b.dataset.taskPlay);if(v){if(eid!==v.episode_id)await selectEpisode(v.episode_id);playUnit(v.unit_id,v.id);}}
  if(b.id==='script-profile-open')await openProfiles();
  if(b.id==='script-submit-unit')await submitActiveScriptUnit();
  if(b.id==='script-submit-episode')await submitActiveScriptEpisode();
  if(b.id==='profile-test')await testProfile();
  if(b.id==='fetch-models')await fetchProfileModels();
  if(b.id==='delete-profile')await deleteCurrentProfile();
  if(b.id==='toggle-key-vis'){const k=$('#profile-key');if(k){const show=k.type==='password';k.type=show?'text':'password';b.textContent=show?'隐藏':'显示';}}
  if(b.id==='batch-sync-btn')$('#script-frame')?.contentWindow?.postMessage?.({type:'studio-board-cmd',action:'batch-sync'},location.origin);
  if(b.id==='video-dock-toggle'){videoMonitorFullscreen=!videoMonitorFullscreen;const u=selectedUnit();if(u)playUnit(u.id,unitVideoVersions.get(u.id));}
  if(b.dataset.videoTag!==undefined){const cur=videoAnnotation(unitVideoVersions.get(selectedUnit()?.id));await saveCurrentVideoAnnotation(b.dataset.videoTag===cur.tag&&b.dataset.videoTag!==''?'':b.dataset.videoTag,undefined);}
  if(b.id==='save-video-note')await saveCurrentVideoAnnotation(undefined,$('#unit-video-note')?.value||'');
  if(b.dataset.openRefAsset&&typeof openAssetLightbox==='function'){
   const list=(episode?.reference_assets||[]).filter(r=>r.url);const idx=Math.max(0,list.findIndex(r=>r.id===b.dataset.openRefAsset));
   if(list.length)openAssetLightbox(list,idx);
  }
  if(b.dataset.close==='video-dialog'){$('#unit-video').pause();$('#script-view')?.classList?.remove?.('has-docked-monitor');$('#video-dialog')?.classList?.remove?.('docked');}
 }catch(error){toast(error.message);}
});
document.addEventListener('change',async event=>{
 try{
  if(event.target.id==='unit-version')playUnit(selectedUnit().id,event.target.value);
  if(event.target.id==='profile-model-select'){const v=event.target.value,inp=$('#profile-model');if(inp){if(v==='__custom__'){inp.hidden=false;inp.focus?.();}else{inp.hidden=true;inp.value=v;}}}
  if(event.target.id==='preset-map'){try{const r=JSON.parse(event.target.value).reference||'';if(r&&$('#profile-model'))$('#profile-model').value=r;}catch{}}
  if(event.target.id==='script-profile'){const previous=profiles.active,p=profiles.profiles.find(p=>p.id===event.target.value);if(!p){event.target.value=previous;return;}event.target.disabled=true;try{profiles=await api('profiles',{profile:p});populateProfiles();}catch(error){event.target.value=previous;throw error;}finally{event.target.disabled=false;}}
 }catch(error){toast(error.message);}
});
document.addEventListener('click',event=>{const b=event.target.closest('[data-unit-version]');if(b)playUnit(selectedUnit().id,b.dataset.unitVersion);});
document.querySelector('#video-dialog')?.addEventListener?.('close',()=>{$('#unit-video').pause();$('#script-view')?.classList?.remove?.('has-docked-monitor');$('#video-dialog')?.classList?.remove?.('docked');});
window.addEventListener('beforeunload',event=>{if([...unitDrafts.values()].some(d=>d.dirty)){event.preventDefault();event.returnValue='';}});
