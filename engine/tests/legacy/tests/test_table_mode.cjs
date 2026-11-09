'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),clone=x=>JSON.parse(JSON.stringify(x)),catalog=require('../catalog.json');
const codec=require('../static/project-file.js'),shared=require('../static/shared-project.js');
const harness={require,__dirname:root,console};vm.createContext(harness);
const perf=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');
vm.runInContext(perf.slice(0,perf.indexOf('{\n  const f=fixture(),e=f.editor'))+'\nglobalThis.makeEnvironment=environment;',harness);
const source=['layout.js','stacked-boards.js','elevation.js','laser-adapter.js','table-mode.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n');
const board=(width=625,height=625,pitch=25)=>({widthMm:width,heightMm:height,pitchMm:pitch,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]});
function editor(saved){const env=harness.makeEnvironment(source),proto=env.document.getElementById('board-svg').constructor.prototype;proto.insertBefore=function(node,before){node.parentNode=this;const index=this.children.indexOf(before);this.children.splice(index<0?this.children.length:index,0,node);return node};proto.removeAttribute=function(key){delete this.attributes[key]};const e=new env.Editor({catalog:clone(catalog),saved,notify(){}});if(saved?.subBoards)e.loadLayout(saved);return{...env,e}}
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name)}
const instance=(id='part',extra={})=>({id,kitId:'pbs-fixed',xMm:100.1,yMm:100.1,rotationDeg:0,...extra});
test('root table is optional, undoable and never moves components',()=>{
  const {e}=editor({board:board(),instances:[instance()]}),before=clone(e.snapshot());
  assert.equal(e.validation().valid,false);assert.ok(e.validation().issues.some(i=>i.code==='mounting_mismatch'));
  e.setBaseMode('table');assert.equal(e.snapshot().baseMode,'table');assert.deepEqual(clone(e.snapshot().instances),before.instances);assert.equal(e.validation().valid,true);
  e.undo();assert.equal(e.snapshot().baseMode,undefined);assert.equal(e.validation().valid,false);e.redo();assert.equal(e.snapshot().baseMode,'table');assert.equal(e.validation().valid,true);
  e.boardFormDirty=true;assert.equal(e.setBaseMode('breadboard'),false);assert.equal(e.baseMode,'table');
});
test('table permits unfastened small boards while preserving their internal alignment checks',()=>{
  const l={baseMode:'table',board:board(),subBoards:[{id:'small',name:'Small',board:board(200,150,12.5),xMm:201.2,yMm:201.2,rotationDeg:0}],instances:[instance('child',{boardId:'small',xMm:75,yMm:75})]};
  const {e}=editor(l);assert.equal(e.validation().valid,true,JSON.stringify(e.validation().issues));e.loadLayout(l,'small');assert.equal(e.baseMode,'table');assert.equal(e.snapshot().baseMode,'table');assert.equal(e.validation().valid,true);
  e.instances[0].xMm+=1;assert.ok(e.validation().issues.some(i=>i.code==='mounting_mismatch'&&i.boardId==='small'));
  e.instances[0].xMm-=1;e.setBaseMode('breadboard');assert.ok(e.validation().issues.some(i=>i.code==='sub_board_unfastened'));
});
test('table retains real collision and boundary errors',()=>{
  const {e}=editor({baseMode:'table',board:board(),instances:[instance('a'),instance('b')]});
  assert.ok(e.validation().issues.some(i=>i.code==='collision'));
  e.instances=[instance('a',{xMm:0,yMm:0})];assert.ok(e.validation().issues.some(i=>i.code==='out_of_bounds'));
});
test('project roundtrip preserves table mode and rejects malformed mode',()=>{
  const project=clone(require('../qa/optical-rendering-stacked.zzoptics.json'));project.layout.baseMode='table';
  const options={catalog,validateBoard:b=>b},encoded=codec.create(project,options),loaded=codec.parse(JSON.stringify(encoded),options).project;
  assert.equal(loaded.layout.baseMode,'table');const part=shared.extractBoard(loaded,'qa-small-module',options);assert.equal(part.layout.baseMode,undefined);assert.equal(part.layout.board.widthMm,350);
  project.layout.baseMode='unknown';assert.throws(()=>codec.create(project,options));delete project.layout.baseMode;assert.equal(codec.create(project,options).layout.baseMode,undefined);
});
test('mounting a shared small board on a table keeps only the root reference flag',()=>{
  const project=clone(require('../qa/optical-rendering-stacked.zzoptics.json')),options={catalog,validateBoard:b=>b,newId:kind=>kind+'-new'};
  const small=shared.extractBoard(project,'qa-small-module',options);project.layout.baseMode='table';
  const result=shared.mountOnBoard(project,small,{...options,newId:(()=>{let n=0;return kind=>kind+'-'+(++n)})(),platePosition:{xMm:500,yMm:400}});
  assert.equal(result.project.layout.baseMode,'table');assert.equal(result.project.layout.subBoards.at(-1).board.baseMode,undefined);
  assert.equal(shared.subset(result.project,null,options).layout.baseMode,'table');
});
test('existing laser adapter stays manufactured and loses only root beam-grid blocking on a table',()=>{
  const l=clone(require('../qa/optical-rendering-stacked.zzoptics.json').layout);l.baseMode='table';l.instances[0].yMm+=1;
  const {e}=editor(l),record=e.laserAdapterSpec(l.instances[0]);assert.equal(record.beamAligned,false);assert.equal(record.spec.boardMountingHolesMm.length,4);assert.ok(!e.validation().issues.some(i=>i.code==='adapter_beam_off_grid'));
});
test('shared component merge onto a table preserves nonaligned geometry across pitches and manufactures no root board',()=>{
  const options={catalog,validateBoard:b=>b,newId:(()=>{let n=0;return()=>`table-import-${++n}`})()},target=codec.create({metadata:{name:'Reference table'},layout:{baseMode:'table',board:board(),instances:[instance('existing',{xMm:500.1,yMm:500.1})]}},options),before=clone(target);
  for(const pitch of [12.5,25,37.5]){
    const source=codec.create({metadata:{name:'Unaligned shared optics'},layout:{board:board(300,250,pitch),instances:[instance('source-a',{xMm:110.1,yMm:100.1}),{id:'source-b',kitId:'waveplate',xMm:200.2,yMm:180.4,rotationDeg:90}]}},options),original=clone(source),result=shared.merge(target,source,{...options,offsetMm:{xMm:37.5,yMm:37.5}}),incoming=result.project.layout.instances.filter(i=>i.id!=='existing');
    assert.equal(result.project.layout.baseMode,'table');assert.equal(result.project.layout.subBoards,undefined,'component-only import does not manufacture or insert the source breadboard');assert.deepEqual(result.project.layout.board,target.layout.board,'reference area remains unchanged');assert.equal(incoming.length,2);
    for(let n=0;n<incoming.length;n++){assert.equal(incoming[n].xMm,source.layout.instances[n].xMm+result.offsetMm.xMm);assert.equal(incoming[n].yMm,source.layout.instances[n].yMm+result.offsetMm.yMm);assert.equal(incoming[n].rotationDeg,source.layout.instances[n].rotationDeg);assert.equal(incoming[n].boardId,undefined);assert.notEqual(incoming[n].id,source.layout.instances[n].id)}
    assert.ok(Math.abs((incoming[1].xMm-incoming[0].xMm)-(source.layout.instances[1].xMm-source.layout.instances[0].xMm))<1e-9);assert.ok(Math.abs((incoming[1].yMm-incoming[0].yMm)-(source.layout.instances[1].yMm-source.layout.instances[0].yMm))<1e-9);
    const {e}=editor(result.project.layout);assert.equal(e.validation().valid,true,JSON.stringify(e.validation().issues));assert.equal(e.snapshot().baseMode,'table');assert.deepEqual(target,before,'merge cannot mutate current table');assert.deepEqual(source,original,'merge cannot mutate the source');
    const python=`import json,sys\nfrom pathlib import Path\nfrom bom import aggregate,load_catalog\nr=aggregate(load_catalog(Path('catalog.json')),{'layout':json.load(sys.stdin)})\nprint(json.dumps({'valid':r['layoutValidation']['valid'],'boards':[x['componentId'] for x in r['manufacturing'] if x.get('generatedBoard')]}))`;
    const actual=JSON.parse(require('node:child_process').execFileSync(process.env.ZZLAB_TEST_PYTHON||'python3',['-c',python],{cwd:root,input:JSON.stringify(result.project.layout),encoding:'utf8'}));assert.equal(actual.valid,true);assert.deepEqual(actual.boards,[],'real production BOM must omit the reference root board');
    const physicalTarget=clone(target);delete physicalTarget.layout.baseMode;assert.throws(()=>shared.merge(physicalTarget,source,options),pitch===25?/安装孔/:/孔距不同/,'physical breadboards retain grid compatibility checks');
  }
});
console.log(`${checks} table mode checks passed`);
