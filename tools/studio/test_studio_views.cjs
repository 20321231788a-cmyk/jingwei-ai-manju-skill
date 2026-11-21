// Run the shipped rendering and refresh logic against simulated queue snapshots.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const nodes=new Map();
function node(selector){
 if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',innerHTML:'',hidden:false,disabled:false,style:{},dataset:{},lastChild:{textContent:''},scrollTop:0,scrollLeft:0,offsetTop:0,offsetLeft:0,readyState:1,duration:20,src:'',addEventListener(){},pause(){},load(){},removeAttribute(k){this[k]=''},getAttribute(k){return this[k]},play(){return Promise.resolve()}});
 return nodes.get(selector);
}
const context=vm.createContext({console,structuredClone,URL,Map,setTimeout,clearTimeout,innerWidth:1500,location:{href:'http://127.0.0.1:8766/'},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'web/app.js'),'utf8').replace(/\nboot\(\);?\s*$/,''),context);
const run=s=>vm.runInContext(s,context);
run(`
 eid='EP001';
 episode={id:eid,title:'测试',revision:'v1',units:[{id:'EP001_U01',title:'第一镜'},{id:'EP001_U02',title:'第二镜'}],requests:[{request_id:'plan-v2',unit_id:'EP001_U01',model_request_seconds:12,ready:true,source_request_ids:[]}]};
 mix={name:'测试初剪',episode_id:eid,clips:[]};
 globalThis.older={request_id:'old-done',plan_request_id:'plan-v2',episode_id:eid,unit_id:'EP001_U01',seconds:12,state:'done',downloaded:true,job_id:'old-job',source:'agent',upstream:'原接口'};
 globalThis.latest={...older,request_id:'new-attempt',source:'studio',state:'queued',downloaded:false,job_id:null};
 state={episodes:[{id:eid,title:'测试',revision:'v1',total:1,downloaded:0,shots:2}],tasks:[latest],history:[older],regenerations:[latest],videos:[{id:'old-video',episode_id:eid,unit_id:'EP001_U01',request_id:'old-done',seconds:12,url:'/old.mp4'}],counts:{queued:1},total:1,downloaded:0,updated_at:'2026-11-04T12:00:00+08:00'};
 $('#task-episode').value='all';$('#task-status').value='all';
 renderTasks();renderLibrary();
`);
assert.match(node('#task-rows').innerHTML,/new-attempt/);
assert.doesNotMatch(node('#task-rows').innerHTML,/old-done/);
assert.match(node('#library-list').innerHTML,/待提交/);
assert.match(node('#library-list').innerHTML,/历史版本/);
assert.equal(node('#done-count').textContent,'0 / 1');
run(`taskSource='history';renderTasks();`);
assert.match(node('#task-rows').innerHTML,/old-done/);
assert.doesNotMatch(node('#task-rows').innerHTML,/new-attempt/);
// Same state, different latest attempt must still invalidate the library render.
run(`state.tasks=[{...latest,request_id:'old-done',downloaded:false}];renderLibrary();`);
assert.match(node('#library-list').innerHTML,/最新提交/);
run(`state.tasks=[latest];renderLibrary();`);
assert.doesNotMatch(node('#library-list').innerHTML,/最新提交/);
run(`state.tasks[0]={...latest,state:'running',job_id:'new-job'};state.counts={running:1};taskSource='current';renderTasks();renderLibrary();`);
assert.match(node('#task-rows').innerHTML,/new-job/);
assert.match(node('#library-list').innerHTML,/生成中/);
run(`state.counts={waiting_key:1,capacity_wait:1,retry_wait:1,sending:1,submitted:1};state.tasks=['waiting_key','capacity_wait','retry_wait','sending','submitted'].map((state,i)=>({...latest,request_id:'counter-'+i,state}));renderTasks();`);
assert.equal(node('#waiting-count').textContent,3);
assert.equal(node('#running-count').textContent,2);
run(`
 state.tasks=[latest];
 state.videos.unshift({...state.videos[0],id:'new-video',request_id:'new-attempt',url:'/new.mp4'});
 state.tasks[0]={...latest,state:'done',downloaded:true};
`);
assert.equal(run('chooseVersion(episode.requests[0]).id'),'new-video');
run(`adoptVersion('plan-v2','old-video');renderLibrary();`);
assert.equal(run('mix.clips[0].video_id'),'old-video');
assert.match(node('#library-list').innerHTML,/<option value="old-video" selected/);
// Without a current plan, versions of each shot still share one selector.
run(`
 episode.requests=[];mix.clips=[];selected=-1;
 state.videos.push({...state.videos[1],id:'second-shot',unit_id:'EP001_U02',request_id:'second',url:'/second.mp4'});
 renderLibrary();
`);
assert.equal((node('#library-list').innerHTML.match(/class="source-card"/g)||[]).length,2);
assert.equal((node('#library-list').innerHTML.match(/data-version=/g)||[]).length,2);
assert.equal(run('episodePreviewVideos().length'),2);
run(`adoptVersion('new-attempt','old-video');`);
assert.equal(run('mix.clips[0].video_id'),'old-video');
assert.equal(node('#player').src,'/old.mp4');
run(`renderLibrary();`);
assert.match(node('#library-list').innerHTML,/<option value="old-video" selected/);

(async()=>{
 // A submit-triggered refresh arriving during an older poll must run again.
 run(`
  episode.requests=[{request_id:'plan-v2',unit_id:'EP001_U01',model_request_seconds:12,ready:true}];
  view='tasks';taskSource='current';
  globalThis.fresh=structuredClone(state);fresh.tasks=[{...latest,state:'running',job_id:'fresh-job'}];fresh.counts={running:1};
  globalThis.polls=0;globalThis.resolveOld=null;
  api=route=>{
   if(route==='state'){polls++;return polls===1?new Promise(resolve=>resolveOld=resolve):Promise.resolve(fresh);}
   if(route==='exports')return Promise.resolve([]);
   throw new Error('unexpected route '+route);
  };
 `);
 const pending=run('refresh()');
 await run('refresh()');
 run('resolveOld(state)');
 await pending;
 assert.equal(run('polls'),2);
 assert.equal(run('state.tasks[0].job_id'),'fresh-job');
 assert.match(node('#task-rows').innerHTML,/fresh-job/);
 assert.match(node('#library-list').innerHTML,/生成中/);
 console.log('PASS: latest versus history, live state and counters, refresh overlap, grouped history selectors and adopted versions.');
})().catch(e=>{console.error(e);process.exitCode=1});
