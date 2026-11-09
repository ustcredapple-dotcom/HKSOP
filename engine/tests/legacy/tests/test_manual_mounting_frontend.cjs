'use strict';
// Real renderer, event handlers, geometry and history; test-only DOM is the counted SVG fixture.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..'),performance=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');
const harness={require,__dirname:root,console};vm.createContext(harness);
const setup=performance.slice(0,performance.indexOf('{\n  const f=fixture(),e=f.editor'));
assert.ok(setup.length>1000,'production renderer fixture is available');vm.runInContext(setup+'\nglobalThis.createManualFixture=fixture;',harness);
const copy=x=>JSON.parse(JSON.stringify(x)),same=(a,b,message)=>assert.deepEqual(copy(a),copy(b),message),h=(columnIndex,rowIndex)=>({columnIndex,rowIndex});
function fixture(){
  const f=harness.createManualFixture(0),e=f.editor,d=f.document;const Element=e.svg.constructor;
  if(!Element.prototype.replaceChildren)Element.prototype.replaceChildren=function(...children){for(const child of this.children)child.parentNode=null;this.children=[];for(const child of children)this.appendChild(child)};
  e.notices=[];e.notify=(...args)=>e.notices.push(args);d.getElementById('mounting-row-parity').value='any';d.getElementById('mounting-column-parity').value='any';
  const point=(column,row)=>({xMm:e.board.edgeOffsetMm+column*e.board.pitchMm,yMm:e.board.edgeOffsetMm+row*e.board.pitchMm});
  const pick=(column,row)=>e.pickManualMounting(point(column,row));
  const click=(column,row,extra={})=>{const p=point(column,row);const event={target:e.svg,button:0,pointerId:1,clientX:p.xMm,clientY:e.board.heightMm-p.yMm,preventDefault(){this.prevented=true},...extra};e.svg.handlers.pointerdown(event);return event};
  return{...f,e,d,pick,click,point};
}
let cases=0;function test(name,run){run();cases++;console.log('PASS '+name)}
test('pointer clicks toggle four draft holes; apply creates one undo step',()=>{
  const f=fixture(),{e,d,click}=f,before=copy(e.snapshot()),changes=f.counts().changes;e.beginManualMounting();assert.equal(d.getElementById('mounting-manual-bar').hidden,false);assert.equal(d.getElementById('mounting-manual').getAttribute('aria-pressed'),'true');
  click(0,0);assert.equal(e.manualMounting.holes.length,1);click(0,0);assert.equal(e.manualMounting.holes.length,0);click(0,0);click(2,0);click(0,2);assert.equal(e.applyManualMounting(),false,'three cannot apply');click(2,2);assert.equal(e.manualMounting.holes.length,4);click(4,4);assert.equal(e.manualMounting.holes.length,4,'fifth cannot add');assert.match(e.notices.at(-1)[0],/已达到所选孔数/);assert.equal(d.getElementById('mounting-manual-apply').disabled,false);
  same(e.snapshot(),before,'draft click selection never mutates board');assert.equal(f.counts().changes,changes,'draft selection cannot autosave or stale cart');assert.equal(e.history.length,0);assert.equal(e.applyManualMounting(),true);same(e.board.mountingHoles,[h(0,0),h(2,0),h(0,2),h(2,2)]);assert.equal(e.manualMounting,null);assert.equal(e.history.length,1);assert.equal(f.counts().changes,changes+1);assert.equal(d.getElementById('mounting-manual-bar').hidden,true);
  e.undo();same(e.snapshot(),before);e.redo();same(e.board.mountingHoles,[h(0,0),h(2,0),h(0,2),h(2,2)]);
});
test('cancel, reset and reopening preserve previous applied holes and history',()=>{
  const {e,d,click}=fixture();const original=[h(0,0),h(2,0),h(0,2),h(2,2)];e.setMountingHoles(original);const history=e.history.length;e.beginManualMounting();same(e.manualMounting.holes,original);click(0,0);d.getElementById('mounting-manual-reset').handlers.click();assert.equal(e.manualMounting.holes.length,0);same(e.board.mountingHoles,original);d.getElementById('mounting-manual-cancel').handlers.click();assert.equal(e.manualMounting,null);same(e.board.mountingHoles,original);assert.equal(e.history.length,history);
  d.getElementById('mounting-manual').handlers.click();assert.ok(e.manualMounting);d.getElementById('mounting-manual').handlers.click();assert.equal(e.manualMounting,null);same(e.board.mountingHoles,original);
});
test('row and column parity are one based; same parity alone is insufficient for nonstandard pitch',()=>{
  const {e,d,pick}=fixture();d.getElementById('mounting-row-parity').value='odd';d.getElementById('mounting-column-parity').value='even';e.beginManualMounting();assert.equal(pick(0,0),false);assert.match(e.notices.at(-1)[0],/偶数列/);assert.equal(pick(1,1),false);assert.match(e.notices.at(-1)[0],/奇数行/);assert.equal(pick(1,0),true);assert.equal(pick(3,2),true);
  d.getElementById('mounting-row-parity').value='even';d.getElementById('mounting-row-parity').handlers.change();assert.match(d.getElementById('mounting-manual-status').textContent,/偶数行/);assert.equal(d.getElementById('mounting-manual-apply').disabled,true,'changing preference cannot silently keep an incompatible draft');e.cancelManualMounting();
  e.board={...e.board,widthMm:500,heightMm:400,pitchMm:20,edgeOffsetMm:20};d.getElementById('mounting-row-parity').value='any';d.getElementById('mounting-column-parity').value='any';e.beginManualMounting();assert.equal(pick(0,0),true);assert.equal(pick(1,0),false);assert.match(e.notices.at(-1)[0],/25 mm/);assert.equal(pick(5,0),true);assert.equal(pick(0,5),true);assert.equal(pick(5,5),true);assert.equal(e.applyManualMounting(),true);assert.equal(e.mountingIssues().length,0);
});
test('board edge, actual grid, thickness and nearby grid-hole material constraints reject bad holes',()=>{
  const {e,pick}=fixture();e.board.edgeOffsetMm=5;e.beginManualMounting();assert.equal(pick(0,0),false);assert.match(e.notices.at(-1)[0],/7.5 mm/);assert.equal(pick(2,2),true);assert.equal(pick(-1,2),false);assert.match(e.notices.at(-1)[0],/实际孔位/);assert.equal(pick(100,2),false);e.cancelManualMounting();
  e.board={...e.board,pitchMm:10,edgeOffsetMm:10};e.beginManualMounting();assert.equal(pick(2,2),false);assert.match(e.notices.at(-1)[0],/不足 2 mm/);e.cancelManualMounting();
  e.board={...e.board,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:8.49};e.beginManualMounting();assert.equal(e.manualMounting,null);assert.match(e.notices.at(-1)[0],/8.5 mm/);e.board.thicknessMm=8.5;e.beginManualMounting();assert.ok(e.manualMounting);assert.equal(pick(0,0),true);
  assert.equal(e.pickManualMounting({xMm:19,yMm:19}),false);assert.match(e.notices.at(-1)[0],/孔位附近/);
});
test('the whole counterbore disk uses only the exact brown contour, not blue base or screw estimates',()=>{
  const {e,pick}=fixture();const tiny={xMin:-1,yMin:-1,xMax:1,yMax:1};
  const place=(id,x,y,layout)=>{e.kits.set(id,{id,name:id,layout:{topViewUrl:'test.svg',widthMm:10,heightMm:10,anchorXMm:5,anchorYMm:5,baseBoundsMm:tiny,collisionBoundsMm:tiny,mountingHoleOffsetsMm:[],...layout}});e.instances=[{id,kitId:id,xMm:x,yMm:y,rotationDeg:0}];};
  place('contour',23,12.5,{collisionBoundsMm:{xMin:-5,yMin:-5,xMax:5,yMax:5}});e.beginManualMounting();assert.equal(pick(0,0),false,'disk tangent to real contour is obstructed');assert.match(e.notices.at(-1)[0],/遮挡/);e.cancelManualMounting();
  e.instances[0].xMm=23.01;e.beginManualMounting();assert.equal(pick(0,0),true,'positive contour clearance is usable');e.cancelManualMounting();
  place('base',12.5,12.5,{collisionBoundsMm:{xMin:15,yMin:15,xMax:20,yMax:20},baseBoundsMm:{xMin:-2,yMin:-2,xMax:2,yMax:2}});e.beginManualMounting();assert.equal(pick(0,0),true,'blue base outside brown silhouette does not block');e.cancelManualMounting();
  place('screw',50,12.5,{mountingHoleOffsetsMm:[{xMm:-28.7,yMm:0}],mountingHoleRadiusMm:3.3});e.beginManualMounting();assert.equal(pick(0,0),true,'mounting screw estimate outside brown silhouette does not block');e.cancelManualMounting();
  const contour=[[-20,-20],[20,-20],[20,20],[10,20],[10,-10],[-10,-10],[-10,20],[-20,20]].map(([xMm,yMm])=>({xMm,yMm}));place('concave',12.5,12.5,{collisionBoundsMm:{xMin:-20,yMin:-20,xMax:20,yMax:20},collisionPolygonsMm:[contour]});e.beginManualMounting();assert.equal(pick(0,0),true,'open notch inside silhouette bounding box remains usable');e.cancelManualMounting();e.instances[0].xMm=27.5;e.beginManualMounting();assert.equal(pick(0,0),false,'actual brown arm blocks the complete counterbore disk');e.cancelManualMounting();
});
test('counterbores need no extra two-millimeter wall but actual overlap and ordinary-hole wall stay enforced',()=>{
  const {e}=fixture();e.board={...e.board,pitchMm:11,edgeOffsetMm:12.5};assert.equal(e.mountingHoleClearanceError(h(0,0),[h(0,0),h(1,0)]),'','two 11-mm counterbores can touch without an extra 2-mm wall');e.board.pitchMm=10.999;assert.match(e.mountingHoleClearanceError(h(0,0),[h(0,0),h(1,0)]),/实际孔径重叠/);e.board.pitchMm=10;assert.match(e.mountingHoleClearanceError(h(0,0),[h(0,0)]),/普通孔.*2 mm/);e.board.pitchMm=12.5;assert.equal(e.mountingHoleClearanceError(h(0,0),[h(0,0),h(1,0)]),'');
});
test('stale board, instance and unsaved parameter changes cannot apply old draft',()=>{
  const {e,pick}=fixture();e.beginManualMounting();pick(0,0);pick(2,0);pick(0,2);pick(2,2);e.board.widthMm+=25;assert.equal(e.applyManualMounting(),false);assert.equal(e.manualMounting,null);same(e.board.mountingHoles,[]);assert.match(e.notices.at(-1)[0],/画布已改变/);
  e.beginManualMounting();e.instances.push({id:'new',kitId:'kit',xMm:112.5,yMm:112.5,rotationDeg:0});assert.equal(pick(0,0),false);assert.equal(e.manualMounting,null);
  e.beginManualMounting();e.boardFormDirty=true;assert.equal(pick(0,0),false);assert.equal(e.manualMounting,null);e.beginManualMounting();assert.equal(e.manualMounting,null);assert.match(e.notices.at(-1)[0],/更新面包板/);
});
test('imported duplicate saved holes cannot be re-applied as four distinct draft holes',()=>{
  const {e,d}=fixture();e.board.mountingHoles=[h(0,0),h(0,0),h(0,2),h(2,2)];e.beginManualMounting();assert.equal(d.getElementById('mounting-manual-apply').disabled,true,'four entries containing a duplicate are not four usable holes');assert.equal(e.applyManualMounting(),false);assert.equal(e.history.length,0);
});
test('manual keyboard prevents selected component edits; escape, enter and pan keep intended scope',()=>{
  const {e,d,click}=fixture();e.instances=[{id:'selected',kitId:'kit',xMm:112.5,yMm:112.5,rotationDeg:0}];e.setSelection(['selected']);e.beginManualMounting();const before=copy(e.instances),key=value=>({key:value,target:e.svg,preventDefault(){this.prevented=true}});e.handleKeydown(key('Delete'));e.handleKeydown(key('ArrowLeft'));same(e.instances,before,'manual keyboard does not edit components');
  const space=key(' ');e.handleKeydown(space);assert.equal(space.prevented,true);assert.equal(e.space,true);const pan=click(0,0);assert.equal(e.drag.mode,'pan');assert.equal(e.manualMounting.holes.length,0,'Space drag cannot select a hole');e.svg.handlers.pointerup({...pan,type:'pointerup'});e.space=false;
  click(0,0);click(2,0);click(0,2);click(2,2);e.handleKeydown(key('Enter'));assert.equal(e.manualMounting,null);assert.equal(e.board.mountingHoles.length,4);e.beginManualMounting();click(0,0);e.handleKeydown(key('Escape'));assert.equal(e.manualMounting,null);assert.equal(e.board.mountingHoles.length,4);
});
test('app auto/manual controls retain readonly and guest access and disable unsafe simultaneous requests',()=>{
  const {e,d}=fixture(),app=fs.readFileSync(path.join(root,'static/app.js'),'utf8'),start=app.indexOf('  function updateMountingButtons(){'),end=app.indexOf('  async function chooseMountingHoles(',start),state={session:{role:'readonly'},choosingMounting:false},context={state,editor:e,$:id=>d.getElementById(id)};vm.createContext(context);vm.runInContext(app.slice(start,end),context);
  for(const role of ['readonly','guest','admin','user']){state.session.role=role;context.updateMountingButtons();assert.equal(d.getElementById('mounting-manual').disabled,false,role+' can manually select');assert.equal(d.getElementById('mounting-auto').disabled,false);}
  state.choosingMounting=true;context.updateMountingButtons();assert.equal(d.getElementById('mounting-manual').disabled,true);state.choosingMounting=false;state.session.role='unauthenticated';context.updateMountingButtons();assert.equal(d.getElementById('mounting-manual').disabled,true);state.session.role='readonly';e.beginManualMounting();context.updateMountingButtons();assert.equal(d.getElementById('mounting-auto').disabled,true);assert.equal(d.getElementById('mounting-manual').disabled,false,'exit manual remains available');
});
(async()=>{
  const accountSource=fs.readFileSync(path.join(root,'test_account_cart_frontend.cjs'),'utf8'),accountHarness={require,__dirname:root,console};vm.createContext(accountHarness);vm.runInContext(accountSource.slice(0,accountSource.indexOf('\n(async()=>{'))+'\nglobalThis.createAccountFixture=fixture;',accountHarness);
  const f=accountHarness.createAccountFixture();await f.context.syncCartSession();await f.context.addAccountCart({},'已保存方案');f.editor.manualMounting={holes:[]};f.context.updateButtons();assert.equal(f.buttons[2].disabled,false,'independent saved cart still exports during new canvas manual draft');await f.context.exportList('bundle');assert.equal(f.service.requests.at(-1).path,'/cart/export?format=bundle');cases++;
  console.log(`${cases} manual mounting checks passed, including production pointer/render/history/geometry and persisted cart isolation.`);
})().catch(error=>{console.error(error);process.exitCode=1});
