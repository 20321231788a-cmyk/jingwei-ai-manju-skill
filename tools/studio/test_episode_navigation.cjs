// Exercise the shipped navigation logic without network, media or paid tasks.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const nodes=new Map();
function node(selector){if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',innerHTML:'',hidden:false,style:{},dataset:{},lastChild:{textContent:''},scrollTop:0,scrollLeft:0,offsetTop:0,offsetLeft:0,readyState:1,duration:20,src:'old',paused:false,addEventListener(){},pause(){this.paused=true},load(){},removeAttribute(k){this[k]=''},getAttribute(k){return this[k]},play(){this.paused=false;return Promise.resolve()}});return nodes.get(selector)}
const context=vm.createContext({console,structuredClone,URL,Map,setTimeout,clearTimeout,innerWidth:1500,location:{href:'http://127.0.0.1:8765/'},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}}});
const script=fs.readFileSync(path.join(__dirname,'web/app.js'),'utf8').replace(/\nboot\(\);?\s*$/,'');
vm.runInContext(script,context);
const run=s=>vm.runInContext(s,context);
run(`
globalThis.pending={};
globalThis.boards={};
for(const id of ['EP010','EP011','EP012','EP045'])boards[id]={id,title:id,units:[],requests:id==='EP045'?[]:[{request_id:id+'-r1',unit_id:id+'_S01',source_request_ids:[id+'_S01_R01']}]};
state={videos:['EP010','EP011','EP012'].map(id=>({id:id+'-video',episode_id:id,unit_id:id+'_S01',request_id:id+'-r1',source_request_ids:[id+'_S01_R01'],seconds:20,adopted_interval:[0,18],url:'/media/'+id}))};
api=async route=>boards[route.split('/')[1]];
renderEpisodes=()=>{};renderEpisode=()=>{};renderTimeline=()=>{};renderMixOptions=()=>{};renderExports=async()=>{};
episode=boards.EP010;eid='EP010';mix={id:'saved10',name:'EP010 · 初剪',episode_id:'EP010',clips:[{video_id:'EP010-video',start:0,end:18}]};
mixes=[structuredClone(mix)];
`);
(async()=>{
 await run(`selectEpisode('EP011')`);
 assert.equal(run('eid'),'EP011');assert.equal(run('mix.episode_id'),'EP011');
 assert.equal(run('mix.clips[0].video_id'),'EP011-video');assert.equal(node('#player').src,'/media/EP011');
 assert.equal(node('#playing-title').textContent,'EP011_S01');
 run(`mix.clips[0].start=2;dirty=true;continuous=true;`);
 await run(`selectEpisode('EP012')`);
 assert.equal(run('continuous'),false);assert.equal(node('#player').paused,true);assert.equal(node('#player').src,'/media/EP012');
 await run(`selectEpisode('EP011')`);
 assert.equal(run('mix.clips[0].start'),2);assert.equal(run('dirty'),true);
 await run(`selectEpisode('EP045')`);
 assert.equal(node('#player').src,'');assert.equal(node('#player-empty').hidden,false);assert.equal(run('mix.clips.length'),0);
 assert.match(node('#playing-title').textContent,/EP045/);
 await run(`selectEpisode('EP010')`);
 assert.equal(run('mix.id'),'saved10');assert.equal(node('#player').src,'/media/EP010');
 run(`api=route=>new Promise(resolve=>pending[route]=resolve);`);
 const older=run(`selectEpisode('EP011')`),newer=run(`selectEpisode('EP012')`);
 run(`pending['episode/EP012'](boards.EP012)`);await newer;
 run(`pending['episode/EP011'](boards.EP011)`);await older;
 assert.equal(run('eid'),'EP012');assert.equal(node('#player').src,'/media/EP012');
 run(`
 api=async route=>boards[route.split('/')[1]];
 state.videos.push({...state.videos.find(v=>v.id==='EP012-video'),id:'history12',request_id:'EP012-old',seconds:15,url:'/media/history12'});
 mix.clips[0].start=2;selected=0;
 adoptVersion('EP012-r1','history12');
 `);
 assert.equal(run('mix.clips[0].video_id'),'history12');
 assert.equal(run('mix.clips[0].start'),2);assert.equal(run('mix.clips[0].end'),15);
 run(`selected=-1;`);
 assert.equal(run('chooseVersion(episode.requests[0]).id'),'history12');
 run(`playClip(0);stopSequence();`);
 assert.equal(node('#player').src,'/media/history12');
 await run(`selectEpisode('EP011')`);await run(`selectEpisode('EP012')`);
 assert.equal(run('chooseVersion(episode.requests[0]).id'),'history12');
 // A new download and serialization/reload must not replace the adopted version.
 run(`state.videos.unshift({...state.videos.find(v=>v.id==='EP012-video'),id:'new-download'});mix=JSON.parse(JSON.stringify(mix));selected=-1;`);
 assert.equal(run('chooseVersion(episode.requests[0]).id'),'history12');
 // Two 20-second parts of one shot remain independently selectable.
 run(`
 episode.requests=[{request_id:'part-a',unit_id:'EP012_S03',source_request_ids:['a']},{request_id:'part-b',unit_id:'EP012_S03',source_request_ids:['b']}];
 for(const [id,source] of [['a-now','a'],['a-old','a'],['b-now','b'],['b-old','b']])state.videos.push({id,episode_id:'EP012',unit_id:'EP012_S03',request_id:id,source_request_ids:[source],seconds:20,url:'/media/'+id});
 mix.clips=[{video_id:'a-now',start:0,end:20},{video_id:'b-now',start:0,end:20},{video_id:'b-now',start:4,end:9}];
 selected=2;adoptVersion('part-b','b-old');
 `);
 assert.deepEqual(JSON.parse(run('JSON.stringify(mix.clips.map(c=>c.video_id))')),['a-now','b-now','b-old']);
 assert.equal(run('mix.clips[2].start'),4);assert.equal(run('mix.clips[2].end'),9);
 run(`mix.clips=[];selected=-1;adoptVersion('part-a','a-old');`);
 assert.equal(run('mix.clips[0].video_id'),'a-old');
 console.log('PASS: historical adoption persists across shot/episode changes, playback, downloads and saved reload; trim clamping and independent multi-part/duplicate clips.');
 console.log('PASS: episode preview/timeline switch, playback stops, draft restoration, empty episode, saved mix restoration, rapid navigation race.');
})().catch(e=>{console.error(e);process.exitCode=1});
