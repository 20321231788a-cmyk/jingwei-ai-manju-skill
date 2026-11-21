// Regression: identical episode codes in different dramas must never share UI scope.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map(),storage=new Map(),location={href:'http://127.0.0.1:8766/?view=tasks'};
function node(selector){
 if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',innerHTML:'',hidden:false,style:{},dataset:{},lastChild:{textContent:''},scrollTop:0,scrollLeft:0,offsetTop:0,offsetLeft:0,readyState:1,duration:30,src:'',addEventListener(){},pause(){},load(){},removeAttribute(k){this[k]=''},getAttribute(k){return this[k]},play(){return Promise.resolve()}});
 return nodes.get(selector);
}
const context=vm.createContext({console,structuredClone,URL,Map,Set,setTimeout,clearTimeout,innerWidth:1500,location,history:{replaceState(_a,_b,url){location.href=String(url)}},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){},localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'web/app.js'),'utf8').replace(/\nboot\(\);?\s*$/,''),context);
const run=s=>vm.runInContext(s,context);
run(`
globalThis.boards={};
const names={A:'子夜典当行',B:'我在都市做柳家出马仙'};
const definitions=[['A01','A','EP01','契成'],['ASP','A','SP002','提线转场'],['B01','B','EP01','第一集'],['BOP','B','OP001','血月临城']];
state={episodes:definitions.map(([id,p,code,name])=>({id,title:names[p]+' · '+code+' · '+name,revision:'v1',shots:1,total:1,downloaded:0})),tasks:[],history:[],videos:[],updated_at:'2026-11-11T13:00:00+08:00',counts:{done:999},total:999,downloaded:999,issues:['我在都市做柳家出马仙/分镜脚本/制作数据.json: 缺少 source']};
for(const [id] of definitions){boards[id]={id,title:state.episodes.find(e=>e.id===id).title,units:[],requests:[]};state.tasks.push({request_id:id+'-new',episode_id:id,unit_id:id+'_G01',seconds:30,state:id==='A01'?'running':id==='B01'?'done':'draft',downloaded:id==='B01',upstream:'Wan3'});}
state.history=state.tasks.map(t=>({...t,request_id:t.episode_id+'-old'}));
state.videos=[{id:'A-video',episode_id:'A01',unit_id:'A01_G01',request_id:'A01-new',seconds:30,url:'/media/A-video'}];
mixes=[{id:'mixA',episode_id:'A01',name:'初剪',clips:[{video_id:'A-video',start:1,end:29}]}];
api=async route=>boards[route.split('/')[1]];renderExports=async()=>{};
$('#task-episode').value='all';$('#task-status').value='all';view='tasks';
`);
(async()=>{
 await run(`selectEpisode('A01')`);
 assert.equal(run('projectId'),'子夜典当行');
 assert.equal(node('#project-count').textContent,'2 部');
 assert.match(node('#episodes').innerHTML,/契成/);assert.match(node('#episodes').innerHTML,/SP002/);
 assert.doesNotMatch(node('#episodes').innerHTML,/血月临城|B01/);
 assert.equal(node('#script-count').textContent,2);assert.equal(node('#task-count').textContent,2);
 assert.equal(node('#done-count').textContent,'0 / 2');assert.equal(node('#running-count').textContent,1);
 assert.doesNotMatch(node('#task-rows').innerHTML,/B01-new|BOP-new/);assert.equal(node('#banner').hidden,true);
 run(`taskSource='history';renderTasks();`);
 assert.match(node('#task-rows').innerHTML,/A01-old/);assert.doesNotMatch(node('#task-rows').innerHTML,/B01-old/);
 run(`taskSource='current';mix.clips[0].start=3;dirty=true;$('#episode-search').value='契成';`);
 await run(`selectProject('我在都市做柳家出马仙')`);
 assert.equal(run('eid'),'B01');assert.equal(run('mix.clips.length'),0);assert.equal(node('#player').src,'');
 assert.equal(node('#episode-search').value,'');assert.match(node('#episodes').innerHTML,/OP001/);
 assert.doesNotMatch(node('#episodes').innerHTML,/契成|SP002/);
 assert.equal(node('#done-count').textContent,'1 / 2');assert.equal(node('#running-count').textContent,0);
 assert.doesNotMatch(node('#task-rows').innerHTML,/A01-new|ASP-new/);assert.equal(node('#banner').hidden,false);
 await run(`selectEpisode('BOP')`);
 run(`$('#task-episode').value='current';renderTasks();`);
 assert.equal(node('#done-count').textContent,'0 / 1');assert.doesNotMatch(node('#task-rows').innerHTML,/B01-new/);
 await run(`selectProject('子夜典当行')`);
 assert.equal(run('eid'),'A01');assert.equal(run('mix.clips[0].start'),3);assert.equal(run('dirty'),true);
 assert.equal(node('#player').src,'/media/A-video');
 await run(`selectProject('我在都市做柳家出马仙')`);
 assert.equal(run('eid'),'BOP');assert.equal(new URL(location.href).searchParams.get('episode'),'BOP');
 assert.equal(JSON.parse(storage.get('studio.selection')).project,'我在都市做柳家出马仙');
 // An unsaved script blocks the entire project switch; selector and data remain aligned.
 run(`episode.units=[{id:'dirty-unit'}];globalThis.hasUnsavedUnit=()=>true;`);
 await run(`selectProject('子夜典当行')`);
 assert.equal(run('eid'),'BOP');assert.equal(node('#project-select').value,'我在都市做柳家出马仙');
 run(`hasUnsavedUnit=()=>false;globalThis.pending={};api=route=>new Promise(resolve=>pending[route]=resolve);`);
 const slow=run(`selectProject('子夜典当行')`),fast=run(`selectEpisode('B01')`);
 run(`pending['episode/B01'](boards.B01)`);await fast;
 run(`pending['episode/A01'](boards.A01)`);await slow;
 assert.equal(run('eid'),'B01');assert.equal(run('projectId'),'我在都市做柳家出马仙');
 assert.doesNotMatch(node('#task-rows').innerHTML,/A01-new/);
 console.log('PASS: project-scoped episodes, OP codes, task/history counts, duplicate EP01, empty video reset, per-project drafts/selection, dirty guard, URL persistence, and racing switches.');
})().catch(error=>{console.error(error);process.exitCode=1});
