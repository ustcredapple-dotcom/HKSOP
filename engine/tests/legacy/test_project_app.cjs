'use strict';
// Exercise the actual app attachment/project hooks with the real editor history.
// DOM rendering is stubbed; its pre-render input flush is deliberately preserved.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const appSource=fs.readFileSync(__dirname+'/static/app.js','utf8');
const section=(from,to)=>{
  const start=appSource.indexOf(from),end=appSource.indexOf(to,start);
  assert.ok(start>=0&&end>start,`app section exists: ${from}`);
  return appSource.slice(start,end);
};
const appHooks=[
  section('  function normalizeMountingSelection(', '  function persist('),
  section('  function updateQuantities(', '  function updateButtons('),
  section('  function storeOpticalInput(', '  function renderPlan('),
  section('  function layoutRequirements(', '  async function fetchAPI'),
  section('  function projectData(', '  function saveProject('),
  section('  function saveProject(', '  function applyProject('),
  section('  function applyProject(', "  $('save-layout-json').addEventListener"),
].join('\n');
const copy=x=>JSON.parse(JSON.stringify(x));
const equal=(a,b,message)=>assert.deepEqual(copy(a),copy(b),message);
const fixed='2026-09-24T09:00:00.000Z';
const board={widthMm:350,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]};
const instance=(id,x,y,angle=0)=>({id,kitId:'mirror',xMm:x,yMm:y,rotationDeg:angle});
const input=(id,field,value)=>({dataset:{instance:id,slot:'mirror',opticalField:field},value});
const optical=(model,wavelength='532')=>({model,wavelength,opticalType:'',kind:'lubang'});
const extra=(id,kitId,quantity,instanceId)=>({id,kitId,quantity,name:id,model:'M2x6',unit:'颗',kind:'standard',notes:'',...(instanceId?{instanceId}:{})});
function fixture(){
  const elements=new Map(),counters={persist:0,renderPlan:0,renderCards:0,resetExtraForm:0};
  const document={getElementById(id){if(!elements.has(id))elements.set(id,{id,value:'',hidden:false,inputs:[],clientWidth:700,clientHeight:500,replaceChildren(){this.inputs=[]},focus(){},classList:{toggle(){}}});return elements.get(id)},querySelectorAll(){return [...this.getElementById('plan-body').inputs,...this.getElementById('kit-grid').inputs]}};
  const bounds={xMin:-10,yMin:-10,xMax:10,yMax:10};
  const kits=[
    {id:'mirror',name:'Test mirror',opticalSlots:[{id:'mirror',label:'反射镜',type:'mirror',quantity:1,diameterMm:25.4}],layout:{topViewUrl:'mirror.svg',widthMm:20,heightMm:20,anchorXMm:10,anchorYMm:10,baseBoundsMm:bounds,collisionBoundsMm:bounds}},
    {id:'module',name:'Test standalone module',opticalSlots:[{id:'mirror',label:'反射镜',type:'mirror',quantity:3}],layout:{placementAllowed:false}},
    {id:'inactive',name:'Unused kit',opticalSlots:[],layout:{placementAllowed:true}},
  ];
  const state={catalog:{version:'test-catalog',kits},kits:new Map(kits.map(k=>[k.id,k])),quantities:new Map([['mirror',2]]),moduleQuantities:new Map([['module',3]]),extras:[extra('global',null,3),extra('per-kit','mirror',2),extra('instance-a','mirror',4,'a'),extra('instance-b','mirror',5,'b'),extra('inactive-extra','inactive',7)],optical:{'a::mirror':optical('A-532'),'b::mirror':optical('','780'),'module:module::mirror':optical('MODULE-780','780')},mountingSelection:{rowParity:'odd',columnParity:'even'},project:{name:'Old project',notes:'old notes',createdAt:fixed,updatedAt:fixed},revision:0,moduleRevision:0,preview:{},resultSource:'layout'};
  const downloads=[],messages=[];
  const context={window:{},document,console,crypto,state,opticalKey:(a,b)=>`${a}::${b}`,opticalKind:v=>v.kind||'lubang',$:id=>document.getElementById(id),persist(){counters.persist++},requestPersist(){context.persist()},requestPlanRender(){context.renderPlan()},updateButtons(){},renderExtras(){},resetExtraForm(){counters.resetExtraForm++;state.editingExtra=null},notify(...args){messages.push(args)},setTimeout(){},Blob:class{constructor(parts,options){this.text=parts.join('');this.type=options.type}},URL:{createObjectURL(blob){downloads.push({blob});return 'blob:project-test'},revokeObjectURL(){}}};
  document.body={append(){}};
  document.createElement=tag=>({tag,click(){Object.assign(downloads.at(-1),{filename:this.download,href:this.href,clicked:true})},remove(){}});
  vm.createContext(context);
  // Use one JS realm for the real codec's plain-data safety checks.
  vm.runInContext('globalThis.deepCopy=value=>JSON.parse(JSON.stringify(value));state.kits=new Map(state.catalog.kits.map(k=>[k.id,k]));state.quantities=new Map(state.quantities);state.moduleQuantities=new Map(state.moduleQuantities);',context);
  vm.runInContext(fs.readFileSync(__dirname+'/static/manual-source-mount.js','utf8'),context);
  vm.runInContext(fs.readFileSync(__dirname+'/static/layout.js','utf8'),context);
  vm.runInContext(fs.readFileSync(__dirname+'/static/metric-migration.js','utf8'),context);
  vm.runInContext(fs.readFileSync(__dirname+'/static/project-file.js','utf8'),context);
  context.window.ZZLabProjectFile=context.ZZLabProjectFile;
  context.renderPlan=()=>{counters.renderPlan++;context.flushOpticalInputs()};
  context.renderCards=()=>{counters.renderCards++;context.flushOpticalInputs()};
  vm.runInContext(appHooks,context);
  const editor=Object.create(context.window.BreadboardEditor.prototype);
  Object.assign(editor,{board:copy(board),instances:[instance('a',62.5,62.5),instance('b',112.5,87.5,90)],selectedIds:vm.runInContext("new Set(['a','b'])",context),selectedId:'b',history:[],future:[],clipboard:null,pasteCount:0,keyboardActive:true,view:{x:-10,y:-20,w:400,h:260},pendingKitId:null,drag:null,space:false,boardFormDirty:false,kits:state.kits,svg:document.getElementById('board-svg'),viewport:document.getElementById('board-viewport'),render(){},notify(message){this.notices.push(message)},notices:[],captureExternalState:context.captureExternalState,restoreExternalState:context.restoreExternalState,onCopy:context.copyAttachments,onPaste:context.pasteAttachments,onRemove:context.removeAttachments,onChange:context.syncLayout,onSelect(){context.renderPlan();context.persist()}});
  context.editor=editor;
  const editableState=()=>{const p=copy(context.projectData());delete p.metadata.updatedAt;return p};
  return {context,state,editor,document,elements,counters,editableState,downloads,messages};
}
let count=0;
function test(name,fn){fn();count++;console.log(`PASS ${name}`)}

test('copy freezes original positions, blank optics and instance extras after editing and deleting originals',()=>{
  const {context,state,editor}=fixture();
  const packet=editor.copySelection();
  assert.ok(Object.isFrozen(packet)&&Object.isFrozen(packet.metadata.optical['a::mirror']));
  state.optical['a::mirror'].model='EDITED';state.extras.find(e=>e.id==='instance-a').quantity=99;
  editor.instances[0].xMm=200;editor.removeIds(['a']);
  const result=editor.pasteSelection();assert.equal(result.ids.length,2);
  const [a,b]=result.ids;
  equal(editor.selectedInstances().map(i=>[i.xMm,i.yMm,i.rotationDeg]),[[75,75,0],[125,100,90]]);
  equal(state.optical[a+'::mirror'],optical('A-532'));
  equal(state.optical[b+'::mirror'],optical('','780'));
  assert.equal(state.extras.find(e=>e.instanceId===a).quantity,4);
  assert.equal(state.extras.find(e=>e.instanceId===b).quantity,5);
  assert.equal(state.extras.filter(e=>e.id==='global').length,1);
  assert.equal(state.extras.find(e=>e.id==='global').quantity,3);
  assert.equal(state.extras.filter(e=>e.id==='per-kit').length,1);
  assert.equal(state.extras.find(e=>e.id==='per-kit').quantity,2);
  assert.equal(state.extras.filter(e=>e.kitId==='inactive').length,1);
  assert.equal(state.moduleQuantities.get('module'),3);
  assert.equal(state.optical['module:module::mirror'].model,'MODULE-780');
  assert.equal(new Set(state.extras.map(e=>e.id)).size,state.extras.length);
  state.optical[a+'::mirror'].model='COPY-ONLY';
  assert.equal(packet.metadata.optical['a::mirror'].model,'A-532');
  assert.equal(state.optical['b::mirror'].model,'');
  const request=context.payload();
  assert.equal(request.extras.filter(e=>e.id==='per-kit').length,1);
});

test('duplicate does not multiply global or per-kit configuration rows',()=>{
  const {context,state,editor}=fixture();
  const first=editor.duplicate();assert.equal(first.ids.length,2);
  assert.equal(editor.instances.length,4);assert.equal(state.quantities.get('mirror'),4);
  assert.equal(state.extras.filter(e=>!e.instanceId&&e.kitId==='mirror').length,1);
  assert.equal(state.extras.find(e=>e.id==='per-kit').quantity*state.quantities.get('mirror'),8);
  assert.equal(state.extras.find(e=>e.id==='global').quantity,3);
  assert.equal(context.modulePayload('module',3).extras.filter(e=>e.id==='global').length,1);
  editor.undo();assert.equal(editor.instances.length,2);assert.equal(state.extras.length,5);
  editor.redo();assert.equal(editor.instances.length,4);assert.equal(state.extras.length,7);
  equal([...editor.selectedIds],first.ids);
});

test('batch delete flushes visible optics and undo/redo restores attachments in one action',()=>{
  const {state,editor,document}=fixture();
  document.getElementById('plan-body').inputs=[input('a','model','TYPED-BEFORE-DELETE'),input('b','wavelength','')];
  editor.remove();assert.equal(editor.history.length,1);assert.equal(editor.instances.length,0);
  equal(Object.keys(state.optical),['module:module::mirror']);
  assert.equal(state.extras.length,3);assert.equal(document.getElementById('plan-body').inputs.length,0);
  editor.undo();assert.equal(editor.instances.length,2);assert.equal(state.extras.length,5);
  equal([...editor.selectedIds],['a','b']);
  assert.equal(state.optical['a::mirror'].model,'TYPED-BEFORE-DELETE');
  assert.equal(state.optical['b::mirror'].wavelength,'');
  editor.redo();assert.equal(editor.instances.length,0);equal(Object.keys(state.optical),['module:module::mirror']);
});

const newProject=()=>({metadata:{name:'Imported project',notes:'new notes\nwith a second line',createdAt:'2026-09-23T01:02:03.000Z',updatedAt:fixed},catalogVersion:'test-catalog',layout:{board:{...copy(board),widthMm:300,heightMm:150,thicknessMm:10,mountingHoles:[{columnIndex:0,rowIndex:0},{columnIndex:22,rowIndex:0},{columnIndex:0,rowIndex:10},{columnIndex:22,rowIndex:10}]},instances:[instance('a',87.5,37.5,180),instance('new',162.5,87.5,270)]},optical:{'a::mirror':optical('IMPORTED-A','1064'),'new::mirror':optical('',''),'module:module::mirror':optical('IMPORTED-MODULE','')},extras:[extra('new-global',null,9),extra('new-a','mirror',8,'a'),extra('new-inactive','inactive',6)],moduleQuantities:[['module',8]],ui:{mountingSelection:{rowParity:'even',columnParity:'odd'},view:{x:20,y:10,w:160,h:100},selectedIds:['a','new']}});

test('project import plus undo/redo restores complete state without stale inputs crossing the transition',()=>{
  const {context,state,editor,document,editableState}=fixture();
  document.getElementById('plan-body').inputs=[input('a','model','OLD-DOM-MODEL')];
  document.getElementById('kit-grid').inputs=[input('module:module','model','OLD-MODULE-DOM')];
  const before=editableState(),project=newProject();
  context.applyProject(project);
  assert.equal(editor.history.length,1);assert.equal(editor.future.length,0);
  assert.equal(state.optical['a::mirror'].model,'IMPORTED-A');
  assert.equal(state.optical['module:module::mirror'].model,'IMPORTED-MODULE');
  assert.equal(document.querySelectorAll().length,0,'replaceChildren detaches old instance and module inputs before any flush');
  equal(state.extras,project.extras);equal([...state.moduleQuantities],project.moduleQuantities);
  equal(editor.view,project.ui.view);equal([...editor.selectedIds],project.ui.selectedIds);
  assert.equal(document.getElementById('project-name').value,'Imported project');
  assert.equal(document.getElementById('mounting-row-parity').value,'even');
  assert.equal(document.getElementById('board-width').value,300);
  const imported=editableState();
  // Nodes rendered for the imported project may still exist at undo time.
  document.getElementById('plan-body').inputs=[input('a','model','IMPORTED-A')];
  document.getElementById('kit-grid').inputs=[input('module:module','model','IMPORTED-MODULE')];
  editor.undo();equal(editableState(),before,'undo includes board, optics, extras, modules, metadata, parity, view and selection');
  assert.equal(state.optical['a::mirror'].model,'OLD-DOM-MODEL');
  assert.equal(state.optical['module:module::mirror'].model,'OLD-MODULE-DOM');
  document.getElementById('plan-body').inputs=[input('a','model','OLD-DOM-MODEL')];
  document.getElementById('kit-grid').inputs=[input('module:module','model','OLD-MODULE-DOM')];
  editor.redo();equal(editableState(),imported,'redo includes complete imported project');
  assert.ok(Number.isFinite(Date.parse(state.project.updatedAt)));
});

test('missing imported viewport fits new geometry and undo restores the previous viewport',()=>{
  const {context,editor}=fixture(),oldView=copy(editor.view),project=newProject();
  project.ui.view=null;context.applyProject(project);
  assert.ok(editor.view.w>0&&editor.view.h>0);assert.notDeepEqual(copy(editor.view),oldView);
  const fitted=copy(editor.view);editor.undo();equal(editor.view,oldView);editor.redo();equal(editor.view,fitted);
});

test('partial attachment failure rolls a paste back atomically',()=>{
  const {context,editor,editableState}=fixture();editor.copySelection();const before=editableState();
  editor.onPaste=(mapping,metadata)=>{context.pasteAttachments(mapping,metadata);throw new Error('simulated failure after mutation')};
  assert.equal(editor.pasteSelection(),null);equal(editableState(),before);
  assert.equal(editor.history.length,0);assert.equal(editor.pasteCount,0);
});

test('project save captures empty and inactive choices while backend layout remains geometry only',()=>{
  const {context,state,editor}=fixture();
  state.optical['a::mirror']=optical('','');
  const project=context.projectData();assert.equal(project.optical['a::mirror'].model,'');
  assert.equal(project.optical['a::mirror'].wavelength,'');
  assert.ok(project.extras.some(e=>e.kitId==='inactive'));
  assert.equal(project.moduleQuantities[0][1],3);equal(project.ui.view,editor.view);
  const request=context.payload();
  equal(Object.keys(editor.snapshot()).sort(),['board','instances']);
  equal(Object.keys(request.layout).sort(),['board','instances']);
  equal(Object.keys(request).sort(),['catalogVersion','extras','layout']);
  assert.ok(!request.extras.some(e=>e.kitId==='inactive'));
  assert.ok(!request.extras.some(e=>e.instanceId==='a'&&e.slotId==='mirror'));
  assert.equal(project.extras.length,5,'request filtering does not mutate persisted project');
  request.layout.instances[0].xMm=999;assert.equal(editor.instances[0].xMm,62.5);
});

test('saveProject actual downloaded JSON bytes round-trip through codec and restore full editing state',()=>{
  const {context,state,editor,document,downloads,messages,editableState}=fixture();
  state.project.name='光路/测试:532';state.project.notes='型号可以留空\n以后再选';
  document.getElementById('plan-body').inputs=[input('a','model',''),input('a','wavelength','1064')];
  document.getElementById('kit-grid').inputs=[input('module:module','model',''),input('module:module','wavelength','780')];
  const before=editableState();context.saveProject();
  assert.equal(downloads.length,1,JSON.stringify(messages));
  const download=downloads[0];assert.equal(download.clicked,true);
  assert.equal(download.filename,'光路_测试_532.zzoptics.json');
  assert.equal(download.blob.type,'application/json;charset=utf-8');
  assert.ok(download.blob.text.endsWith('\n'));
  const opened=context.window.ZZLabProjectFile.parse(download.blob.text,context.projectOptions());
  assert.equal(opened.legacy,false);equal(opened.warnings,[]);
  assert.equal(opened.project.optical['a::mirror'].model,'');
  assert.equal(opened.project.optical['a::mirror'].wavelength,'1064');
  assert.equal(opened.project.optical['b::mirror'].model,'');
  assert.equal(opened.project.optical['module:module::mirror'].model,'');
  assert.ok(opened.project.extras.some(e=>e.id==='inactive-extra'));
  context.applyProject(newProject());
  context.applyProject(opened.project);
  equal(editableState(),before,'downloaded file restores metadata, board, layout, raw optics, all extras, modules, viewport and selection');
  assert.equal(editor.selectedIds.size,2);
  assert.ok(messages.some(([message])=>message.includes('工程已保存')));
});

console.log(`${count} project/app integration checks passed using actual hooks and BreadboardEditor prototype.`);
