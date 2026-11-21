'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=s=>{s=Math.max(0,Number(s)||0);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(Math.floor(s%60)).padStart(2,'0')};
const statusNames={draft:'待终审 / 待补齐',ready:'可提交',queued:'待提交',pending:'上游排队',running:'生成中',done:'已生成',failed:'生成失败',cancelled:'已取消',rejected:'提交拒绝',uncertain:'结果待核对',sending:'提交中',submitted:'已提交',capacity_wait:'等待空位',retry_wait:'等待重试',waiting_key:'等待卡密',priority_wait:'优先排队'};
let state,episode,csrf,profiles,mixes=[],view='mix',eid='',taskSource='current',mix={name:'初剪',episode_id:'',clips:[]},selected=-1,dirty=false,continuous=false,playingIndex=-1,regenNonce='',regenIds=[],profileId='',dragIndex=-1,lastLibrarySignature='',refreshing=false,refreshPending=false,toastTimer;
let annotations={videos:{},units:{}},assetItems=[],assetType='all',lbList=[],lbIndex=-1,retryTarget={episodeId:'',ids:[]},currentProfileModels=[];
function videoTag(id){return annotations?.videos?.[id]||{tag:'',note:''};}
function videoMarkPrefix(id){const t=videoTag(id).tag;return t==='star'?'⭐ ':t==='bad'?'❌ ':'';}
const player=$('#player');
const episodeDrafts=new Map();
let projectId='',scopedProject='';
const projectEpisodeSelections=new Map();
function selectionStorageKey(){return scopedProject?'studio.selection.'+scopedProject:'studio.selection';}
function projectName(e){return e?.project||e?.title?.split(' · ')[0]||'未分类作品';}
function episodeCode(e){return e?.episode||e?.title?.match(/(?:^| · )((?:EP|SP|OP)\d+)(?: · |$)/i)?.[1]||'剧集';}
function episodeName(e){return e?.name||e?.title?.split(' · ').slice(2).join(' · ')||e?.title||'';}
function projectEpisodes(id=projectId){return (state?.episodes||[]).filter(e=>!id||projectName(e)===id);}
function inProject(rows){const ids=new Set(projectEpisodes().map(e=>e.id));return rows.filter(t=>ids.has(t.episode_id));}
function saveSelection(){
 try{window.localStorage?.setItem(selectionStorageKey(),JSON.stringify({project:projectId,episodes:[...projectEpisodeSelections]}));}catch{}
 if(typeof history!=='undefined'&&history.replaceState){const url=new URL(location.href);url.searchParams.set('view',view);if(projectId&&!scopedProject)url.searchParams.set('project',projectId);if(eid)url.searchParams.set('episode',eid);history.replaceState(null,'',url);}
}
function renderProjects(){
 const names=[...new Set((state?.episodes||[]).map(projectName))],select=$('#project-select');
 const signature=JSON.stringify(names);
 if(select.dataset.projects!==signature){select.innerHTML=names.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('')||'<option value="">暂无正式作品</option>';select.dataset.projects=signature;}
 select.value=projectId;select.disabled=names.length<2;
 $('#project-count').textContent=names.length+' 部';$('#current-project').textContent=projectId||'尚无正式作品';
 $('#task-count').textContent=inProject(state?.tasks||[]).length;
 $('#mix-count').textContent=mixes.filter(m=>projectEpisodes().some(e=>e.id===m.episode_id)).length;
 if($('#asset-count'))$('#asset-count').textContent=(assetItems||[]).filter(a=>!projectId||(a.projects||[]).includes(projectId)).length;
}
function renderIssues(){
 const issues=(state.issues||[]).filter(message=>!projectId||message.startsWith(projectId+'/')||message.startsWith(projectId+'\\')||!/[\\/]/.test(message.split(':')[0]));
 $('#banner').hidden=!issues.length;$('#banner').textContent=issues.join('；');
}
async function selectProject(id){
 const entries=projectEpisodes(id),remembered=projectEpisodeSelections.get(id),target=entries.find(e=>e.id===remembered)||entries[0];
 if(!target){renderProjects();return;}
 $('#project-switch-status').textContent='正在打开作品…';
 try{await selectEpisode(target.id);}finally{renderProjects();$('#project-switch-status').textContent='';}
}
function canRegenerate(q){return !!q&&(q.ready===true||q.ready_for_approval===true)&&!q.pending_sync&&!(typeof hasUnsavedUnit==='function'&&hasUnsavedUnit(q.unit_id));}
let episodeSelectionEpoch=0,previewEpoch=0;
async function api(path,data){const options=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':csrf},body:JSON.stringify(data)};const r=await fetch('/api/'+path,options);const v=await r.json();if(!r.ok)throw new Error(v.error||'操作未完成');return v;}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500);}
function label(status,downloaded=false){const cls=downloaded||status==='done'?'good':['failed','rejected','uncertain','cancelled'].includes(status)?'bad':['running','pending','sending'].includes(status)?'warn':'';return `<span class="tag ${cls}">${esc(downloaded?'已下载':statusNames[status]||status)}</span>`;}
function markDirty(){dirty=true;$('#save-status').textContent='有未保存修改';$('#save-status').style.color='var(--warning)';}
function currentVideos(){return state.videos.filter(v=>v.episode_id===eid);}
function libraryRequests(){
 if(episode.requests.length)return episode.requests;
 const groups=new Map();
 for(const v of currentVideos()){
  const key=v.unit_id||v.request_id;
  if(!groups.has(key))groups.set(key,{request_id:v.request_id,unit_id:key,model_request_seconds:v.seconds,source_request_ids:[],history_only:true,ready:false});
 }
 return [...groups.values()].sort((a,b)=>a.unit_id.localeCompare(b.unit_id,undefined,{numeric:true}));
}
function variants(q){const unitRequests=episode.requests.filter(x=>x.unit_id===q.unit_id);return currentVideos().filter(v=>v.request_id===q.request_id||v.unit_id===q.unit_id&&(q.history_only||unitRequests.length===1||(v.source_request_ids||[]).some(id=>(q.source_request_ids||[]).includes(id))));}
function currentTask(q){return (state.tasks||[]).find(t=>(t.plan_request_id||t.request_id)===q.request_id);}
function chooseVersion(q){
 const vs=variants(q),focused=vs.find(v=>v.id===mix.clips[selected]?.video_id);
 const starred=vs.find(v=>videoTag(v.id).tag==='star');
 return focused||mix.clips.map(c=>vs.find(v=>v.id===c.video_id)).find(Boolean)||starred||vs.find(v=>v.request_id===(currentTask(q)?.request_id||q.request_id))||vs[0];
}
function adoptVersion(requestId,videoId){
 const q=libraryRequests().find(q=>q.request_id===requestId);
 if(!q)throw new Error('此镜头不在当前剧集中，请刷新后重试');
 const vs=variants(q),v=vs.find(v=>v.id===videoId);
 if(!v)throw new Error('此视频版本尚未下载或已不存在');
 stopSequence();player.pause();
 const belongs=c=>c&&vs.some(v=>v.id===c.video_id);
 let index=belongs(mix.clips[selected])?selected:mix.clips.findIndex(belongs);
 if(index<0){
  const a=v.adopted_interval||[0,v.seconds];
  mix.clips.push({video_id:v.id,start:Math.max(0,Number(a[0])),end:Math.min(Number(a[1]),Number(v.seconds))});
  index=mix.clips.length-1;markDirty();
 }else if(mix.clips[index].video_id!==v.id){
  const c=mix.clips[index],a=v.adopted_interval||[0,v.seconds];
  const end=Math.min(c.end,Number(v.seconds));
  if(end-c.start>=.1)c.end=end;
  else{c.start=Math.max(0,Number(a[0]));c.end=Math.min(Number(a[1]),Number(v.seconds));}
  c.video_id=v.id;markDirty();
 }
 selected=index;renderTimeline();previewVideo(v,false,mix.clips[index].start);
 return index;
}
function videoById(id){return state.videos.find(v=>v.id===id);}
function unitTitle(id){return episode?.units.find(u=>u.id===id)?.title||id;}
function renderEpisodes(){
 renderProjects();const entries=projectEpisodes();
 $('#episode-count').textContent=entries.length+' 集';$('#script-count').textContent=entries.length;
 const list=$('#episodes'),previousTop=list.scrollTop,previousLeft=list.scrollLeft,query=$('#episode-search').value.trim().toLowerCase();
 const filtered=entries.filter(e=>(episodeCode(e)+' '+episodeName(e)).toLowerCase().includes(query));
 const baseSig=JSON.stringify([projectId,query,filtered.map(e=>[e.id,e.total,e.downloaded,e.video_count,e.shots,e.revision])]);
 if(list.dataset.baseSig===baseSig&&list.querySelectorAll){
  for(const btn of list.querySelectorAll('button.episode')){const sel=btn.dataset.episode===eid;btn.classList.toggle('selected',sel);btn.setAttribute('aria-pressed',sel?'true':'false');}
  return;
 }
 list.dataset.baseSig=baseSig;
 list.innerHTML=filtered.map(e=>`<button class="episode ${e.id===eid?'selected':''}" data-episode="${esc(e.id)}" aria-pressed="${e.id===eid}"><div class="episode-top"><span>${esc(episodeCode(e))}</span>${e.total&&e.downloaded===e.total?'<span class="tag good">素材齐了</span>':''}</div><span class="episode-name" title="${esc(episodeName(e))}">${esc(episodeName(e))}</span><div class="episode-meta"><span>${e.total?`${e.downloaded} / ${e.total} 现行视频`:`${e.video_count} 个历史素材`}</span><span>${e.shots} 镜</span></div>${e.total?`<div class="mini-progress"><span style="width:${e.downloaded/e.total*100}%"></span></div>`:''}</button>`).join('')||(entries.length?'<div class="empty">本剧未找到匹配的剧集</div>':'<div class="empty">本剧暂无正式剧集</div>');
 list.scrollTop=previousTop;list.scrollLeft=previousLeft;
}
function episodePreviewVideos(){
 return libraryRequests().map(chooseVersion).filter(Boolean);
}
function resetPreview(){
 ++previewEpoch;stopSequence();player.pause();player.removeAttribute('src');player.load();
 playingIndex=-1;$('#preview-mode').hidden=true;$('#play-clock').textContent='00:00';
 $('#playing-title').textContent=eid+' · 暂无可预览视频';$('#playing-version').textContent='本集尚无已下载视频';
 $('#player-empty strong').textContent='本集暂无已下载视频';
 $('#player-empty span').textContent='视频下载完成后，可从右侧素材预览';$('#player-empty').hidden=false;
}
async function selectEpisode(id){
 if(episode&&id!==eid&&typeof hasUnsavedUnit==='function'&&episode.units.some(u=>hasUnsavedUnit(u.id))){toast('本集有未保存的中文修改，请先保存再切换剧集。');return;}
 const selection=++episodeSelectionEpoch;
 try{
  const next=await api('episode/'+id);
  if(selection!==episodeSelectionEpoch)return;
  const changing=episode&&id!==eid;
  if(changing)episodeDrafts.set(eid,{mix:structuredClone(mix),dirty,selected});
   const entry=state.episodes?.find(e=>e.id===id),nextProject=entry?projectName(entry):projectId;
   if(nextProject!==projectId)$('#episode-search').value='';
   projectId=nextProject;projectEpisodeSelections.set(projectId,id);
   eid=id;episode=next;lastLibrarySignature='';resetPreview();
   if(changing&&$('#video-dialog')?.open){$('#unit-video').pause();$('#video-dialog').close();}
  const available=episodePreviewVideos();
  if(changing||mix.episode_id!==eid){
   const draft=episodeDrafts.get(eid);
   const saved=[...mixes].filter(m=>m.episode_id===eid).sort((a,b)=>a.updated_at.localeCompare(b.updated_at)).at(-1);
   if(draft){mix=structuredClone(draft.mix);dirty=draft.dirty;selected=draft.selected;}
   else if(saved){mix=structuredClone(saved);dirty=false;selected=-1;}
   else{
    mix={name:eid+' · 初剪',episode_id:eid,clips:available.map(v=>{const a=v.adopted_interval||[0,v.seconds];return {video_id:v.id,start:Math.max(0,Number(a[0])),end:Math.min(Number(a[1]),Number(v.seconds))};})};
    dirty=false;selected=-1;
   }
  }
  $('#mix-name').value=mix.name;$('#save-status').textContent=dirty?'有未保存修改':mix.id?'已保存':'未保存';
  $('#save-status').style.color=dirty?'var(--warning)':'';$('#export-status').textContent='';
   renderEpisodes();renderEpisode();renderMixOptions();renderTimeline();renderIssues();saveSelection();
  const first=mix.clips.map(c=>videoById(c.video_id)).find(v=>v?.episode_id===eid)||available[0];
  if(first)previewVideo(first);
  const list=$('#episodes'),active=$('#episodes .selected');
  if(active){if(innerWidth<=640)list.scrollLeft=active.offsetLeft-list.offsetLeft;else list.scrollTop=active.offsetTop-list.offsetTop-10;}
  if(view==='script')renderScript();if(view==='assets')renderAssets();if(view==='tasks')renderTasks();
  await renderExports();
 }catch(e){if(selection===episodeSelectionEpoch)toast(e.message);}
}
 function renderEpisode(){$('#save-mix').disabled=false;$('#fill-timeline').disabled=false;const e=state.episodes.find(x=>x.id===eid);$('#episode-title').textContent=episodeCode(e)+' · '+episodeName(e);$('#episode-detail').textContent=`${episode.units.length} 个分镜 · ${e?.downloaded||0} / ${episode.requests.length} 个现行视频已下载${episode.requests.length?'':' · 本集不在现行重提计划中'}`;$('#regen-episode').disabled=!episode.requests.some(canRegenerate);renderLibrary();}
function renderLibrary(){const sig=JSON.stringify([eid,currentVideos(),(state.tasks||[]).filter(t=>t.episode_id===eid),mix.clips.map(c=>c.video_id),selected,annotations?.videos]);if(sig===lastLibrarySignature)return;lastLibrarySignature=sig;
 const libraryScroll=$('#library-list').scrollTop;$('#library-count').textContent=currentVideos().length+' 个版本';
 const requests=libraryRequests();
 $('#library-list').innerHTML=requests.map(q=>{const vs=variants(q),chosen=chooseVersion(q),task=currentTask(q),part=episode.requests.filter(x=>x.unit_id===q.unit_id),suffix=part.length>1?' · 段'+(part.indexOf(q)+1):'';const cMeta=chosen?videoTag(chosen.id):{tag:'',note:''};const markBadge=cMeta.tag==='star'?'<span class="tag good">⭐ 采用</span>':cMeta.tag==='bad'?'<span class="tag bad">❌ 穿帮</span>':'';return `<article class="source-card"><div class="source-line"><strong>${esc(q.unit_id.replace(eid+'_',''))}${suffix} <span class="muted">${q.model_request_seconds}s</span></strong>${markBadge}${q.history_only?'<span class="tag">历史素材</span>':label(task?.state||(q.ready===false?'draft':'ready'),task?.downloaded)}</div><p class="source-title">${esc(unitTitle(q.unit_id))}${cMeta.note?` <span class="muted">· ${esc(cMeta.note)}</span>`:''}</p>${vs.length?`<select data-version="${esc(q.request_id)}" aria-label="${esc(q.unit_id)} 选择视频版本">${vs.map(v=>`<option value="${v.id}" ${chosen?.id===v.id?'selected':''}>${esc(videoMarkPrefix(v.id))}${v.request_id===(task?.request_id||q.request_id)&&!q.history_only?'最新提交':'历史版本'} · ${esc(v.request_id.split(q.unit_id+'-').pop())}</option>`).join('')}</select>`:'<p class="empty-source">此分镜暂无已下载视频</p>'}<div class="source-actions"><button class="button small" data-preview="${esc(q.request_id)}" ${chosen?'':'disabled'}>预览</button><button class="button small" data-add="${esc(q.request_id)}" ${chosen?'':'disabled'}>加入</button>${q.history_only?'':`<button class="button small subtle" data-regen="${esc(q.request_id)}" ${canRegenerate(q)?'':'disabled'}>提交 / 重提</button>`}</div></article>`}).join('')||'<div class="empty">本集暂无已登记的下载视频</div>';$('#library-list').scrollTop=libraryScroll;}
function stopSequence(){continuous=false;$('#preview-mode').hidden=true;$('#play-mix').lastChild.textContent='连续预览';}
function previewVideo(v,autoplay=false,start=0){if(!v)return;const playback=++previewEpoch;$('#player-empty').hidden=true;$('#playing-title').textContent=v.unit_id||'视频预览';$('#playing-version').textContent=v.request_id;const absolute=new URL(v.url,location.href).href;if(player.src!==absolute){player.src=v.url;player.load();}const seek=()=>{if(playback!==previewEpoch)return;player.currentTime=Math.min(start,Math.max(0,(player.duration||v.seconds)-.02));if(autoplay)player.play().catch(()=>toast('点击播放器继续播放'));};if(player.readyState>=1)seek();else player.addEventListener('loadedmetadata',seek,{once:true});}
function addVideo(v){if(!v)return;const a=v.adopted_interval||[0,v.seconds];mix.clips.push({video_id:v.id,start:Math.max(0,Number(a[0])),end:Math.min(Number(a[1]),Number(v.seconds))});selected=mix.clips.length-1;markDirty();renderTimeline();toast('已加入时间轴');}
function renderTimeline(){const total=mix.clips.reduce((s,c)=>s+c.end-c.start,0);$('#timeline-count').textContent=mix.clips.length+' 个片段';$('#timeline-duration').textContent=time(total);$('#timeline').innerHTML=mix.clips.length?mix.clips.map((c,i)=>{const v=videoById(c.video_id),shot=(v?.unit_id||'缺失').split('_').pop();return `<button draggable="true" class="clip ${selected===i?'selected':''}" data-clip="${i}" aria-label="片段 ${i+1} ${esc(v?.unit_id||'素材缺失')}" title="${esc(v?.request_id||'素材缺失')} · ${c.start.toFixed(1)}–${c.end.toFixed(1)} 秒">${esc(shot)}</button>`}).join(''):'<div class="timeline-empty">从素材中选择镜头加入时间轴</div>';$('#play-mix').disabled=!mix.clips.length;$('#export-mix').disabled=!mix.clips.length;if($('#export-srt'))$('#export-srt').disabled=!mix.clips.length;renderTrim();if(episode)renderLibrary();}
function renderTrim(){const c=mix.clips[selected],box=$('#trim-editor');box.hidden=!c;if(!c)return;box.innerHTML=`<span class="muted">片段 ${selected+1}</span><label>入点<input id="trim-start" type="number" step="0.1" min="0" value="${c.start}" aria-label="片段入点"></label><button id="mark-in" type="button" class="button small" title="按快捷键 I 以当前播放位置作为入点">设为入点</button><label>出点<input id="trim-end" type="number" step="0.1" min="0.1" value="${c.end}" aria-label="片段出点"></label><button id="mark-out" type="button" class="button small" title="按快捷键 O 以当前播放位置作为出点">设为出点</button><button id="apply-trim" type="button" class="button small">应用区间</button><div class="trim-tools"><button id="clip-left" type="button" class="button small" ${selected===0?'disabled':''}>前移</button><button id="clip-right" type="button" class="button small" ${selected===mix.clips.length-1?'disabled':''}>后移</button><button id="clip-remove" type="button" class="button small">移除</button></div>`;}
function markClipBoundary(kind){
 const c=mix.clips[selected];if(!c)throw new Error('请先在时间轴上选中片段');
 const v=videoById(c.video_id);if(!v)throw new Error('当前片段视频已失效');
 const maxDur=Math.min(Number(v.seconds),Number(player.duration)||Number(v.seconds));
 const cur=Math.max(0,Math.min(maxDur,Math.round((Number(player.currentTime)||0)*10)/10));
 if(kind==='in'){
  if(c.end-cur<.1)throw new Error('当前位置距出点不足 0.1 秒');
  c.start=cur;
 }else{
  if(cur-c.start<.1)throw new Error('出点须晚于入点至少 0.1 秒');
  c.end=cur;
 }
 stopSequence();player.pause();markDirty();renderTimeline();previewVideo(v,false,c.start);
 toast(`已设置${kind==='in'?'入点':'出点'}：${cur.toFixed(1)} 秒`);
}
function playClip(index){if(index>=mix.clips.length){player.pause();stopSequence();return;}const c=mix.clips[index],v=videoById(c.video_id);if(!v){stopSequence();toast('此片段的本地视频已不存在，请重新选择');return;}playingIndex=index;selected=index;renderTimeline();continuous=true;$('#preview-mode').hidden=false;$('#play-mix').lastChild.textContent='停止连播';previewVideo(v,true,c.start);}
player.addEventListener('timeupdate',()=>{$('#play-clock').textContent=time(player.currentTime);if(continuous){const c=mix.clips[playingIndex];if(c&&player.currentTime>=c.end-.04)playClip(playingIndex+1);}});
player.addEventListener('ended',()=>{if(continuous)playClip(playingIndex+1)});
player.addEventListener('error',()=>{if(player.getAttribute('src')){stopSequence();toast('无法播放此视频，请刷新素材或检查本地文件。')}});
function switchView(next){view=next;$$('[data-view]').forEach(b=>{b.classList?.toggle?.('active',b.dataset.view===next);b.setAttribute?.('aria-current',b.dataset.view===next?'page':'false')});for(const name of ['mix','script','assets','tasks']){const el=$('#'+name+'-view');if(el)el.hidden=name!==next;}$('#page-title').textContent={mix:'混剪台',script:'剧本',assets:'资产库',tasks:'制作任务'}[next];$('#page-subtitle').textContent={mix:'把每一个镜头，接成完整的故事。',script:'直接在原分镜头看板中编辑、保存与提交。',assets:'一屏核对人物、场景、道具与参考视频，点击原地放大。',tasks:'与自动提交脚本同步，查看真实生成、下载进度与消耗统计。'}[next];if(next!=='mix'){player.pause();stopSequence();}if(next!=='script'){if($('#unit-video')?.pause)$('#unit-video').pause();const vd=$('#video-dialog');if(vd?.open&&vd.classList?.contains?.('docked')){vd.close?.();vd.classList.remove('docked');$('#script-view')?.classList?.remove?.('has-docked-monitor');}}if(next==='script')renderScript();if(next==='assets')renderAssets();if(next==='tasks')renderTasks();saveSelection();}
function renderScript(){if(typeof renderBoardFrame==='function'){renderBoardFrame();return;}if(!episode){$('#script-title').textContent='版式预览 · 非正式剧集';$('#script-frame').src='/preview';$('#board-open').href='/preview';return;}$('#script-title').textContent=eid+' · '+episode.title;const url='/board/'+eid;$('#board-open').href=url;if($('#script-frame').dataset.episode!==eid+episode.revision){$('#script-frame').src=url;$('#script-frame').dataset.episode=eid+episode.revision;}}
const assetTypeLabels={character_sheet:'人物设定',background:'场景底图',prop:'道具',video_reference:'视频参考'};
function filteredAssets(){
 const scope=$('#asset-scope')?.value||'project';
 const query=($('#asset-search')?.value||'').trim().toLowerCase();
 return (assetItems||[]).filter(a=>{
  if(projectId&&!(a.projects||[]).includes(projectId))return false;
  if(scope==='episode'&&!(a.episodes||[]).some(ep=>ep.id===eid))return false;
  if(assetType==='pending'){if(a.url&&a.verified===true)return false;}
  else if(assetType!=='all'&&a.type!==assetType)return false;
  if(!query)return true;
  const hay=[a.id,...(a.ids||[]),a.path,a.purpose,...(a.episodes||[]).map(ep=>ep.code+' '+ep.title)].join(' ').toLowerCase();
  return hay.includes(query);
 });
}
function renderAssets(){
 const grid=$('#asset-grid');if(!grid)return;
 const list=filteredAssets();
 grid.innerHTML=list.length?list.map((a,i)=>{
  const badge=a.url?(a.verified===true?'<span class="tag good">已核验</span>':'<span class="tag warn">待核验</span>'):'<span class="tag bad">缺失</span>';
  const media=a.url?(a.type==='video_reference'?`<video preload="metadata" src="${esc(a.url)}"></video>`:`<img loading="lazy" src="${esc(a.url)}" alt="${esc(a.id)}">`):'<div class="asset-missing">待补素材</div>';
  const sizeText=a.width&&a.height?`${a.width}×${a.height}`:'';
  const eps=(a.episodes||[]).map(ep=>`<button type="button" class="asset-ep-pill" data-jump-episode="${esc(ep.id)}" data-jump-unit="${esc(ep.units?.[0]||'')}" title="${esc(ep.title)}">${esc(ep.code||ep.title)}</button>`).join('');
  return `<article class="asset-card"><button type="button" class="asset-thumb" data-asset-open="${i}" ${a.url?'':'disabled'}>${media}</button><div class="asset-body"><div class="asset-head"><strong>${esc(a.id||a.ids?.[0]||'未命名')}</strong><span class="tag">${esc(assetTypeLabels[a.type]||a.type)}</span>${badge}</div><p class="asset-purpose">${esc(a.purpose||'未填写用途说明')}</p><div class="asset-meta">${sizeText?`<span>${sizeText}</span>`:''}<span title="${esc(a.path)}">${esc(a.path||'路径未填')}</span></div><div class="asset-eps">${eps}</div><div class="asset-actions"><button type="button" class="button small" data-asset-open="${i}" ${a.url?'':'disabled'}>大图核验</button><button type="button" class="button small subtle" data-asset-redraw="${i}">复制重画</button></div></div></article>`;
 }).join(''):'<div class="empty">当前筛选条件下暂无设定库素材</div>';
}
function updateLightbox(){
 const it=lbList[lbIndex];if(!it)return;
 const img=$('#lb-img'),vid=$('#lb-video'),stage=$('#lb-stage'),zoom=$('#lb-zoom');
 stage?.classList?.remove?.('zoomed');if(zoom)zoom.textContent='100% 原始尺寸';
 $('#lb-title').textContent=(it.id?it.id+' · ':'')+(it.purpose||'资产预览');
 $('#lb-meta').textContent=`${lbIndex+1} / ${lbList.length}${it.path?' · '+it.path:''}`;
 if($('#lb-raw'))$('#lb-raw').href=it.url||'#';
 if(it.type==='video_reference'){
  img.hidden=true;img.removeAttribute('src');vid.hidden=false;vid.src=it.url;vid.load();if(zoom)zoom.hidden=true;
 }else{
  vid.pause?.();vid.hidden=true;vid.removeAttribute?.('src');img.hidden=false;if(zoom)zoom.hidden=false;
  img.onload=()=>{$('#lb-meta').textContent=`${lbIndex+1} / ${lbList.length} · ${img.naturalWidth}×${img.naturalHeight}${it.path?' · '+it.path:''}`;};
  img.src=it.url;
 }
 if($('#lb-info'))$('#lb-info').textContent=it.purpose||'';
}
function openAssetLightbox(list,index){
 lbList=(list||[]).filter(a=>a&&a.url);if(!lbList.length)return;
 lbIndex=Math.max(0,Math.min(lbList.length-1,index||0));
 updateLightbox();
 const dlg=$('#asset-lightbox');if(dlg&&!dlg.open)dlg.showModal?.();
}
function copyRedrawInstruction(item){
 if(!item)return;
 const cmd=`请依据当前《delivery.md》和《style-presets.md》审美规范重画「${item.id||item.path}」（${item.purpose||'参考图'}），保持原身份/透视关系，提升电影级光影立体感、材质细节与高级配色，完成后回写并核验。`;
 navigator.clipboard?.writeText?.(cmd).then(()=>toast('已复制重画指令，粘贴到聊天发送即可')).catch(()=>toast(cmd));
}
function profilePrice(upstreamName){
 const p=(profiles?.profiles||[]).find(x=>x.name===upstreamName);
 return Number(p?.price_per_second)||0;
}
function renderTasks(){
 const currentOnly=$('#task-episode').value==='current';
 const scoped=rows=>inProject(rows||[]).filter(t=>!currentOnly||t.episode_id===eid);
 const current=scoped(state.tasks),count=states=>current.filter(t=>states.includes(t.state)).length,done=current.filter(t=>t.downloaded).length;
 $('#task-project-title').textContent=(projectId?projectId+' · ':'')+'制作任务';
 $('#done-count').textContent=done+' / '+current.length;
 $('#running-count').textContent=count(['pending','running','sending','submitted']);
 $('#waiting-count').textContent=count(['queued','ready','draft','waiting_key','capacity_wait','retry_wait']);
 $('#failed-count').textContent=count(['failed','rejected','uncertain','cancelled']);
 const submitted=scoped(state.tasks).concat(scoped(state.history)).filter(t=>t.job_id||['done','failed','rejected','cancelled','uncertain','running','pending','sending','submitted'].includes(t.state));
 const totalSec=submitted.reduce((s,t)=>s+(Number(t.seconds)||0),0);
 const estCost=submitted.reduce((s,t)=>s+(Number(t.seconds)||0)*profilePrice(t.upstream),0);
 if($('#cost-count'))$('#cost-count').textContent=estCost>0?`¥${estCost.toFixed(1)}`:`${submitted.length} 次`;
 if($('#cost-meta'))$('#cost-meta').textContent=estCost>0?`累计 ${submitted.length} 次 · ${totalSec}秒`:`累计生成 ${totalSec}秒（接口填单价可估费）`;
 const problemSet=new Set(['failed','rejected','uncertain','cancelled']);
 const failedRows=current.filter(t=>problemSet.has(t.state));
 const preferredEp=failedRows.some(t=>t.episode_id===eid)?eid:failedRows[0]?.episode_id||'';
 const targetFailed=preferredEp?failedRows.filter(t=>t.episode_id===preferredEp):[];
 retryTarget={episodeId:preferredEp,ids:targetFailed.map(t=>t.plan_request_id||t.request_id)};
 const retryBtn=$('#retry-failed');
 if(retryBtn){
  retryBtn.hidden=!targetFailed.length;
  if(targetFailed.length)retryBtn.textContent=`一键重提失败镜 (${targetFailed.length})`;
 }
 $('#overall-progress').style.width=(current.length?done/current.length*100:0)+'%';
 $('#task-updated').textContent='记录读取于 '+state.updated_at.slice(11,19);
 const filter=$('#task-status').value;
 const rows=scoped(taskSource==='current'?state.tasks:(state.history||[])).filter(t=>filter==='all'||filter==='downloaded'&&t.downloaded||filter==='active'&&['pending','running','sending','submitted'].includes(t.state)||filter==='queued'&&['queued','ready','draft','waiting_key','capacity_wait','retry_wait'].includes(t.state)||filter==='problem'&&problemSet.has(t.state));
 $('#task-rows').innerHTML=rows.map(t=>{
  const e=state.episodes.find(e=>e.id===t.episode_id),video=(state.videos||[]).find(v=>v.request_id===t.request_id);
  return `<tr><td><strong title="${esc(t.unit_id)}">${esc(episodeCode(e))} · ${esc(t.unit_id.replace(t.episode_id+'_',''))}</strong><span class="version">${esc(episodeName(e))}</span><span class="version" title="${esc(t.request_id)}">${esc(t.request_id)}</span>${t.note?`<span class="task-note-text">${esc(t.note)}</span>`:''}</td><td>${t.seconds}s</td><td>${label(t.source==='studio'&&['queued','capacity_wait'].includes(t.state)?'priority_wait':t.state)}</td><td>${t.downloaded?'<span class="tag good">已下载</span>'+(video?` <button class="button small" data-task-play="${esc(video.id)}">播放</button>`:''):t.state==='done'?'<span class="tag warn">等待下载</span>':'<span class="muted">未下载</span>'}</td><td>${esc(t.job_id||'—')}</td><td>${esc(t.upstream)}</td></tr>`;
 }).join('')||`<tr><td colspan="6" class="empty">${taskSource==='history'?'本剧此范围暂无提交历史':'本剧此范围暂无任务'}</td></tr>`;
}
async function refresh(){
 if(refreshing){refreshPending=true;return;}refreshing=true;
 try{
  state=await api('state');$('#connection').textContent='记录已连接';$('.dot').style.background='var(--good)';
  renderEpisodes();
  if((!episode||!state.episodes.some(e=>e.id===eid))&&state.episodes.length){const entries=projectEpisodes(),target=entries.find(e=>e.id===projectEpisodeSelections.get(projectId))||entries[0]||state.episodes[0];await selectEpisode(target.id);}
  if(episode){const current=state.episodes.find(e=>e.id===eid);if(current&&current.revision!==episode.revision)await selectEpisode(eid);else renderEpisode();}
  renderIssues();if(view==='script')renderScript();if(view==='assets'){api('assets').then(a=>{assetItems=a.assets||[];renderProjects();renderAssets();}).catch(()=>{});}if(view==='tasks')renderTasks();await renderExports();
 }catch(e){$('#connection').textContent='连接中断';$('.dot').style.background='var(--warning)';$('#banner').textContent='本地看板连接中断，请重新运行“启动制作看板.cmd”。上游已接收的任务继续生成。';$('#banner').hidden=false;}
 finally{refreshing=false;if(refreshPending){refreshPending=false;await refresh();}}
}
function renderMixOptions(){$('#mix-select').innerHTML='<option value="">新方案</option>'+mixes.filter(m=>m.episode_id===eid).map(m=>`<option value="${m.id}" ${m.id===mix.id?'selected':''}>${esc(m.name)}</option>`).join('');$('#mix-count').textContent=mixes.filter(m=>projectEpisodes().some(e=>e.id===m.episode_id)).length;}
async function saveMix(){mix.name=$('#mix-name').value.trim()||eid+' · 初剪';mix.episode_id=mix.episode_id||eid;mix=await api('mixes',mix);mixes=(await api('mixes')).mixes;dirty=false;episodeDrafts.delete(eid);$('#save-status').textContent='已保存';$('#save-status').style.color='';renderMixOptions();return mix;}
async function renderExports(){const targetMix=mix;const exports=await api('exports');if(targetMix!==mix)return;const relevant=exports.filter(e=>e.name===mix.name).slice(0,3);$('#export-status').innerHTML=relevant.map(e=>e.state==='done'?`<div class="export-result"><strong>已导出 · ${time(e.duration)}</strong><a href="${e.video}" target="_blank" rel="noopener">播放 MP4</a><a href="${e.video}" download="${esc(e.name)}.mp4">下载</a><a href="${e.manifest}" download>剪辑清单</a>${e.subtitle?`<a href="${e.subtitle}" download="${esc(e.name)}.srt">下载 SRT</a>`:''}</div>`:`<div class="export-result"><span>${e.state==='running'||e.state==='queued'?`正在导出 ${e.completed} / ${e.total} 个片段…`:esc(e.error||'导出中断，请重试')}</span></div>`).join('');}
function populateProfiles(){
 const list=profiles?.profiles||[];
 const opts=list.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')||'<option value="">暂无已保存接口</option>';
 for(const id of ['profile-select','regen-profile','script-profile']){const el=$('#'+id);if(el){el.innerHTML=opts;el.value=list.some(p=>p.id===profiles.active)?profiles.active:(list[0]?.id||'');}}
 const active=list.find(p=>p.id===profiles.active)||list[0];
 $('#upstream-label').textContent=active?.name||'未配置';
 const status=$('#script-profile-status');
 if(status)status.textContent=active?`${active.model||active.preset_map?.reference||''} · ${active.video_resolution||'默认画质'} · ${active.credential_ready?'已保存密钥':'待填写密钥'}`:'请点击右侧“配置接口”新增真实接口';
}
function syncProfileModels(models,selectedModel=''){
 const list=(models||[]).map(m=>typeof m==='string'?{id:m,label:m,enabled:true}:m).filter(m=>m&&m.id);
 currentProfileModels=list;
 const sel=$('#profile-model-select'),inp=$('#profile-model');
 if(!sel||!inp)return;
 if(list.length){
  const target=selectedModel||list[0].id;
  const hasTarget=list.some(m=>m.id===target);
  const extra=target&&!hasTarget?`<option value="${esc(target)}">${esc(target)}（当前）</option>`:'';
  sel.innerHTML=extra+list.map(m=>`<option value="${esc(m.id)}" ${m.enabled===false?'disabled':''}>${esc(m.label||m.id)}${m.enabled===false?'（暂不可用）':''}</option>`).join('')+'<option value="__custom__">手动输入其他模型…</option>';
  sel.value=target||'__custom__';
  sel.hidden=false;
  inp.hidden=sel.value!=='__custom__';
  inp.value=sel.value==='__custom__'?target:sel.value;
 }else{
  sel.innerHTML='';sel.hidden=true;
  inp.hidden=false;inp.value=selectedModel||'';
 }
}
function resetBlankProfile(){
 fillProfile({id:'upstream-'+Date.now(),name:'',base_url:'',model:'',video_resolution:'1080p',jobs_path:'',presign_path:'',commit_path:'',video_path:'',max_concurrency:10,available_models:[],credential_ready:false});
 if($('#profile-select'))$('#profile-select').value='';
}
function fillProfile(p){
 if(!p){resetBlankProfile();return;}
 profileId=p.id;
 $('#profile-name').value=p.name||'';
 $('#profile-base').value=p.base_url||'';
 if($('#profile-key')){$('#profile-key').value='';$('#profile-key').type='password';}
 if($('#toggle-key-vis'))$('#toggle-key-vis').textContent='显示';
 if($('#profile-price'))$('#profile-price').value=p.price_per_second?String(p.price_per_second):'';
 if($('#jobs-path'))$('#jobs-path').value=p.jobs_path||'';
 if($('#presign-path'))$('#presign-path').value=p.presign_path||'';
 if($('#commit-path'))$('#commit-path').value=p.commit_path||'';
 if($('#video-path'))$('#video-path').value=p.video_path||'';
 if($('#preset-map'))$('#preset-map').value=p.preset_map?JSON.stringify(p.preset_map,null,2):'';
 if($('#profile-concurrency')){
  $('#profile-concurrency').max=p.protocol==='wan-portal-v1'?2000:p.protocol==='sparkcine-v1'?150:p.protocol==='doubao-canvas-v1'?1:100;
  $('#profile-concurrency').value=p.max_concurrency||10;
 }
 if($('#profile-resolution-label'))$('#profile-resolution-label').hidden=false;
 if($('#profile-resolution'))$('#profile-resolution').value=(p.video_resolution||'1080p').toLowerCase();
 const modelName=p.model||p.preset_map?.reference||'';
 syncProfileModels(p.available_models||[],modelName);
 $('#profile-key-status').textContent=p.credential_ready?`已本机加密永久保存密钥（${p.key_masked||'已保存'}）；留空继续使用，填写新密钥可覆盖保存。`:'尚未保存密钥；填入密钥并保存后将本机加密永久保存，重启看板仍生效。';
 const ms=$('#profile-models-status');
 if(ms)ms.textContent=(p.available_models||[]).length?`已缓存 ${p.available_models.length} 个上游模型，可点击“获取模型”刷新`:'填写接口地址与密钥后，点击“获取模型”可直接向上游拉取可用模型。';
 const delBtn=$('#delete-profile');
 if(delBtn)delBtn.disabled=!(profiles?.profiles||[]).some(x=>x.id===p.id);
 $('#profile-error').textContent='';
}
async function openProfiles(){profiles=await api('profiles');populateProfiles();const target=(profiles.profiles||[]).find(p=>p.id===profiles.active)||profiles.profiles?.[0]||null;fillProfile(target);$('#profile-dialog').showModal();}
function regenDescription(){
 const p=(profiles?.profiles||[]).find(x=>x.id===$('#regen-profile').value);
 $('#regen-endpoint').textContent=p?p.base_url+p.jobs_path:'请先点击“提交接口”新增并保存真实接口';
 $('#regen-key').placeholder=p?.credential_ready?'已保存密钥，留空直接提交；填写新密钥将覆盖保存':'请输入此接口的 API Key（保存后自动记住）';
 const checked=$$('#regen-items input:checked');const reqs=checked.map(i=>episode.requests.find(q=>q.request_id===i.value)).filter(Boolean);const seconds=reqs.reduce((s,q)=>s+q.model_request_seconds,0);const rate=Number(p?.price_per_second)||0;
 $('#regen-total').textContent=`本次提交 ${checked.length} 个请求 · 总生成 ${seconds} 秒`+(rate>0?` · 预估费用 ¥${(seconds*rate).toFixed(2)}`:'');
 $('#regen-submit').textContent=`确认付费提交 ${checked.length} 个请求`;$('#regen-submit').disabled=!checked.length||!p;
 const hint=$('#regen-hint');
 if(hint){
  const summary=[...new Set(reqs.map(q=>`${q.requested_model||'模型'} ${q.model_request_seconds}秒`))].join(' / ');
  const targetModel=p?.model||p?.preset_map?.reference||'';
  hint.textContent=p&&summary?`按分镜锁定规格（${summary}）提交到 ${p.name}${targetModel?'（'+targetModel+'）':''}，不会自动改时长。`:'逐镜按当前制作数据锁定的模型与请求时长提交（如 Wan3 30秒、Seedance 2.0 15秒或 H3 短补镜），不会自动改时长或更换模型。';
 }
}
async function openRegen(ids){if(!episode)return;profiles=await api('profiles');populateProfiles();regenIds=ids;regenNonce=crypto.randomUUID();$('#regen-title').textContent=ids.length===episode.requests.length?'提交 / 重提本集 · '+episode.title:'提交 / 重提镜头 · '+episode.title;$('#regen-key').value='';$('#regen-error').textContent='';$('#regen-items').innerHTML=episode.requests.filter(q=>ids.includes(q.request_id)).map(q=>`<div class="regen-item"><label><input type="checkbox" ${canRegenerate(q)?'checked':'disabled'} value="${esc(q.request_id)}">${esc(unitTitle(q.unit_id))}</label><span>${q.model_request_seconds}s · ${esc(q.blocked_reason||(!canRegenerate(q)?'待保存或待终审':q.preset))}</span></div>`).join('');regenDescription();$('#regen-dialog').showModal();}
document.addEventListener('click',async e=>{const b=e.target.closest('button,a');if(!b)return;try{
 if(b.dataset.view)switchView(b.dataset.view);
 if(b.dataset.episode)await selectEpisode(b.dataset.episode);
 if(b.dataset.close)$('#'+b.dataset.close).close();
 if(b.dataset.preview){stopSequence();previewVideo(chooseVersion(libraryRequests().find(q=>q.request_id===b.dataset.preview)));}
 if(b.dataset.previewVideo){stopSequence();previewVideo(videoById(b.dataset.previewVideo));}
 if(b.dataset.add)addVideo(chooseVersion(libraryRequests().find(q=>q.request_id===b.dataset.add)));
 if(b.dataset.addVideo)addVideo(videoById(b.dataset.addVideo));
 if(b.dataset.regen)await openRegen([b.dataset.regen]);
 if(b.dataset.clip!==undefined){stopSequence();player.pause();selected=Number(b.dataset.clip);const c=mix.clips[selected];renderTimeline();previewVideo(videoById(c.video_id),false,c.start);}
 if(b.dataset.taskSource){taskSource=b.dataset.taskSource;$$('[data-task-source]').forEach(x=>x.classList?.toggle?.('selected',x===b));renderTasks();}
 if(b.dataset.assetType){assetType=b.dataset.assetType;$$('[data-asset-type]').forEach(x=>x.classList?.toggle?.('selected',x===b));renderAssets();}
 if(b.dataset.assetOpen!==undefined){openAssetLightbox(filteredAssets(),Number(b.dataset.assetOpen));}
 if(b.dataset.assetRedraw!==undefined){copyRedrawInstruction(filteredAssets()[Number(b.dataset.assetRedraw)]);}
 if(b.dataset.jumpEpisode){
  const unitId=b.dataset.jumpUnit;await selectEpisode(b.dataset.jumpEpisode);switchView('script');
  if(unitId&&$('#script-frame')){const base='/board/'+eid;$('#script-frame').src=base+'#'+encodeURIComponent(unitId);$('#script-frame').dataset.episode=eid;}
 }
 switch(b.id){
 case 'profile-open':await openProfiles();break;
 case 'regen-episode':await openRegen(episode.requests.map(q=>q.request_id));break;
 case 'retry-failed':{
  if(!retryTarget.episodeId||!retryTarget.ids.length)break;
  if(eid!==retryTarget.episodeId)await selectEpisode(retryTarget.episodeId);
  const readyIds=retryTarget.ids.filter(id=>canRegenerate(episode.requests.find(q=>q.request_id===id)));
  if(!readyIds.length){toast('失败镜头所在集存在未同步中文或尚未完成终审，暂无法一键重提');break;}
  await openRegen(readyIds);break;
 }
 case 'save-mix':await saveMix();toast('剪辑方案已保存');break;
 case 'new-mix':if(!episode){toast('先选择实际剧集');break;}if(dirty)await saveMix();stopSequence();player.pause();mix={name:eid+' · 初剪 '+(mixes.length+1),episode_id:eid,clips:[]};selected=-1;dirty=false;$('#mix-name').value=mix.name;$('#save-status').textContent='新方案';renderMixOptions();renderTimeline();renderExports();break;
 case 'fill-timeline':{if(!episode)break;let added=0;const occupied=new Set(mix.clips.map(c=>c.video_id));for(const q of libraryRequests()){const v=chooseVersion(q);if(v&&!occupied.has(v.id)){const a=v.adopted_interval||[0,v.seconds];mix.clips.push({video_id:v.id,start:a[0],end:Math.min(a[1],v.seconds)});occupied.add(v.id);added++;}}if(added){markDirty();renderTimeline();}toast(added?`已按顺序加入 ${added} 个片段；历史版本请逐镜检查`:'没有可加入的新素材');break;}
 case 'mark-in':markClipBoundary('in');break;
 case 'mark-out':markClipBoundary('out');break;
 case 'apply-trim':{const start=Number($('#trim-start').value),end=Number($('#trim-end').value),c=mix.clips[selected],v=videoById(c.video_id);if(!Number.isFinite(start+end)||start<0||end-start<.1||end>v.seconds)throw new Error('入点须小于出点，且区间不得超出素材时长');stopSequence();player.pause();c.start=start;c.end=end;markDirty();renderTimeline();previewVideo(v,false,start);break;}
 case 'clip-left':case 'clip-right':{stopSequence();player.pause();const next=selected+(b.id==='clip-left'?-1:1);[mix.clips[selected],mix.clips[next]]=[mix.clips[next],mix.clips[selected]];selected=next;markDirty();renderTimeline();break;}
 case 'clip-remove':stopSequence();player.pause();mix.clips.splice(selected,1);selected=Math.min(selected,mix.clips.length-1);markDirty();renderTimeline();break;
 case 'play-mix':if(continuous){player.pause();stopSequence();}else playClip(0);break;
 case 'export-mix':b.disabled=true;try{await saveMix();await api('export',mix);toast('开始导出，可继续查看其他页面');await renderExports();}finally{b.disabled=!mix.clips.length;}break;
 case 'export-srt':{
  b.disabled=true;try{
   const res=await api('export-srt',mix);
   if(!res.count){toast('所选片段未配置台词时间点，暂未导出 SRT');break;}
   const blob=new Blob([res.srt],{type:'text/plain;charset=utf-8'});const href=URL.createObjectURL(blob);
   const a=document.createElement('a');a.href=href;a.download=res.filename||'字幕.srt';document.body.appendChild(a);a.click();a.remove();
   setTimeout(()=>URL.revokeObjectURL(href),1000);toast(`已导出 ${res.count} 条 SRT 字幕：${res.filename}`);
  }finally{b.disabled=!mix.clips.length;}
  break;
 }
 case 'lb-prev':lbIndex=(lbIndex-1+lbList.length)%lbList.length;updateLightbox();break;
 case 'lb-next':lbIndex=(lbIndex+1)%lbList.length;updateLightbox();break;
 case 'lb-zoom':case 'lb-img':{const st=$('#lb-stage'),zm=$('#lb-zoom');if(st&&!$('#lb-img').hidden){st.classList?.toggle?.('zoomed');if(zm)zm.textContent=st.classList?.contains?.('zoomed')?'适应屏幕':'100% 原始尺寸';}break;}
 case 'lb-redraw':copyRedrawInstruction(lbList[lbIndex]);break;
 case 'new-profile':{resetBlankProfile();break;}
 }
 }catch(error){toast(error.message);}});
document.addEventListener('change',e=>{if(e.target.dataset.version){try{adoptVersion(e.target.dataset.version,e.target.value);}catch(error){toast(error.message);}}if(['task-episode','task-status'].includes(e.target.id))renderTasks();if(e.target.id==='asset-scope')renderAssets();if(e.target.id==='regen-profile'||e.target.closest('#regen-items'))regenDescription();if(e.target.id==='profile-select'){const found=(profiles?.profiles||[]).find(p=>p.id===e.target.value);if(found)fillProfile(found);else resetBlankProfile();}});
$('#asset-search')?.addEventListener?.('input',renderAssets);
$('#asset-lightbox')?.addEventListener?.('close',()=>{$('#lb-video')?.pause?.();$('#lb-img')?.removeAttribute?.('src');});
document.addEventListener('keydown',e=>{
 const lb=$('#asset-lightbox');
 if(lb?.open){
  if(e.key==='ArrowLeft'){e.preventDefault();lbIndex=(lbIndex-1+lbList.length)%lbList.length;updateLightbox();return;}
  if(e.key==='ArrowRight'){e.preventDefault();lbIndex=(lbIndex+1)%lbList.length;updateLightbox();return;}
  if(e.key==='z'||e.key==='Z'){$('#lb-zoom')?.click?.();return;}
  return;
 }
 if(e.ctrlKey||e.metaKey||e.altKey)return;
 if(e.target?.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName||''))return;
 if(view==='mix'&&mix.clips[selected]){
  if(e.key==='i'||e.key==='I'){e.preventDefault();try{markClipBoundary('in');}catch(err){toast(err.message);}}
  if(e.key==='o'||e.key==='O'){e.preventDefault();try{markClipBoundary('out');}catch(err){toast(err.message);}}
 }
});
$('#mix-select').addEventListener('change',async e=>{const id=e.target.value;try{if(dirty)await saveMix();if(!id){$('#new-mix').click();return;}mix=structuredClone(mixes.find(m=>m.id===id));dirty=false;selected=-1;stopSequence();player.pause();$('#mix-name').value=mix.name;$('#save-status').textContent='已保存';$('#save-status').style.color='';renderMixOptions();renderTimeline();renderExports();}catch(error){toast(error.message)}});
$('#mix-name').addEventListener('input',()=>{mix.name=$('#mix-name').value;markDirty();});$('#episode-search').addEventListener('input',renderEpisodes);
$('#project-select').addEventListener('change',e=>selectProject(e.target.value).catch(error=>toast(error.message)));
$('#timeline').addEventListener('dragstart',e=>{const b=e.target.closest('[data-clip]');if(b){dragIndex=Number(b.dataset.clip);e.dataTransfer.setData('text/plain',String(dragIndex));e.dataTransfer.effectAllowed='move';}});
$('#timeline').addEventListener('dragover',e=>{if(e.target.closest('[data-clip]'))e.preventDefault();});
$('#timeline').addEventListener('drop',e=>{e.preventDefault();const b=e.target.closest('[data-clip]');if(!b||dragIndex<0)return;stopSequence();player.pause();const to=Number(b.dataset.clip),[clip]=mix.clips.splice(dragIndex,1);mix.clips.splice(to,0,clip);selected=to;dragIndex=-1;markDirty();renderTimeline();});
$('#timeline').addEventListener('dragend',()=>dragIndex=-1);
$('#profile-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter||$('#profile-form button[type="submit"]');if(b)b.disabled=true;try{const p=typeof collectProfile==='function'?collectProfile():{id:profileId,name:$('#profile-name').value,base_url:$('#profile-base').value};profiles=await api('profiles',{profile:p,key:$('#profile-key').value});$('#profile-key').value='';populateProfiles();$('#profile-dialog').close();toast('接口与密钥已保存，重启后自动保留');}catch(error){$('#profile-error').textContent=error.message;}finally{if(b)b.disabled=false;}});
$('#regen-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('#regen-submit');b.disabled=true;try{const ids=$$('#regen-items input:checked').map(i=>i.value);let p=profiles.profiles.find(p=>p.id===$('#regen-profile').value);const key=$('#regen-key').value;if(key){profiles=await api('profiles',{profile:p,key});p=profiles.profiles.find(x=>x.id===profiles.active);$('#regen-key').value='';populateProfiles();}const result=await api('regenerate',{request_ids:ids,profile_id:p.id,nonce:regenNonce,approve_reviewed_selection:true});$('#regen-dialog').close();toast(`已加入优先队列 ${result.request_ids.length} 个请求，将优先使用空闲名额`);await refresh();}catch(error){$('#regen-error').textContent=error.message;}finally{b.disabled=false;}});
window.addEventListener('beforeunload',e=>{if(dirty||[...episodeDrafts.values()].some(d=>d.dirty)){e.preventDefault();e.returnValue='';}});
async function boot(){
 try{
  const params=new URL(location.href).searchParams,requestedView=params.get('view');
  view=['script','mix','assets','tasks'].includes(requestedView)?requestedView:'script';
  const boot=await api('bootstrap');csrf=boot.csrf;profiles=boot.profiles;scopedProject=boot.project||'';
  if(scopedProject&&typeof document!=='undefined'){document.title=scopedProject+' · 制作看板';const picker=$('#project-select')?.closest('.project-picker');if(picker)picker.hidden=true;}
  populateProfiles();const [stateData,mixesData,annData,assetData]=await Promise.all([api('state'),api('mixes'),api('annotations').catch(()=>({videos:{},units:{}})),api('assets').catch(()=>({assets:[]}))]);state=stateData;mixes=mixesData.mixes;annotations=annData||{videos:{},units:{}};assetItems=assetData.assets||[];$('#connection').textContent='记录已连接';$('.dot').style.background='var(--good)';
  let savedSelection={};try{savedSelection=JSON.parse(window.localStorage?.getItem(selectionStorageKey())||'{}');for(const [id,selected] of savedSelection.episodes||[])projectEpisodeSelections.set(id,selected);}catch{}
  if(mixes.length){mix=structuredClone([...mixes].sort((a,b)=>a.updated_at.localeCompare(b.updated_at)).at(-1));eid=mix.episode_id||eid;$('#mix-name').value=mix.name;$('#save-status').textContent='已保存';}
  const explicit=state.episodes.find(e=>e.id===params.get('episode'));
  const preferred=scopedProject||params.get('project')||(explicit&&projectName(explicit))||savedSelection.project||projectName(state.episodes.find(e=>e.id===eid)||state.episodes[0]);
  projectId=scopedProject||(state.episodes.some(e=>projectName(e)===preferred)?preferred:state.episodes[0]?projectName(state.episodes[0]):'');
  const entries=projectEpisodes(),target=entries.find(e=>e.id===explicit?.id)||entries.find(e=>e.id===projectEpisodeSelections.get(projectId))||entries.find(e=>e.id===eid)||entries[0];
  renderEpisodes();renderMixOptions();
  if(target)await selectEpisode(target.id);else{$('#episode-title').textContent='等待原件与制作数据';$('#episode-detail').textContent='在项目文件夹保存制作数据.json后，刷新即可开始审阅。';$('#library-list').innerHTML='<div class="empty">暂无正式剧集，未创建任何视频任务</div>';}
  renderIssues();renderTimeline();switchView(view);$('main').scrollTop=0;setInterval(()=>{if(typeof document==='undefined'||!document.hidden)refresh();},10000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 }catch(error){$('#banner').hidden=false;$('#banner').textContent='看板读取失败：'+error.message+'。请检查本地服务后刷新。';}
}
boot();
