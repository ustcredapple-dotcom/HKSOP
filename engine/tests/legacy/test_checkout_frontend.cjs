'use strict';
// Exercise production cart/render/export functions with an instrumented DOM and network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
const section=(from,to)=>{const start=source.indexOf(from),end=source.indexOf(to,start);assert.ok(start>=0&&end>start);return source.slice(start,end)};
const clone=value=>JSON.parse(JSON.stringify(value));
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const row=(componentId,kind,quantity=1)=>({componentId,kind,name:'器件 '+componentId,model:'MODEL-'+componentId,quantity,unit:'个',kits:[{kitId:'module',name:'模块',kitQuantity:1,perKitQuantity:quantity,quantity}],status:'已核对',stepPath:kind==='manufacturing'?'part.step':null,drawingPath:kind==='manufacturing'?'part.pdf':null});
function fixture(){
  const elements=new Map(),inputs=[],requests=[],downloads=[],notices=[];
  const element=id=>({id,dataset:{},value:'',hidden:false,disabled:false,checked:false,indeterminate:false,textContent:'',innerHTML:'',attributes:{},classList:{toggle(){}},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},querySelector(){return this.child||(this.child=element('child'))},focus(){document.activeElement=this},scrollIntoView(){},after(){}});
  const $=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id)};
  const buttons=['lubang','manufacturing','bundle'].map(kind=>Object.assign(element(kind),{dataset:{export:kind}}));
  const document={activeElement:null,body:{append(){}},getElementById:$,querySelector:()=>buttons[2],querySelectorAll:selector=>selector==='[data-export]'?buttons:selector==='[data-checkout-quantity]'?inputs:[],createElement:tag=>({...element(tag),click(){downloads.push({name:this.download})},remove(){}})};
  const preview={lubang:[row('optic','lubang',3)],manufacturing:[row('post','manufacturing',2),{...row('board','manufacturing'),name:'参数面包板',unit:'块',generatedBoard:true}],standard:[row('screw','standard',4)],reviewGroups:[],items:[{kitId:'module',quantity:1}],totals:{kits:1,componentTypes:4},layoutValidation:{valid:true}};
  const state={preview,checkout:new Map(),checkoutRevision:0,resultSource:'module',moduleRevision:2,previewModuleRevision:2,revision:7,previewRevision:7,quantities:new Map([['module',1]]),kits:new Map([['module',{name:'模块',bundleStatus:'blocked'}]]),resultRequest:{catalogVersion:'fixture',items:[{kitId:'module',quantity:1}]},session:{role:'guest'}};
  const editor={boardFormDirty:false,validation:()=>({valid:true})};
  const context={state,editor,document,$,escape,deepCopy:clone,window:{confirm:()=>true,matchMedia:()=>({matches:true})},clearTimeout(){},textValue:v=>Array.isArray(v)?v.join('；'):String(v??''),link:()=>'',Set,Map,Array,Number,JSON,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout(){},sharedLibrary:null,updateMountingButtons(){},flushOpticalInputs(){},notify:(...args)=>notices.push(args),fetchAPI:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return{blob:async()=>({file:true}),headers:{get:()=>null}}}};
  vm.createContext(context);
  vm.runInContext(section('  function statusInfo(','  function bundleNote(')+section('  function signedInCartSession(','  async function generate() {')+section('  function downloadName(','  function normalizedSession(')+section('  function updateButtons() {','  function renderFilters()'),context);
  context.renderResults(preview);context.updateButtons();
  return{context,state,editor,document,$,inputs,requests,downloads,notices,buttons};
}
(async()=>{
  {
    const f=fixture(),c=f.context;assert.equal(c.checkoutPayload().items.length,4);assert.equal(f.$('checkout-select-all').checked,true);assert.ok(f.buttons.every(b=>!b.disabled),'old blanket kit status cannot block complete chosen files');
    assert.match(f.$('lubang-table').innerHTML,/data-checkout-select="optic"/);assert.match(f.$('manufacturing-table').innerHTML,/材料与表面处理/);assert.match(f.$('checkout-summary').textContent,/9 个、1 块/);assert.match(f.$('results-summary').textContent,/本次导出以勾选项目为准/);
    const before=clone(f.state.resultRequest),revision=f.state.revision,moduleRevision=f.state.moduleRevision;
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'8',setAttribute(){}}});
    c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:false}});c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:true}});
    assert.equal(f.state.checkout.get('optic').quantity,'8','unchecked custom quantity survives');assert.equal(f.$('checkout-select-all').checked,true);assert.match(f.$('checkout-summary').textContent,/14 个、1 块/);
    c.checkoutAction('remove','post');assert.equal(c.checkoutPayload().items.some(item=>item.componentId==='post'),false);assert.match(f.$('checkout-removed-list').innerHTML,/器件 post/);assert.equal(f.state.checkout.get('post').selected,false,'removal clears selection immediately');assert.doesNotMatch(f.$('manufacturing-table').innerHTML,/data-checkout-select="post"/,'removed items cannot be checked before restoration');
    const staleCheckbox={dataset:{checkoutSelect:'post'},checked:true,disabled:false};c.onCheckoutChange({target:staleCheckbox});assert.equal(staleCheckbox.checked,false);assert.equal(staleCheckbox.disabled,true);assert.equal(f.state.checkout.get('post').selected,false,'a delayed change event cannot reselect a removed item');
    c.onCheckoutChange({target:{dataset:{checkoutGroup:'manufacturing'},checked:true}});c.onCheckoutChange({target:{id:'checkout-select-all',dataset:{},checked:true}});assert.equal(f.state.checkout.get('post').selected,false,'group and global selection omit removed rows');
    c.checkoutAction('restore','post');assert.equal(c.checkoutPayload().items.find(item=>item.componentId==='post').quantity,2);assert.equal(f.state.checkout.get('post').selected,true);assert.match(f.$('manufacturing-table').innerHTML,/data-checkout-select="post"[^>]* checked/,'explicit restoration makes the row selectable again');
    c.onCheckoutChange({target:{dataset:{checkoutSelect:'board'},checked:false}});
    for(const format of ['lubang','manufacturing','bundle'])await c.exportList(format);
    assert.equal(f.requests.length,3);for(const request of f.requests){assert.equal(request.body.checkout.items.find(item=>item.componentId==='optic').quantity,8);assert.equal(request.body.checkout.items.some(item=>item.componentId==='board'),false);assert.deepEqual(request.body.items,before.items);}
    assert.equal(f.state.revision,revision);assert.equal(f.state.moduleRevision,moduleRevision);assert.deepEqual(clone(f.state.resultRequest),before,'cart edits do not modify engineering payload');
  }
  {
    const f=fixture(),c=f.context;
    for(const invalid of ['', '0','-1','1.5','10000001','1e3','Infinity']){
      c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:invalid,setAttribute(){}}});assert.equal(c.checkoutValid(),false,invalid);assert.ok(f.buttons.every(b=>b.disabled));await c.exportList('bundle');assert.equal(f.requests.length,0);
    }
    c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:false}});assert.equal(c.checkoutValid(),true,'an invalid unchecked row is not exported');await c.exportList('bundle');assert.equal(f.requests.length,1);
    c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:true}});assert.equal(f.buttons[2].disabled,true);
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'10000000',setAttribute(){}}});assert.equal(c.checkoutValid(),true);
  }
  {
    const f=fixture(),c=f.context;
    c.onCheckoutChange({target:{id:'checkout-select-all',dataset:{},checked:false}});assert.equal(f.$('checkout-summary').textContent,'已勾选 0 / 4 种器件');assert.ok(f.buttons.every(b=>b.disabled));await c.exportList('bundle');assert.equal(f.requests.length,0);
    c.onCheckoutChange({target:{dataset:{checkoutGroup:'standard'},checked:true}});assert.equal(f.$('checkout-select-all').indeterminate,true);assert.equal(f.buttons[0].disabled,true,'other suppliers are not placed into the Lubang website template');assert.equal(f.buttons[1].disabled,true);assert.equal(f.buttons[2].disabled,false);
    c.checkoutAction('remove-selected');assert.equal(c.checkoutPayload().items.length,0);assert.equal(f.state.checkout.get('screw').selected,false);c.checkoutAction('restore-all');assert.equal(c.checkoutPayload().items.length,1,'restoring removed items does not reselect visible unchecked items');
    c.checkoutAction('defaults');assert.equal(c.checkoutPayload().items.length,4);assert.equal(f.$('checkout-select-all').checked,true);
  }
  {
    const f=fixture(),c=f.context;f.state.preview.reviewGroups=[{id:'sourceFiles',title:'资料核验',blocking:true,blockedExports:['bundle'],items:[{code:'missing',summary:'支架缺少 STEP',componentIds:['post'],blocking:true,blockedExports:['bundle']}]}];
    c.checkoutChanged();assert.equal(f.buttons[2].disabled,true);assert.equal(f.buttons[1].disabled,false);
    c.checkoutAction('remove','post');assert.equal(f.buttons[2].disabled,false);assert.equal(f.$('bundle-blocked-note').hidden,true);await c.exportList('bundle');assert.equal(f.requests.length,1);
    c.checkoutAction('restore','post');assert.equal(f.buttons[2].disabled,true);
    f.state.preview.lubang[0].componentIds=['optic-source','extra-source'];f.state.preview.reviewGroups=[{id:'procurement',items:[{componentIds:['extra-source'],summary:'merged model pending',blocking:false}]}];c.checkoutChanged();assert.match(f.$('result-warnings').innerHTML,/merged model pending/);c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:false}});assert.equal(f.$('result-warnings').hidden,true);
  }
  {
    const f=fixture(),c=f.context;const input={dataset:{checkoutQuantity:'optic'},value:'11',setAttribute(){}};f.inputs.push(input);
    await c.exportList('bundle');assert.equal(f.requests[0].body.checkout.items.find(item=>item.componentId==='optic').quantity,11,'focused value flushes before download even without blur/input event');
    input.value='';await c.exportList('bundle');assert.equal(f.requests.length,1,'invalid focused value cannot escape final validation');
  }
  {
    const f=fixture(),c=f.context;let resolve;c.fetchAPI=(path,options)=>{f.requests.push({path,body:JSON.parse(options.body)});return new Promise(r=>resolve=r)};
    const pending=c.exportList('bundle');assert.equal(f.state.exporting,true);c.checkoutAction('remove','post');assert.equal(f.state.checkout.get('post').removed,false,'download snapshot cannot change under an active request');
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'post'},value:'19',setAttribute(){}}});assert.equal(f.state.checkout.get('post').quantity,'2');await c.exportList('lubang');assert.equal(f.requests.length,1);
    resolve({blob:async()=>({file:true}),headers:{get:()=>null}});await pending;assert.equal(f.state.exporting,false);
  }
  {
    const f=fixture(),c=f.context;c.checkoutAction('remove','post');c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'7',setAttribute(){}}});c.renderResults(f.state.preview);assert.equal(f.state.checkout.get('post').removed,false);assert.equal(f.state.checkout.get('optic').quantity,'3','a fresh generation restores design defaults');
    f.state.resultSource='layout';f.editor.validation=()=>({valid:false});c.updateButtons();assert.ok(f.buttons.every(b=>b.disabled));await c.exportList('bundle');assert.equal(f.requests.length,0,'cart selection never bypasses layout validity');
    f.editor.validation=()=>({valid:true});f.state.revision++;c.updateButtons();assert.ok(f.buttons.every(b=>b.disabled));await c.exportList('bundle');assert.equal(f.requests.length,0,'stale design cannot export an old review');
  }
  {
    const f=fixture(),c=f.context;f.state.preview.lubangImport={blocked:[{componentId:'optic',name:'型号待核对器件',model:'ALIAS-1',quantity:3,reason:'原装配别名未确认'}]};c.checkoutChanged();assert.equal(f.buttons[0].disabled,true);assert.equal(f.buttons[2].disabled,false);assert.match(f.$('lubang-import-note').innerHTML,/已勾选 1 项型号待确认/);await c.exportList('lubang');assert.equal(f.requests.length,0);await c.exportList('bundle');assert.equal(f.requests.length,1);assert.ok(f.notices.some(([message])=>/1 项型号待确认采购将另列/.test(message)));c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'7',setAttribute(){}}});assert.match(f.$('lubang-import-note').innerHTML,/× 7/);c.onCheckoutChange({target:{dataset:{checkoutSelect:'optic'},checked:false}});assert.equal(c.selectedLubangImportBlocked().length,0);assert.doesNotMatch(f.$('lubang-import-note').innerHTML,/已勾选 1 项/);
  }
  {
    const f=fixture(),c=f.context;const malicious={...row('x" onfocus="bad','lubang'),name:'<script>bad</script>'};f.state.preview.lubang=[malicious];c.renderResults(f.state.preview);const html=f.$('lubang-table').innerHTML;assert.doesNotMatch(html,/<script>|onfocus="bad/);assert.match(html,/&lt;script&gt;/);
    f.state.session.role='unauthenticated';c.updateButtons();assert.ok(f.buttons.every(b=>b.disabled));
  }
  {
    const f=fixture(),c=f.context,validation={valid:true};f.editor.validation=()=>validation;c.updateButtons();assert.equal(f.buttons[2].disabled,false);
    f.state.session.canDownloadManufacturing=false;c.updateButtons();assert.equal(f.buttons[2].disabled,true,'download capability invalidates the cached button state');assert.equal(f.$('manufacturing-download-access-note').hidden,false);assert.match(f.buttons[2].querySelector('span').textContent,/图纸和模型下载需登录/);assert.equal(f.buttons[0].disabled,false);assert.equal(f.buttons[1].disabled,false);assert.equal(f.$('generate').disabled,false,'manufacturing permission does not prevent generating a guest list');assert.equal(f.$('save-layout-json').disabled,false);assert.equal(f.$('save-layout-svg').disabled,false);
    await c.exportList('bundle');assert.equal(f.requests.length,0);await c.exportList('lubang');await c.exportList('manufacturing');assert.equal(f.requests.length,2);assert.equal(f.buttons[2].disabled,true,'export completion never restores a forbidden ZIP');
    f.state.session.canDownloadManufacturing=true;c.updateButtons();assert.equal(f.buttons[2].disabled,false);assert.equal(f.$('manufacturing-download-access-note').hidden,true);assert.equal(f.buttons[2].attributes['aria-describedby'],undefined);assert.equal(f.buttons[2].querySelector('span').textContent,'结算并导出所选资料包');
  }
  console.log('Checkout UI: selected/default/removed rows, editable quantities and live unit totals, last-input validation, individual/ZIP payload equality, original geometry isolation, selected-file blockers, empty/category eligibility, merged reviews, request snapshot, stale-layout blocking, regenerate reset and escaping passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
