'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const codec=require('../static/project-file.js');
const record={id:'source-l',revision:'r1',name:'L形板',widthMm:100,heightMm:80,thicknessMm:12,pitchMm:12.5,edgeOffsetMm:12.5,mountingHoleIds:['M1','M2']};
const catalog={version:'test-1',kits:[],registeredBoards:[record]};
const ref=()=>({registeredBoardId:'source-l',registeredBoardRevision:'r1'});
function project(board=ref()) {return codec.create({metadata:{name:'异形板工程'},catalogVersion:catalog.version,layout:{board:{widthMm:300,heightMm:225},subBoards:[{id:'plate',name:'L形板',board,xMm:20,yMm:20,rotationDeg:90}],instances:[]},optical:{},extras:[],moduleQuantities:[],ui:{selectedIds:[],view:null}},{catalog})}
test('portable registered board keeps exact source identity and mounting IDs',()=>{
  const p=project(),restored=codec.parse(JSON.stringify(p),{catalog}).project;
  assert.equal(restored.layout.subBoards[0].board.registeredBoardRevision,'r1');
  assert.deepEqual(restored.layout.subBoards[0].board.mountingHoles,[{holeId:'M1'},{holeId:'M2'}]);
  assert.equal(restored.layout.subBoards[0].board.widthMm,100);
  assert.ok(!('outlineMm' in restored.layout.subBoards[0].board));
  assert.deepEqual(project({...ref(),mountingHoles:[]}).layout.subBoards[0].board.mountingHoles,[]);
});
test('project rejects unknown revisions, forged geometry/assets and nonexistent mounting holes',()=>{
  for(const value of [{...ref(),registeredBoardId:'missing'},{...ref(),registeredBoardRevision:'old'},
    {...ref(),widthMm:101},{...ref(),outlineMm:[]},{...ref(),stepPath:'wrong.step'},
    {...ref(),mountingHoles:[{holeId:'T1'}]},{...ref(),mountingHoles:[{holeId:'M1'},{holeId:'M1'}]},
    {...ref(),mountingHoles:[{columnIndex:0,rowIndex:0}]},{registeredBoardId:'source-l'}])assert.throws(()=>project(value));
});
test('standalone registered-board projects remain reusable as source modules',()=>{
  const p=project();p.layout.board=p.layout.subBoards[0].board;delete p.layout.subBoards;
  const restored=codec.parse(p,{catalog,validateBoard:b=>b.registeredBoardId==='source-l'}).project;
  assert.equal(restored.layout.board.registeredBoardId,'source-l');
  const changed=structuredClone(catalog);changed.registeredBoards[0].revision='r2';
  assert.throws(()=>codec.parse(p,{catalog:changed}),e=>e.code==='registered_board_changed');
});
