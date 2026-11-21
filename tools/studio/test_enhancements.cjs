// Regression: P0+P1 UI features (starred priority, mark-in/out, cost estimate, retry-failed, updated model hint).
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map();
function node(selector){
 if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',innerHTML:'',hidden:false,disabled:false,open:false,style:{},dataset:{},lastChild:{textContent:''},scrollTop:0,scrollLeft:0,offsetTop:0,offsetLeft:0,readyState:1,duration:30,currentTime:0,src:'',addEventListener(){},pause(){},load(){},showModal(){this.open=true},removeAttribute(k){this[k]=''},getAttribute(k){return this[k]},play(){return Promise.resolve()},classList:{toggle(){},contains(){return false},add(){},remove(){}}});
 return nodes.get(selector);
}
const context=vm.createContext({console,structuredClone,URL,Map,Set,crypto:{randomUUID:()=>'uuid-1'},setTimeout,clearTimeout,innerWidth:1500,location:{href:'http://127.0.0.1:8766/'},document:{querySelector:node,querySelectorAll:s=>s==='#regen-items input:checked'?[{value:'q1'},{value:'q2'}]:[],addEventListener(){}},window:{addEventListener(){}}});
for(const file of ['editor.js','app.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'web',file),'utf8').replace(/\nboot\(\);?\s*$/,''),context);
const run=s=>vm.runInContext(s,context);

run(`
 eid='EP001';
 projectId='测试剧';
 profiles={active:'wan',profiles:[{id:'wan',name:'Wan3 1080P',protocol:'wan-portal-v1',base_url:'https://wan.coolhs.com',jobs_path:'/api/portal/jobs',preset_map:{reference:'wan3'},price_per_second:0.4}]};
 episode={
  id:eid,title:'测试剧 · EP001 · 第一集',revision:'v1',
  units:[{id:'EP001_W01',local_id:'W01',title:'拍桌',duration_s:30},{id:'EP001_W02',local_id:'W02',title:'反杀',duration_s:30}],
  requests:[
   {request_id:'q1',unit_id:'EP001_W01',model_request_seconds:30,requested_model:'wan3',ready:true,preset:'wan3'},
   {request_id:'q2',unit_id:'EP001_W02',model_request_seconds:30,requested_model:'wan3',ready:true,preset:'wan3'}
  ]
 };
 state={
  episodes:[{id:eid,title:'测试剧 · EP001 · 第一集',revision:'v1',total:2,downloaded:1,shots:2}],
  tasks:[
   {request_id:'r1',plan_request_id:'q1',episode_id:eid,unit_id:'EP001_W01',seconds:30,state:'done',downloaded:true,upstream:'Wan3 1080P',job_id:'j1'},
   {request_id:'r2',plan_request_id:'q2',episode_id:eid,unit_id:'EP001_W02',seconds:30,state:'failed',downloaded:false,upstream:'Wan3 1080P',job_id:'j2'}
  ],
  history:[],
  videos:[
   {id:'v-new',episode_id:eid,unit_id:'EP001_W01',request_id:'r1',seconds:30,url:'/new.mp4',mtime:20},
   {id:'v-star',episode_id:eid,unit_id:'EP001_W01',request_id:'r1-old',seconds:30,url:'/star.mp4',mtime:10}
  ],
  updated_at:'2026-11-21T13:30:00+08:00'
 };
 annotations={videos:{'v-star':{tag:'star',note:'表情最好'}},units:{}};
`);

// 1. Starred video wins automatically when mix.clips hasn't locked another version.
assert.equal(run('chooseVersion(episode.requests[0]).id'),'v-star');

// 2. markClipBoundary('in'/'out') captures player.currentTime safely.
run(`
 mix={name:'初剪',episode_id:eid,clips:[{video_id:'v-star',start:0,end:30}]};
 selected=0;
 $('#player').currentTime=4.26;
 markClipBoundary('in');
 $('#player').currentTime=19.84;
 markClipBoundary('out');
`);
assert.equal(run('mix.clips[0].start'),4.3);
assert.equal(run('mix.clips[0].end'),19.8);
assert.equal(run('dirty'),true);

// 3. renderTasks computes shot attempts/cost and exposes one-click retry for failed jobs.
run(`$('#task-episode').value='all';$('#task-status').value='all';renderTasks();`);
assert.equal(node('#cost-count').textContent,'¥24.0');
assert.match(node('#cost-meta').textContent,/60秒/);
assert.equal(node('#retry-failed').hidden,false);
assert.match(node('#retry-failed').textContent,/一键重提失败镜 \(1\)/);
assert.deepEqual(JSON.parse(run('JSON.stringify(retryTarget.ids)')),['q2']);

// 4. regenDescription shows estimated price and current model wording (no stale 12-15s H3 text).
run(`$('#regen-profile').value='wan';regenDescription();`);
assert.match(node('#regen-total').textContent,/预估费用 ¥24\.00/);
assert.match(node('#regen-hint').textContent,/wan3 30秒/);
assert.doesNotMatch(node('#regen-hint').textContent,/常规12–15秒/);

// 5. board-editor.js initializes cleanly even after episode-board.html wraps <small> in .shot-head-bar.
{
 const smallEl={replaceChildren(...args){this._children=args;}};
 const h2El={after(){},contentEditable:'',setAttribute(){},classList:{add(){}},dataset:{}};
 const chineseSection={replaceChildren(){},append(){},querySelector:()=>null,querySelectorAll:()=>[]};
 const detailsEl={querySelector:()=>({textContent:''})};
 const stubEl=()=>({contentEditable:'',setAttribute(){},addEventListener(){},classList:{add(){},toggle(){}},dataset:{},textContent:'',disabled:false,style:{},append(){},prepend(){},after(){},removeAttribute(){},querySelector:()=>({textContent:''}),insertAdjacentElement(){},remove(){}});
 const articleEl={
  id:'W01',style:{},
  querySelector(sel){
   if(sel==='h2')return h2El;
   if(sel.includes('.shot-head-bar'))return smallEl;
   if(sel===':scope > small')return null; // Simulate wrapped <small> inside .shot-head-bar!
   if(sel==='.chinese-shots')return chineseSection;
   if(sel===':scope > details')return detailsEl;
   if(sel==='.board-dialogue')return stubEl();
   if(sel.startsWith('[data-board-action')||sel==='.board-edit-status')return stubEl();
   return null;
  },
  querySelectorAll(){return [];}
 };
 const navTools={prepend(){}};
 const boardCtx=vm.createContext({
  console,structuredClone,URL,Map,Set,fetch:async()=>({ok:true,json:async()=>({csrf:'t',units:{}})}),
  navigator:{clipboard:{writeText:async()=>{}}},
  document:{
   documentElement:{classList:{toggle(){}}},
   getElementById:id=>id==='W01'?articleEl:null,
   createElement:()=>stubEl(),
   createTextNode:t=>({textContent:t}),
   querySelector:sel=>sel==='#board-editor-data'?{textContent:JSON.stringify({id:'EP1',title:'测试',current_data:'d.json',units:[{id:'EP1_W01',local_id:'W01',model:'wan3',duration_s:30,edit_revision:'r1',editable_values:{title:'拍桌',duration_s:30,framing:'近景',directing_summary:'概述',scene:'公园',action:'拍桌',camera:'俯拍',sound:'声',continuity:'接',chinese_description:'中文',dialogue:['甲：hi']}}],requests:[{unit_id:'EP1_W01',ready:true}]})}:sel==='.board-nav-tools'?navTools:null,
   querySelectorAll:()=>[],
   addEventListener(){}
  },
  location:{origin:'http://127.0.0.1:8766',hash:'#W01'},
  parent:{postMessage(){}},
  addEventListener(){},setInterval(){}
 });
 boardCtx.window=boardCtx;
 vm.runInContext(fs.readFileSync(path.join(__dirname,'web','board-editor.js'),'utf8'),boardCtx);
 assert.ok(Array.isArray(smallEl._children)&&smallEl._children.length>0,'small duration/framing initialized inside .shot-head-bar');
 assert.equal(h2El.contentEditable,'plaintext-only');
}

// 6. Real upstream config UI: no #profile-protocol, has delete & fetch-models controls, works with empty profile list.
{
 const htmlText=fs.readFileSync(path.join(__dirname,'web','index.html'),'utf8');
 assert.doesNotMatch(htmlText,/id="profile-protocol"/,'接口协议 select must be removed');
 assert.match(htmlText,/id="delete-profile"/,'delete button must exist');
 assert.match(htmlText,/id="fetch-models"/,'fetch-models button must exist');
 assert.match(htmlText,/id="profile-resolution"/,'resolution select must exist');
 assert.match(htmlText,/id="profile-key"/,'key input must exist');
 assert.match(htmlText,/id="script-submit-unit"[^>]*>提交本分镜生成</,'script unit submit button must exist');
 assert.match(htmlText,/id="script-submit-episode"[^>]*>提交本集生成</,'script episode submit button must exist');

 run(`
  profiles={active:'',profiles:[]};
  populateProfiles();
  fillProfile(null);
 `);
 assert.equal(node('#upstream-label').textContent,'未配置');
 assert.equal(node('#delete-profile').disabled,true);

 run(`
  $('#profile-name').value='新网关';
  $('#profile-base').value='https://api.test-relay.example/v1/';
  $('#profile-resolution').value='720p';
  $('#profile-key').value='sk-my-key';
  api=async(route,body)=>{
   if(route==='profiles/models')return {ok:true,models:[{id:'wan3-pro',label:'wan3-pro',enabled:true},{id:'seedance-2.0',label:'seedance-2.0',enabled:true}],message:'已从上游获取 2 个可用模型。'};
   if(route==='profiles/delete')return {active:'',profiles:[]};
   return {};
  };
 `);
 (async()=>{
  await run('fetchProfileModels()');
  assert.equal(node('#profile-model-select').hidden,false);
  assert.match(node('#profile-model-select').innerHTML,/wan3-pro/);
  const collected=JSON.parse(run('JSON.stringify(collectProfile())'));
  assert.equal(collected.protocol,undefined,'new base_url lets backend infer real protocol');
  assert.equal(collected.base_url,'https://api.test-relay.example/v1');
  assert.equal(collected.video_resolution,'720p');
  assert.deepEqual(collected.available_models,['wan3-pro','seedance-2.0']);
  run(`profiles={active:'p-old',profiles:[{id:'p-old',name:'待删',base_url:'https://x.example',protocol:'openai-video-v1'}]};profileId='p-old';`);
  await run('deleteCurrentProfile()');
  assert.deepEqual(JSON.parse(run('JSON.stringify(profiles.profiles)')),[]);

  // Verify script toolbar unit & episode submit buttons
  run(`
   episode={
    id:eid,title:'测试剧 · EP001 · 第一集',revision:'v1',
    units:[{id:'EP001_W01',local_id:'W01',title:'拍桌',duration_s:30},{id:'EP001_W02',local_id:'W02',title:'反杀',duration_s:30}],
    requests:[
     {request_id:'q1',unit_id:'EP001_W01',model_request_seconds:30,requested_model:'wan3',ready:true,preset:'wan3'},
     {request_id:'q2',unit_id:'EP001_W02',model_request_seconds:30,requested_model:'wan3',ready:true,preset:'wan3'}
    ]
   };
   unitSelections.set(eid,'EP001_W02');
   updateScriptSubmitButtons();
   globalThis._openedRegen=null;
   openRegen=async ids=>{globalThis._openedRegen=ids;};
   api=async route=>{
    if(route==='episode/'+eid)return episode;
    return {};
   };
  `);
  assert.equal(node('#script-submit-unit').disabled,false);
  assert.equal(node('#script-submit-episode').disabled,false);
  await run('submitActiveScriptUnit()');
  assert.deepEqual(JSON.parse(run('JSON.stringify(globalThis._openedRegen)')),['q2']);
  await run('submitActiveScriptEpisode()');
  assert.deepEqual(JSON.parse(run('JSON.stringify(globalThis._openedRegen)')),['q1','q2']);

  console.log('PASS: P0+P1 starred selection, mark-in/out trim, cost estimate, retry-failed targeting, model hint, real upstream config UI, and script submit buttons.');
 })().catch(err=>{console.error(err);process.exitCode=1;});
}
