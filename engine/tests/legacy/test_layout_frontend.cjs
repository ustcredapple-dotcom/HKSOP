const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const context={window:{},console};vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/static/layout.js','utf8'),context);
const Editor=context.window.BreadboardEditor;
const e=Object.create(Editor.prototype);
e.board={widthMm:350,heightMm:225,pitchMm:12.5,edgeOffsetMm:12.5,thicknessMm:12.7,holeType:'M6_through'};
e.kits=new Map([['asymmetric',{id:'asymmetric',name:'不对称套件',layout:{topViewUrl:'./topviews/example.svg',widthMm:50,heightMm:20,anchorXMm:20,anchorYMm:10,collisionBoundsMm:{xMin:-20,yMin:-10,xMax:30,yMax:10},baseBoundsMm:{xMin:-10,yMin:-8,xMax:10,yMax:8},mountingHoleOffsetsMm:[{xMm:-12.5,yMm:-12.5},{xMm:12.5,yMm:-12.5},{xMm:-12.5,yMm:12.5},{xMm:12.5,yMm:12.5}]}}]]);
const instance=(id,xMm,yMm,rotationDeg=0)=>({id,kitId:'asymmetric',xMm,yMm,rotationDeg});
const expected={0:[80,90,130,110],90:[90,80,110,130],180:[70,90,120,110],270:[90,70,110,120]};
for(const [angle,want]of Object.entries(expected)){const b=e.worldBounds(instance('a',100,100,Number(angle)));assert.deepEqual([b.xMin,b.yMin,b.xMax,b.yMax],want);}
e.instances=[instance('a',100,100),instance('b',150,100)];assert.equal(e.validation().valid,false,'edge contact invalid');assert.ok(e.validation().issues.some(i=>i.code==='collision'));
e.instances=[instance('a',100,100),instance('b',151,100)];assert.equal(e.validation().issues.filter(i=>i.code==='collision').length,0,'positive gap avoids collision');
e.instances=[instance('a',100,100),instance('b',140,100,90)];assert.equal(e.validation().valid,false,'rotated contact invalid');
e.instances=[instance('a',100,100),instance('b',141,100,90)];assert.equal(e.validation().issues.filter(i=>i.code==='collision').length,0,'rotated gap avoids collision');
e.instances=[instance('a',100,100),instance('b',100,120)];assert.equal(e.validation().valid,false,'horizontal edge contact invalid');
e.instances=[instance('a',100,100),instance('b',150,120)];assert.equal(e.validation().valid,false,'corner contact invalid');
e.instances=[instance('a',100,100),instance('b',151,121)];assert.equal(e.validation().issues.filter(i=>i.code==='collision').length,0);
e.instances=[instance('a',12.5,100)];assert.equal(e.validation().issues.filter(i=>i.code==='out_of_bounds').length,0,'upper body overhang allowed');e.instances=[instance('a',5,100)];assert.ok(e.validation().issues.some(i=>i.code==='out_of_bounds'));
e.instances=[instance('a',20,100)];assert.equal(e.validation().issues.filter(i=>i.code==='out_of_bounds').length,0,'exact board edge permitted');
e.instances=[instance('a',100,100)];assert.equal(e.validation().valid,true,'default four holes aligned');e.board.pitchMm=25;e.instances=[instance('a',112.5,112.5)];assert.ok(e.validation().issues.some(i=>i.code==='mounting_mismatch'));e.board.pitchMm=12.5;
assert.ok(e.validBoard(e.board));assert.equal(e.validBoard({...e.board,pitchMm:6}),null);assert.equal(e.validBoard({...e.board,widthMm:3000,heightMm:3000,pitchMm:12.5}),null);assert.equal(e.validBoard({...e.board,thicknessMm:2}),null);assert.ok(e.validBoard({...e.board,holeType:'plain_through',holeDiameterMm:3,pitchMm:5,edgeOffsetMm:5,widthMm:100,heightMm:100}));
console.log('Frontend geometry: 4 rotations, edge/corner contact, gaps, bounds, and board constraints passed.');

// Arbitrary concave contours must use their actual interior, not their bounding box or convex hull.
const point=(xMm,yMm)=>({xMm,yMm});
const square=(left,bottom,right,top)=>[point(left,bottom),point(right,bottom),point(right,top),point(left,top)];
const kit=(id,polygons,base={xMin:-2,yMin:-2,xMax:2,yMax:2})=>({id,name:id,layout:{topViewUrl:'./test.svg',widthMm:50,heightMm:50,anchorXMm:25,anchorYMm:25,collisionBoundsMm:{xMin:-25,yMin:-25,xMax:25,yMax:25},collisionPolygonsMm:polygons,baseBoundsMm:base,mountingHoleOffsetsMm:[point(0,0)]}});
e.kits.set('concave',kit('concave',[[point(-20,-20),point(20,-20),point(20,-10),point(-10,-10),point(-10,20),point(-20,20)]]));
e.kits.set('small',kit('small',[square(-4,-4,4,4)]));
const placed=(id,kitId,xMm=100,yMm=100,rotationDeg=0)=>({id,kitId,xMm,yMm,rotationDeg});
const collides=()=>e.validation().issues.some(i=>i.code==='collision');
for(const rotationDeg of [0,90,180,270]){
  e.instances=[placed('concave','concave',100,100,rotationDeg),placed('small','small')];
  assert.equal(collides(),false,`concave cavity remains open at ${rotationDeg}`);
  const arm=e.worldPoint(e.instances[0],point(-15,0));e.instances[1]=placed('small','small',arm.xMm,arm.yMm);assert.equal(collides(),true,`concave arm collides at ${rotationDeg}`);
}
e.kits.set('cross-h',kit('cross-h',[square(-20,-2,20,2)]));e.kits.set('cross-v',kit('cross-v',[square(-2,-20,2,20)]));
e.instances=[placed('h','cross-h'),placed('v','cross-v')];assert.ok(collides(),'crossed polygon edges without contained vertices collide');
e.kits.set('two-islands',kit('two-islands',[square(-20,-20,-10,20),square(10,-20,20,20)]));
e.instances=[placed('islands','two-islands'),placed('small','small')];assert.equal(collides(),false,'gap between disjoint polygons remains open');e.instances[1].xMm=106;assert.equal(collides(),true,'contact against one island detected');
e.instances=[placed('a','small',12.5,100)];e.kits.get('small').layout.collisionPolygonsMm=[square(-30,-4,30,4)];assert.equal(e.outOfBounds(e.instances[0]),false,'upper body may overhang when base stays within board');
e.instances[0].xMm=1;assert.equal(e.outOfBounds(e.instances[0]),true,'base overhang stays invalid');
e.viewport={clientWidth:600,clientHeight:300};e.render=()=>{};e.fit();const content=e.contentBounds();assert.ok(e.view.x<=content.xMin&&e.view.x+e.view.w>=content.xMax,'fit includes horizontal overhang');assert.ok(e.view.y<=e.board.heightMm-content.yMax&&e.view.y+e.view.h>=e.board.heightMm-content.yMin,'fit includes vertical overhang');

// Mounting holes retain exact grid indices, have 25 mm alignment, and become invalid when a part obscures one.
e.board=e.normalizeBoard({...e.board,mountingHoles:[{columnIndex:0,rowIndex:0},{columnIndex:26,rowIndex:0},{columnIndex:26,rowIndex:16},{columnIndex:0,rowIndex:16}]});e.instances=[];assert.equal(e.mountingIssues().length,0);assert.equal(e.mountingPositions()[2].xMm,337.5);assert.equal(e.mountingPositions()[2].yMm,212.5);
e.board.thicknessMm=8;assert.ok(e.mountingIssues().some(i=>i.code==='board_mounting_invalid'));e.board.thicknessMm=12.7;
e.instances=[placed('cover','small',12.5,12.5)];assert.ok(e.mountingIssues().some(i=>i.code==='mounting_hole_obstructed'&&i.holeIds.includes('H1')));
e.instances=[placed('cover','small',75,75)];assert.equal(e.mountingIssues().length,0,'moving away restores selected holes without rearranging');
e.board.mountingHoles[1].columnIndex=25;assert.ok(e.mountingIssues().some(i=>i.code==='board_mounting_invalid'),'all pairwise X differences must be multiples of 25');
e.board.mountingHoles=[];assert.equal(e.mountingIssues().length,0,'board without counterbores remains supported');
assert.equal(e.validBoard({...e.board,mountingHoles:[{columnIndex:0,rowIndex:0}]}),null);assert.equal(e.validBoard({...e.board,mountingHoles:[{columnIndex:'0',rowIndex:0},{columnIndex:2,rowIndex:0},{columnIndex:2,rowIndex:2},{columnIndex:0,rowIndex:2}]}),null);

const catalog=JSON.parse(fs.readFileSync(__dirname+'/catalog.json','utf8'));const actual=Object.create(Editor.prototype);actual.board=e.normalizeBoard({...e.board,mountingHoles:[]});actual.kits=new Map(catalog.kits.map(k=>[k.id,k]));actual.instances=[placed('pbs','pbs-adjustable',37.5,187.5,270),placed('motor','motor-05-45',37.5,137.5,90)];assert.equal(actual.validation().valid,true,JSON.stringify(actual.validation()));assert.ok(actual.instances.some(i=>actual.worldBounds(i).xMin<0),'real fixture upper body overhangs left edge');assert.ok(actual.worldBounds(actual.instances[0],'base').xMin>0,'real fixture base remains inside');assert.ok(actual.boundaryMarkup(actual.instances[0]).includes('<polygon'),'actual outline drawn as polygon');
console.log('Fine contours: concavity, disjoint loops, edge crossings, 4 rotations, overhang fit, mounting obstruction, and source screenshot regression passed.');

actual.instances[1].yMm=162.5;assert.ok(actual.validation().issues.some(i=>i.code==='collision'),'real fixture overlap still detected by fine contours');
