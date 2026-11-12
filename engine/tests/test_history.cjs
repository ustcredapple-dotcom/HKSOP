'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const engine=path.resolve(__dirname,'..'),root=path.dirname(engine),tmp=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'hksop-history-test-')),mapping=JSON.parse(fs.readFileSync(engine+'/runtime-map.json'));process.on('exit',()=>fs.rmSync(tmp,{recursive:true,force:true}));
for(const profile of ['web','editor']){
 for(const [target,entry]of Object.entries(mapping[profile]))if(target.endsWith('.js')){const out=path.join(tmp,profile,target);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(root,entry.source),out)}
 const codec=require(`${tmp}/${profile}/static/project-file.js`);
 const catalog={version:'C',kits:[{id:'mirror',name:'new',revision:'2'},{id:'mirror-old',name:'old',revision:'1',lifecycle:{state:'historical',canCreate:false}}],components:[],registeredBoards:[],historyResolution:[{catalogVersion:'A',kind:'kits',originalId:'mirror',recordId:'mirror-old',revision:'1'}]};
 const input={catalogVersion:'A',layout:{board:{widthMm:100,heightMm:100,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.5,holeType:'M6_through',mountingHoles:[]},instances:[{id:'a',kitId:'mirror',xMm:25,yMm:25,rotationDeg:0}]},catalogReferenced:[{id:'mirror',name:'old',revision:'1'}]};
 const before=JSON.stringify(input);let resolved=codec.resolveHistoricalReferences(input,catalog);assert.equal(resolved.layout.instances[0].kitId,'mirror-old');assert.equal(resolved.catalogReferenced[0].id,'mirror-old');assert.equal(JSON.stringify(input),before);
 const parsed=codec.parse(input,{catalog,validateBoard:b=>b}).project;assert.equal(parsed.layout.instances[0].kitId,'mirror-old');assert.equal(codec.parse(parsed,{catalog,validateBoard:b=>b}).project.layout.instances[0].kitId,'mirror-old');
 const posts=structuredClone(catalog);posts.components=[{id:'post25'},{id:'post37'},{id:'old25',lifecycle:{state:'historical',originalId:'post25'}},{id:'old37',lifecycle:{state:'historical',originalId:'post37'}}];posts.kits[1].components=[{componentId:'old25',quantity:1}];posts.historyResolution.push({catalogVersion:'A',kind:'components',originalId:'post25',recordId:'old25'},{catalogVersion:'A',kind:'components',originalId:'post37',recordId:'old37'});const substituted=structuredClone(input);substituted.layout.instances[0].universalPostSelection={post25:'post37'};assert.deepEqual(codec.resolveHistoricalReferences(substituted,posts).layout.instances[0].universalPostSelection,{old25:'old37'});
 const unknown=structuredClone(input);unknown.catalogVersion='unknown';delete unknown.catalogReferenced;assert.throws(()=>codec.resolveHistoricalReferences(unknown,catalog),e=>e.code==='history_version_ambiguous');unknown.catalogVersion='C';assert.equal(codec.resolveHistoricalReferences(unknown,catalog).layout.instances[0].kitId,'mirror');
 const c={window:{},console,crypto:require('node:crypto').webcrypto};c.globalThis=c.window;vm.createContext(c);vm.runInContext(fs.readFileSync(`${engine}/layout/javascript/web/layout.js`,'utf8'),c);
 const P=c.window.BreadboardEditor.prototype,e=Object.create(P);e.kits=new Map(catalog.kits.map(k=>[k.id,k]));e.instances=[];e.notify=()=>{};e.board={pitchMm:12.5};e.historySnapshot=()=>({});e.commit=()=>{};e.setSelection=()=>{};e.freeSpot=()=>({xMm:25,yMm:25});
 for(const method of ['add','beginPlace']){e[method]('mirror-old');assert.equal(e.instances.length,0);}
 assert.equal(e.pastePacket({instances:[{id:'x',kitId:'mirror-old'}]}),null);
 for(const wrapper of [`${profile}/global-height.js`,'web/periscope-properties.js'])vm.runInContext(fs.readFileSync(`${engine}/layout/javascript/${wrapper}`,'utf8'),c);
 e.add('mirror-old');assert.equal(e.instances.length,0);e.add('mirror');assert.equal(e.instances.length,1);
 // Exercise the actual registered drop callback, not a second copy of its logic.
 const nodes=new Map(),node=()=>({handlers:{},addEventListener(type,fn){this.handlers[type]=fn},classList:{remove(){},add(){}},focus(){}});
 c.document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},addEventListener(){}};
 e.svg=node();e.viewport=node();e.world=()=>({xMm:75,yMm:75});e.snap=(xMm,yMm)=>({xMm,yMm});e.bind();
 const drop=id=>e.viewport.handlers.drop({preventDefault(){},dataTransfer:{getData(type){return type==='application/x-zzlab-kit'?id:''}}});drop('mirror-old');assert.equal(e.instances.length,1);drop('mirror');assert.equal(e.instances.length,2);
 const imageKit={id:'mirror-old',name:'old',lifecycle:{state:'historical',canCreate:false},layout:{topViewUrl:'./topviews/old.svg',widthMm:40,heightMm:40,anchorXMm:20,anchorYMm:20}};e.kits.set('mirror-old',imageKit);assert.equal(e.kitLayout({kitId:'mirror-old'}).actual,true);
 console.log(profile+': historical parse/save, version ambiguity, render geometry, direct add/begin/paste/wrappers/drop and current add/drop passed');
}
