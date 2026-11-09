'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const body=source.slice(source.indexOf('  function prepareSavedLayout('),source.indexOf('  function updateQuantities('));
const R=require('../static/registered-boards.js');
function fixture(blockBackup=false){
  const key='draft',raw=JSON.stringify({version:2,layout:{board:{registeredBoardId:'old',registeredBoardRevision:'R0'},instances:[]},metadata:{name:'Original'},extras:[{name:'Keep'}]});
  const storage=new Map([[key,raw]]),notice={hidden:true,querySelector(){return{addEventListener(){}}}};
  const ctx={savedLayout:JSON.parse(raw).layout,savedProjectUI:{view:{x:2}},savedOpticalRendering:{visible:true},state:{project:{name:'Original'},optical:{a:1},extras:[{name:'Keep'}],moduleQuantities:new Map([['x',2]])},STORAGE_KEY:key,window:{ZZLabRegisteredBoards:R},escape:String,$:()=>notice,newProjectMetadata:()=>({name:'Empty'}),localStorage:{getItem:k=>storage.get(k)||null,setItem(k,v){if(blockBackup)throw Error('Quota');storage.set(k,v)}},Date};
  vm.createContext(ctx);vm.runInContext(body,ctx);return{ctx,storage,raw,notice};
}
test('obsolete board revision preserves original bytes before starting a clean canvas',()=>{
  const{ctx,storage,raw,notice}=fixture();ctx.prepareSavedLayout({registeredBoards:[]});
  assert.equal(storage.get('draft'),raw);assert.equal([...storage].filter(([k,v])=>k.startsWith('draft.recovery.')&&v===raw).length,1);
  assert.equal(ctx.savedLayout,null);assert.equal(ctx.state.autosavePaused,false);assert.equal(notice.hidden,false);assert.match(notice.innerHTML,/下载原草稿备份/);
});
test('full storage never permits autosave to overwrite the unbacked-up original',()=>{
  const{ctx,storage,raw}=fixture(true);ctx.prepareSavedLayout({registeredBoards:[]});assert.equal(ctx.state.autosavePaused,true);assert.equal(storage.size,1);assert.equal(storage.get('draft'),raw);
});
test('ordinary valid draft passes through without backup or configuration loss',()=>{
  const{ctx,storage}=fixture();ctx.savedLayout={board:{widthMm:300,heightMm:200},instances:[]};const before=ctx.savedLayout;ctx.prepareSavedLayout({registeredBoards:[]});
  assert.equal(ctx.savedLayout,before);assert.equal(ctx.state.project.name,'Original');assert.equal(storage.size,1);assert.equal(ctx.state.autosavePaused,undefined);
});
