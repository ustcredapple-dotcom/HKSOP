'use strict';
// Use the production snapping/validation engine and real purchased-laser catalog entry.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const harnessSource=fs.readFileSync(path.join(root,'test_layout_performance_frontend.cjs'),'utf8');
const harness={require,__dirname:root,console};
vm.createContext(harness);
vm.runInContext(harnessSource.slice(0,harnessSource.indexOf('{\n  const f=fixture(),e=f.editor'))+'\nglobalThis.createEnvironment=environment;',harness);
const catalog=JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8'));
const laser=catalog.kits.find(kit=>kit.id==='laser-308nm');
assert.ok(laser,'laser is available in the real catalog');
let checks=0;
for(const pitch of [12.5,25])for(const rotation of [0,90,180,270]){
  const {Editor}=harness.createEnvironment();
  const editor=new Editor({catalog,saved:{board:{widthMm:625,heightMm:625,pitchMm:pitch,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},instances:[]},notify(){}});
  const pose={id:'laser',kitId:'laser-308nm',rotationDeg:rotation};
  assert.equal(editor.anchorGrid(pose).compatible,true,`mounting pattern supports ${pitch} mm at ${rotation}°`);
  Object.assign(pose,editor.snap(310,310,pose));
  editor.instances=[pose];
  for(const hole of laser.layout.mountingHoleOffsetsMm){
    const world=editor.worldPoint(pose,hole);
    for(const coordinate of [world.xMm,world.yMm]){
      const grid=(coordinate-12.5)/pitch;
      assert.ok(Math.abs(grid-Math.round(grid))<1e-6,`all screws snap to board holes: ${pitch} mm / ${rotation}°`);
    }
  }
  const valid=editor.validation();
  assert.equal(valid.valid,true,JSON.stringify(valid.issues));
  assert.equal(valid.mountingAlignment[0].alignedCount,4);
  assert.equal(valid.mountingAlignment[0].requiredCount,2);
  pose.xMm+=1;
  assert.ok(editor.validation().issues.some(issue=>issue.code==='mounting_mismatch'),'a small unsnapped shift remains invalid');
  Object.assign(pose,editor.snap(pose.xMm,pose.yMm,pose));
  assert.equal(editor.validation().valid,true,'dragging restores an allowed mounting pose');
  checks++;
}
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(pitch=31.25,kits=catalog.kits,width=625,height=625){const env=harness.createEnvironment();const editor=new env.Editor({catalog:{kits:clone(kits)},saved:{board:{widthMm:width,heightMm:height,pitchMm:pitch,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through',mountingHoles:[]},instances:[]},notify(){}});return{...env,editor}}
const synthetic=(holes,minimum=2)=>({id:'test',name:'Test',layout:{topViewUrl:'test.svg',widthMm:20,heightMm:20,anchorXMm:10,anchorYMm:10,baseBoundsMm:{xMin:-5,yMin:-5,xMax:5,yMax:5},collisionBoundsMm:{xMin:-5,yMin:-5,xMax:5,yMax:5},mountingHoleOffsetsMm:holes,...(minimum==null?{}:{minimumAlignedMountingHoles:minimum})}});
const point=(xMm,yMm)=>({xMm,yMm});
for(const rotation of [0,90,180,270]){
 const {editor:e}=fixture(),pose={id:'partial',kitId:laser.id,rotationDeg:rotation};Object.assign(pose,e.snap(310,310,pose));e.instances=[pose];
 assert.equal(e.anchorGrid(pose).compatible,true);assert.equal(e.anchorGrid(pose).fullyCompatible,false);
 const v=e.validation();assert.equal(v.valid,true,JSON.stringify(v.issues));assert.equal(v.mountingAlignment[0].alignedCount,2);assert.equal(v.mountingAlignment[0].partial,true);
 const markers=e.mountingMarkerMarkup(pose);assert.equal((markers.match(/data-aligned="true"/g)||[]).length,2);assert.equal((markers.match(/data-aligned="false"/g)||[]).length,2);
 e.render();const node=e._scene.partNodes.get(pose.id),image=node.image;pose.xMm+=1;e.render();assert.equal(e.validation().valid,false);assert.equal((node.mountingMarkers.innerHTML.match(/data-aligned="true"/g)||[]).length,0,'marker state changes with actual pose');Object.assign(pose,e.snap(pose.xMm,pose.yMm,pose));e.render();assert.equal(node.image,image,'alignment repaint retains image nodes');
 e.setSelection([pose.id]);e.rotate();assert.equal(e.validation().valid,true,'rotation reselects the real two-hole phase');e.position(317,302,rotation);assert.equal(e.validation().valid,true,'inspector position uses same phase candidates');
 const packet=e.selectionPacket(),copies=e.pastePacket(packet),copy=e.instances.find(i=>i.id===copies.ids[0]);assert.equal(e.mountingAlignment(copy).alignedCount,2,'paste preserves partial alignment');assert.deepEqual(Object.keys(copy).sort(),['id','kitId','rotationDeg','xMm','yMm'],'alignment metadata never leaks into poses');checks++;
}
{
 const {editor:e}=fixture(30),pose={id:'one',kitId:laser.id,rotationDeg:0};Object.assign(pose,e.snap(310,310,pose));e.instances=[pose];const row=e.validation().mountingAlignment[0];assert.equal(row.alignedCount,1);assert.equal(row.partial,true);assert.ok(e.validation().issues.some(i=>i.code==='mounting_mismatch'),'one aligned hole is insufficient');checks++;
}
{
 const {editor:e}=fixture(25,[synthetic([point(0,0),point(25,0),point(0,25),point(5,5)])]);const pose={id:'prefer-more',kitId:'test',rotationDeg:0};Object.assign(pose,e.snap(107.5,107.5,pose));assert.equal(e.mountingAlignment(pose).alignedCount,3,'more aligned holes beat a nearer one-hole phase');checks++;
}
{
 const {editor:e}=fixture(25,[synthetic([point(0,0),point(0,25),point(5,5),point(30,5)])]);const pose={id:'no-fake-phase',kitId:'test',rotationDeg:0};Object.assign(pose,e.snap(112.5,107.5,pose));assert.equal(e.mountingAlignment(pose).alignedCount,2,'cannot combine unrelated X and Y phases');assert.ok(pose.xMm!==112.5||pose.yMm!==107.5);checks++;
}
{
 const {editor:e}=fixture(25,[synthetic([point(0,0),point(0,0)])]),pose={id:'duplicate',kitId:'test',rotationDeg:0,xMm:112.5,yMm:112.5};e.instances=[pose];const result=e.validation();assert.equal(result.mountingAlignment[0].totalCount,1);assert.equal(result.mountingAlignment[0].requiredCount,2);assert.equal(result.valid,false,'two identical offsets do not become two fixing points');checks++;
}
{
 const ordinary=clone(laser);delete ordinary.layout.minimumAlignedMountingHoles;const {editor:e}=fixture(31.25,[ordinary]),pose={id:'ordinary',kitId:laser.id,rotationDeg:0};Object.assign(pose,e.snap(310,310,pose));e.instances=[pose];assert.equal(e.validation().mountingAlignment[0].requiredCount,4);assert.equal(e.validation().valid,false,'ordinary kits still require every hole');checks++;
}
{
 const {editor:e}=fixture(),pose={id:'policy-cache',kitId:laser.id,rotationDeg:0};Object.assign(pose,e.snap(310,310,pose));e.instances=[pose];assert.equal(e.validation().valid,true);e.kits.get(laser.id).layout.minimumAlignedMountingHoles=4;assert.equal(e.validation().valid,false,'in-place minimum changes invalidate cached validation');e.kits.get(laser.id).layout.minimumAlignedMountingHoles=2;assert.equal(e.validation().valid,true);pose.yMm=106.25;assert.equal(e.mountingAlignment(pose).alignedCount,1,'a coincident hole outside the board is not counted');checks++;
}
{
 const {editor:e}=fixture(25),pose={id:'pitch-change',kitId:laser.id,rotationDeg:0};Object.assign(pose,e.snap(310,310,pose));e.instances=[pose];e.board.pitchMm=31.25;Object.assign(pose,e.snap(pose.xMm,pose.yMm,pose));assert.equal(e.validation().valid,true);assert.equal(e.mountingAlignment(pose).alignedCount,2);e.board.pitchMm=25;Object.assign(pose,e.snap(pose.xMm,pose.yMm,pose));assert.equal(e.mountingAlignment(pose).alignedCount,4);checks++;
}
{
 const kit=synthetic([point(0,0),point(0,25),point(5,5),point(30,5)]),{editor:e}=fixture(25,[kit],350,225);
 const a={id:'a',kitId:'test',xMm:112.5,yMm:112.5,rotationDeg:0},b={id:'b',kitId:'test',xMm:157.5,yMm:132.5,rotationDeg:0};e.instances=[a,b];const relative=[b.xMm-a.xMm,b.yMm-a.yMm];e.setSelection(['a','b']);e.move(10,10);assert.deepEqual([b.xMm-a.xMm,b.yMm-a.yMm],relative);assert.ok(e.instances.every(i=>e.mountingAlignment(i).alignedCount>=2),'one shared phase keeps different mounting classes aligned');const packet=e.selectionPacket(),copies=e.pastePacket(packet),pasted=copies.ids.map(id=>e.instances.find(i=>i.id===id));assert.deepEqual([pasted[1].xMm-pasted[0].xMm,pasted[1].yMm-pasted[0].yMm],relative);assert.ok(pasted.every(i=>e.mountingAlignment(i).alignedCount>=2));checks++;
}
console.log(`${checks} laser and minimum-hole alignment checks passed`);
