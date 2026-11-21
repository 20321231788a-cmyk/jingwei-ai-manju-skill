// Original-board embedding and parent messages; simulated queue, no upstream calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map(),listeners={};
function node(id){
 if(!nodes.has(id))nodes.set(id,{textContent:'',value:'',innerHTML:'',hidden:false,disabled:false,open:false,style:{},dataset:{},classList:{toggle(){}},lastChild:{textContent:''},scrollTop:0,scrollLeft:0,readyState:1,duration:9,src:'',loads:0,contentWindow:{},addEventListener(){},showModal(){this.open=true},pause(){},load(){this.loads++},removeAttribute(k){this[k]=''},getAttribute(k){return this[k]},play(){return Promise.resolve()}});
 return nodes.get(id);
}
const context=vm.createContext({console,structuredClone,URL,Map,Date,setTimeout,clearTimeout,innerWidth:1500,location:{href:'http://127.0.0.1:8766/',origin:'http://127.0.0.1:8766'},navigator:{},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(type,fn){(listeners[type]??=[]).push(fn)},confirm:()=>true}});
const run=s=>vm.runInContext(s,context);
for(const file of ['editor.js','app.js'])run(fs.readFileSync(path.join(__dirname,'web',file),'utf8').replace(/\nboot\(\);?\s*$/,''));
run(`
 eid='Pabcdef';view='script';
 episode={id:eid,title:'第一集',revision:'v1',units:[{id:eid+'_U01',local_id:'U01',title:'愤怒',duration_s:9},{id:eid+'_U02',local_id:'U02',title:'出场',duration_s:9}],requests:[{request_id:'q1',unit_id:eid+'_U01',ready:false,ready_for_approval:true,model_request_seconds:9},{request_id:'q2',unit_id:eid+'_U02',ready:true,model_request_seconds:9}]};
 state={episodes:[],tasks:[],videos:[{id:'old',unit_id:eid+'_U01',episode_id:eid,request_id:'old-q',mtime:1,seconds:9,url:'/old.mp4'}]};
 renderBoardFrame();
`);
assert.match(node('#script-frame').src,/\/board\/Pabcdef#U01/);
run(`episode.revision='v2';$('#script-frame').src='same-document';renderBoardFrame();`);
assert.equal(node('#script-frame').src,'same-document','polling must not reload the in-place editor');
const onmessage=listeners.message[0];
const message={type:'storyboard-editor',episode_id:'Pabcdef',unit_id:'Pabcdef_U01',action:'dirty',dirty_units:['Pabcdef_U01']};
(async()=>{
 await onmessage({origin:'https://external.example',source:node('#script-frame').contentWindow,data:message});
 assert.equal(run("hasUnsavedUnit('Pabcdef_U01')"),false);
 await onmessage({origin:'http://127.0.0.1:8766',source:{},data:message});
 assert.equal(run("hasUnsavedUnit('Pabcdef_U01')"),false);
 await onmessage({origin:'http://127.0.0.1:8766',source:node('#script-frame').contentWindow,data:message});
 assert.equal(run("canRegenerate(episode.requests[0])"),false);
 run("playUnit(eid+'_U01','old');");
 assert.equal(node('#video-dialog').open,true);
 assert.equal(node('#unit-video').src,'/old.mp4');
 const loads=node('#unit-video').loads;
 run("state.videos.unshift({...state.videos[0],id:'new',mtime:2,url:'/new.mp4'});renderUnitMonitor(selectedUnit());");
 assert.equal(node('#unit-video').src,'/old.mp4');assert.equal(node('#unit-video').loads,loads);
 run("playUnit(eid+'_U01','new');");assert.equal(node('#unit-video').src,'/new.mp4');
 console.log('PASS: original board embedding, stable iframe during polling, trusted message bridge, unsaved submission gate and on-demand historical playback.');
})().catch(error=>{console.error(error);process.exitCode=1});
