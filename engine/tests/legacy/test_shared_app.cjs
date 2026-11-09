'use strict';
// Actual shared-library app hooks with the existing real editor/history fixture.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const harness={require,__dirname,console};vm.createContext(harness);
const fixtureSource=fs.readFileSync(__dirname+'/test_project_app.cjs','utf8');
vm.runInContext(fixtureSource.slice(0,fixtureSource.indexOf('let count=0;'))+'\nglobalThis.makeFixture=fixture;',harness);
const source=fs.readFileSync(__dirname+'/static/app.js','utf8'),clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){
  const f=harness.makeFixture(),c=f.context;f.state.session={role:'user',canPublish:true,canDownload:true,loaded:true};
  c.state.kits.get('mirror').layout.mountingHoleOffsetsMm=[{xMm:0,yMm:0}];
  // Install the production unified board editor extension on the actual history
  // prototype. Rendering remains stubbed by the project fixture.
  c.BreadboardEditor=c.window.BreadboardEditor;c.ZZLabLayoutGeometry=c.window.ZZLabLayoutGeometry;
  vm.runInContext(fs.readFileSync(__dirname+'/static/stacked-boards.js','utf8'),c);
  c.window.ZZLabStackMath=c.ZZLabStackMath;
  vm.runInContext(fs.readFileSync(__dirname+'/static/shared-project.js','utf8'),c);
  c.window.ZZLabSharedProject=c.ZZLabSharedProject;
  vm.runInContext(source.slice(source.indexOf('  function sharedContext('),source.indexOf('  function projectData(')),c);
  vm.runInContext(source.slice(source.indexOf('  function downloadName('),source.indexOf('  async function exportList(')),c);
  c.editor.onBeforeContextChange=c.flushOpticalInputs;
  c.editor.viewport.scrollIntoView=()=>{};
  return f;
}
function project(f){return f.context.window.ZZLabProjectFile.create(f.context.projectData(),f.context.projectOptions())}
function shared(f){const p=f.context.window.ZZLabSharedProject.subset(project(f),null,f.context.projectOptions());p.metadata.name='共享反射组合';return p}
async function run(){
  {
    const f=fixture(),before=clone(f.editableState());let request;
    f.editor.setSelection(['a']);f.context.fetchAPI=async(path,options)=>{request={path,payload:JSON.parse(options.body)};return{json:async()=>({kit:{id:'server-id'}})}};
    await f.context.publishSharedKit({name:'  反射组合  ',description:'  固定版本  ',scope:'selection'});
    assert.equal(request.path,'/shared-kits');assert.equal(request.payload.name,'反射组合');assert.equal(request.payload.project.metadata.name,'反射组合');
    assert.equal(request.payload.project.layout.instances.length,1);assert.equal(request.payload.project.extras.some(e=>e.kitId===null),false);
    assert.deepEqual(request.payload.project.moduleQuantities,[]);assert.ok(!Object.keys(request.payload.project.optical).some(k=>k.startsWith('module:')));
    assert.equal(f.state.project.name,before.metadata.name,'publishing a name does not rename the current engineering project');
    assert.equal(f.editor.history.length,0);assert.equal(f.state.extras.length,before.extras.length);
  }
  {
    const f=fixture(),incoming=shared(f),before=clone(f.editableState());
    f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});
    await f.context.addSharedKit({id:'kit1',name:incoming.metadata.name});
    assert.equal(f.editor.instances.length,2,'root editing context preserves its directly mounted components');assert.equal(f.editor.allInstances().length,4);assert.equal(f.editor.history.length,1);assert.equal(f.editor.selectedIds.size,0);
    const mounted=f.editor.snapshot(),plate=mounted.subBoards[0];assert.equal(mounted.subBoards.length,1);
    assert.equal(f.editor.activeBoardId,null);assert.equal(f.editor.selectedModuleId,plate.id,'the new board module is selected as one group');assert.deepEqual(clone(f.editor.validBoard(mounted.board)),before.layout.board,'the existing board becomes the carrier without resizing');
    assert.deepEqual(clone(f.editor.validBoard(plate.board)),clone(f.editor.validBoard(incoming.layout.board)),'source small-board dimensions, pitch and holes are retained in full');
    assert.deepEqual(clone(mounted.instances.filter(i=>!i.boardId)),before.layout.instances,'original root-board components stay in place');
    const added=mounted.instances.filter(i=>i.boardId===plate.id);assert.equal(added[1].xMm-added[0].xMm,50);assert.equal(added[1].yMm-added[0].yMm,25);
    assert.deepEqual(clone(added.map(({id,boardId,...i})=>i)),clone(incoming.layout.instances.map(({id,...i})=>i)),'module retains exact local component poses');
    assert.deepEqual(clone(f.editor.view),before.ui.view,'adding a module preserves the shared canvas viewport');
    assert.equal(f.state.project.name,before.metadata.name);assert.deepEqual(clone(f.editor.board),before.layout.board);
    assert.equal(f.state.optical[added[0].id+'::mirror'].model,'A-532');assert.equal(f.state.optical[added[1].id+'::mirror'].model,'');
    const local=f.state.extras.filter(e=>e.instanceId===added[0].id);assert.equal(local.reduce((n,e)=>n+e.quantity,0),9,'shared first instance owns global3, per-kit2, instance4 once');
    assert.equal(f.state.extras.filter(e=>!e.instanceId&&e.kitId==='mirror').length,0,'current per-kit rows do not accidentally affect imported instances');
    f.editor.undo();assert.deepEqual(clone(f.editableState()),before,'one undo restores complete pre-insert project');
    assert.equal(f.editor.stacked,null,'undo also restores flat-board mode');
    f.editor.redo();assert.equal(f.editor.instances.length,2);assert.equal(f.editor.allInstances().length,4);assert.equal(f.editor.snapshot().subBoards.length,1);assert.equal(f.editor.selectedModuleId,plate.id);
  }
  {
    const f=fixture(),incoming=shared(f);f.editor.board.pitchMm=25;
    incoming.layout.board.widthMm=200;incoming.layout.board.heightMm=150;
    incoming.layout.board.mountingHoles=[{columnIndex:0,rowIndex:0},{columnIndex:14,rowIndex:0},{columnIndex:0,rowIndex:10},{columnIndex:14,rowIndex:10}];
    const before=clone(f.editableState()),source=clone(incoming);
    assert.equal(f.context.sharedContext().canMountModules,true,'a flat canvas already accepts whole modules');
    assert.equal(f.context.sharedContext().hasCarrier,false);
    f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});
    await f.context.addSharedKit({id:'mixed-pitch',name:incoming.metadata.name},{xMm:125,yMm:25});
    const layout=f.editor.snapshot(),plate=layout.subBoards[0];
    assert.equal(layout.board.pitchMm,25);assert.equal(plate.board.pitchMm,12.5,'small-board pitch is independent of the carrier pitch');
    assert.deepEqual(clone(f.editor.validBoard(plate.board)),clone(f.editor.validBoard(source.layout.board)),'original counterbores stay attached to the module');
    assert.equal(plate.xMm,125);assert.equal(plate.yMm,25);assert.equal(plate.rotationDeg,0);
    assert.deepEqual(clone(layout.instances.filter(i=>i.boardId===plate.id).map(({id,boardId,...i})=>i)),source.layout.instances.map(({id,...i})=>i));
    assert.deepEqual(clone(layout.instances.filter(i=>!i.boardId)),before.layout.instances);
    f.editor.undo();assert.deepEqual(clone(f.editableState()),before);
  }
  {
    const f=fixture(),incoming=shared(f);incoming.layout.board.widthMm=200;incoming.layout.board.heightMm=150;
    incoming.layout.board.mountingHoles=[{columnIndex:0,rowIndex:0},{columnIndex:14,rowIndex:0},{columnIndex:0,rowIndex:10},{columnIndex:14,rowIndex:10}];
    f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});await f.context.addSharedKit({id:'module',name:'共享模块'});
    const selected=f.editor.snapshot().subBoards[0],context=f.context.sharedContext();
    assert.equal(f.editor.activeBoardId,null);assert.equal(context.activeBoard,true,'a selected whole module can be published without entering its internal editing context');assert.equal(context.activeBoardCount,2);
    let request;f.context.fetchAPI=async(path,options)=>{request={path,payload:JSON.parse(options.body)};return{json:async()=>({kit:{id:'published'}})}};
    await f.context.publishSharedKit({name:'独立小板模块',description:'',scope:'board'});
    const published=request.payload.project;
    assert.equal(request.path,'/shared-kits');assert.equal(published.layout.subBoards,undefined);assert.equal(published.layout.instances.length,2);assert.ok(published.layout.instances.every(i=>!i.boardId));
    assert.deepEqual(published.layout.board,clone(selected.board),'publishing a whole selected module preserves original board and counterbores');
    assert.ok(!published.layout.instances.some(i=>['a','b'].includes(i.id)),'root components are excluded from publishing a selected module');
  }
  {
    const f=fixture(),incoming=shared(f);incoming.layout.board.widthMm=400;incoming.metadata.name='打开共享';const before=clone(f.editableState());
    f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});
    await f.context.openSharedKit({id:'open',name:incoming.metadata.name});assert.equal(f.state.project.name,'打开共享');assert.equal(f.editor.board.widthMm,400);
    f.editor.undo();assert.deepEqual(clone(f.editableState()),before);
  }
  {
    const f=fixture(),incoming=shared(f);f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});await f.context.addSharedKit({id:'module',name:'模块'});
    const plate=f.editor.snapshot().subBoards[0],child=f.editor.allInstances().find(i=>i.boardId===plate.id),view=clone(f.editor.view);
    f.editor.editModule(plate.id);assert.equal(f.editor.activeBoardId,plate.id);assert.equal(f.editor.selectedModuleId,null);
    f.document.getElementById('plan-body').inputs=[{dataset:{instance:child.id,slot:'mirror',opticalField:'model'},value:'EDITED-IN-MODULE'}];
    f.editor.finishModuleEdit();assert.equal(f.state.optical[child.id+'::mirror'].model,'EDITED-IN-MODULE','leaving the module saves typed optics before changing local ownership');assert.deepEqual(clone(f.editor.view),view);
    f.editor.selectModule(plate.id);const packet=f.editor.copySelection();f.state.optical[child.id+'::mirror'].model='CHANGED-AFTER-COPY';
    const pasted=f.editor.pasteSelection(),mapped=pasted.mapping.find(pair=>pair.fromId===child.id),newPlate=f.editor.snapshot().subBoards.find(p=>p.id===pasted.id);
    assert.equal(f.editor.selectedModuleId,pasted.id);assert.equal(f.editor.activeBoardId,null);assert.equal(f.editor.allInstances().length,6);assert.equal(f.editor.selectedIds.size,0);
    assert.deepEqual(clone(newPlate.board),clone(packet.plate.board));assert.equal(f.state.optical[mapped.toId+'::mirror'].model,'EDITED-IN-MODULE','copied module optics are an immutable snapshot');assert.equal(f.state.optical[child.id+'::mirror'].model,'CHANGED-AFTER-COPY');
    assert.deepEqual(clone(f.editor.allInstances().find(i=>i.id===mapped.toId)).xMm,child.xMm,'whole-module duplication preserves local component position');
    const copiedExtras=f.state.extras.filter(e=>e.instanceId===mapped.toId);assert.equal(copiedExtras.reduce((sum,e)=>sum+e.quantity,0),9,'each copied module receives its instance attachments once');
    const beforeRemoval=clone(f.editableState());f.editor.remove();assert.equal(f.editor.snapshot().subBoards.length,1);assert.equal(f.editor.allInstances().length,4);assert.ok(!f.state.optical[mapped.toId+'::mirror']);assert.ok(!f.state.extras.some(e=>e.instanceId===mapped.toId));
    f.editor.undo();assert.deepEqual(clone(f.editableState()),beforeRemoval,'undo restores the complete copied module, its board, optics and extras');assert.equal(f.editor.selectedModuleId,pasted.id);
  }
  {
    const f=fixture(),before=clone(f.editableState());f.editor.useCurrentAsCarrier();
    assert.deepEqual(clone(f.editor.snapshot()),{...before.layout,subBoards:[]},'explicit carrier promotion never creates a duplicate board or moves existing parts');
    assert.equal(f.editor.activeBoardId,null);assert.equal(f.editor.history.length,1);
    f.editor.undo();assert.deepEqual(clone(f.editableState()),before);assert.equal(f.editor.stacked,null);
  }
  {
    const f=fixture(),incoming=shared(f),before=clone(f.editableState()),mapped=[];let fetches=0;
    const screenMapping=(id,left,top)=>{
      const svg=f.document.getElementById(id);svg.getBoundingClientRect=()=>({left,top,right:left+900,bottom:top+600});
      svg.getScreenCTM=()=>({inverse:()=>({})});
      svg.createSVGPoint=()=>({x:0,y:0,matrixTransform(){mapped.push(id);return{x:(this.x-left)/2,y:(this.y-top)/2}}});
    };
    screenMapping('board-svg',100,50);
    f.context.fetchAPI=async()=>{fetches++;return{text:async()=>JSON.stringify(incoming)}};
    await f.context.dropSharedOnCarrier({id:'dragged',name:'拖入模块'},{clientX:99,clientY:100});
    await f.context.dropSharedOnCarrier({id:'dragged',name:'拖入模块'},{clientX:900,clientY:100});
    assert.equal(fetches,0,'outside SVG or board geometry never triggers a read or promotion');assert.equal(f.editor.stacked,undefined);assert.deepEqual(clone(f.editableState()),before);
    await f.context.dropSharedOnCarrier({id:'dragged',name:'拖入模块'},{clientX:350,clientY:250});
    assert.equal(fetches,1);assert.equal(mapped.at(-1),'board-svg','flat drag uses the current canvas screen transform');
    let plates=f.editor.snapshot().subBoards;assert.equal(plates.length,1);assert.equal(plates[0].xMm,125);assert.equal(plates[0].yMm,125);
    await f.context.dropSharedOnCarrier({id:'dragged-again',name:'再次拖入'},{clientX:300,clientY:350});
    assert.equal(fetches,2);assert.ok(mapped.every(id=>id==='board-svg'),'all module drops keep using the same canvas transform');
    plates=f.editor.snapshot().subBoards;assert.equal(plates.length,2);assert.equal(plates[1].xMm,100);assert.equal(plates[1].yMm,75);assert.equal(f.editor.allInstances().length,6);
    assert.deepEqual(clone(f.editor.snapshot().instances.filter(i=>!i.boardId)),before.layout.instances);
  }
  {
    const f=fixture(),before=clone(f.editableState());f.context.fetchAPI=async()=>{throw Error('网络暂不可用')};
    await assert.rejects(f.context.addSharedKit({id:'x',name:'x'}),/网络暂不可用/);assert.deepEqual(clone(f.editableState()),before);assert.equal(f.editor.history.length,0);
    f.context.fetchAPI=async()=>({text:async()=>'{"format":"unknown"}'});
    await assert.rejects(f.context.openSharedKit({id:'x',name:'x'}));assert.deepEqual(clone(f.editableState()),before);
  }
  {
    const f=fixture(),incoming=shared(f);let resolve;
    f.context.fetchAPI=()=>new Promise(r=>resolve=r);const pending=f.context.addSharedKit({id:'x',name:'x'});
    f.editor.boardFormDirty=true;resolve({text:async()=>JSON.stringify(incoming)});
    await assert.rejects(pending,/更新面包板/);assert.equal(f.editor.instances.length,2);assert.equal(f.editor.history.length,0);
  }
  {
    const f=fixture();let called;f.context.fetchAPI=async path=>{called=path;return{blob:async()=>({content:'download'}),headers:{get:()=>"attachment; filename*=UTF-8''%E5%8F%8D%E5%B0%84.zzoptics.json"}}};
    await f.context.downloadSharedKit({id:'safe-id',name:'组合'},'project');assert.equal(called,'/shared-kits/safe-id/project');assert.equal(f.downloads.at(-1).filename,'反射.zzoptics.json');assert.equal(f.downloads.at(-1).clicked,true);
    await assert.rejects(f.context.downloadSharedKit({id:'x'},'unpublish'),/下载格式无效/);
  }
  {
    const f=fixture(),a=shared(f),b=clone(a),responses={};a.metadata.name='older A';b.metadata.name='newer B';
    f.context.fetchAPI=path=>new Promise(resolve=>{responses[path]=resolve});
    const first=f.context.openSharedKit({id:'a',name:'A'}).then(()=>null,error=>error),second=f.context.openSharedKit({id:'b',name:'B'});
    responses['/shared-kits/b/project']({text:async()=>JSON.stringify(b)});await second;
    responses['/shared-kits/a/project']({text:async()=>JSON.stringify(a)});assert.match((await first).message,/更新的工程/);
    assert.equal(f.state.project.name,'newer B','an old network response cannot replace a more recently opened engineering project');
  }
  {
    const f=fixture(),incoming=shared(f);let resolve;f.context.fetchAPI=()=>new Promise(r=>resolve=r);
    const pending=f.context.addSharedKit({id:'x',name:'x'}).then(()=>null,error=>error);
    f.context.applyProject(incoming);resolve({text:async()=>JSON.stringify(incoming)});
    assert.match((await pending).message,/工程已切换/);assert.equal(f.editor.instances.length,2,'pending add cannot leak into a replacement project');
  }
  {
    const f=fixture(),incoming=shared(f);let resolve;f.context.fetchAPI=()=>new Promise(r=>resolve=r);
    const pending=f.context.openSharedKit({id:'x',name:'x'}).then(()=>null,error=>error);
    f.state.project.notes='typed while loading';f.context.markChanged();resolve({text:async()=>JSON.stringify(incoming)});
    assert.match((await pending).message,/当前工程已修改/);assert.equal(f.state.project.notes,'typed while loading');
  }
  {
    const f=fixture(),incoming=shared(f),responses=[];f.context.fetchAPI=()=>new Promise(r=>responses.push(r));
    const first=f.context.addSharedKit({id:'a',name:'A'}),second=f.context.addSharedKit({id:'b',name:'B'});
    responses[1]({text:async()=>JSON.stringify(incoming)});await second;responses[0]({text:async()=>JSON.stringify(incoming)});await first;
    assert.equal(f.editor.instances.length,2,'adding modules leaves the root editing context in place');assert.equal(f.editor.activeBoardId,null);assert.equal(f.editor.allInstances().length,6,'two additions both apply to the latest project');assert.equal(f.editor.snapshot().subBoards.length,2);assert.equal(f.editor.history.length,2);
    assert.equal(f.editor.selectedModuleId,f.editor.snapshot().subBoards[1].id,'the last completed addition selects its whole module');
    assert.equal(new Set(f.editor.allInstances().map(i=>i.id)).size,6,'each added module has fresh component IDs');
    for(const plate of f.editor.snapshot().subBoards)assert.equal(f.editor.allInstances().filter(i=>i.boardId===plate.id).length,2);
    f.editor.undo();assert.equal(f.editor.snapshot().subBoards.length,1);assert.equal(f.editor.allInstances().length,4);assert.equal(f.editor.selectedModuleId,f.editor.snapshot().subBoards[0].id,'undo restores the previously selected module');
    f.editor.undo();assert.equal(f.editor.stacked,null);assert.equal(f.editor.allInstances().length,2);
  }
  {
    const f=fixture(),incoming=shared(f);f.context.fetchAPI=async()=>({text:async()=>JSON.stringify(incoming)});
    await f.context.addSharedKit({id:'module',name:'模块'});
    const saved=project(f),plate=saved.layout.subBoards[0],child=saved.layout.instances.find(i=>i.boardId===plate.id),view=clone(f.editor.view);
    saved.ui.selectedIds=['a'];f.context.applyProject(saved);
    assert.equal(f.editor.activeBoardId,null,'opening a root selection never switches to the first small board');assert.deepEqual([...f.editor.selectedIds],['a']);assert.deepEqual(clone(f.editor.view),view);
    saved.ui.selectedIds=[child.id];f.context.applyProject(saved);
    assert.equal(f.editor.activeBoardId,plate.id,'opening a selected child component restores its local editing context');assert.deepEqual([...f.editor.selectedIds],[child.id]);assert.deepEqual(clone(f.editor.view),view,'child editing retains the same complete-assembly viewport');
    saved.ui.selectedIds=[];f.context.applyProject(saved);
    assert.equal(f.editor.activeBoardId,null,'an unselected project opens the whole canvas, not an arbitrary small board');assert.equal(f.editor.selectedIds.size,0);
    const layout=f.context.payload().layout;
    assert.deepEqual(clone(f.editor.validBoard(layout.board)),clone(f.editor.validBoard(saved.layout.board)));
    assert.deepEqual(clone(layout.subBoards),clone(saved.layout.subBoards));
    assert.deepEqual(clone(layout.instances).sort((a,b)=>a.id.localeCompare(b.id)),clone(saved.layout.instances).sort((a,b)=>a.id.localeCompare(b.id)),'checkout includes root and every small-board component regardless of editing context');
  }
  console.log('Shared app: one-canvas module selection, original board and local geometry, mixed pitches, stable viewport, root/child selection import, whole-assembly payload, atomic undo/redo, failed/racing requests and named download passed.');
}
run().catch(error=>{console.error(error);process.exitCode=1});
