'use strict';
// Production account-cart hooks against an in-memory server with revision and account checks.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const fixtureSource=fs.readFileSync(__dirname+'/test_checkout_frontend.cjs','utf8'),harness={require,__dirname,console};vm.createContext(harness);vm.runInContext(fixtureSource.slice(0,fixtureSource.indexOf('(async()=>{'))+'\nglobalThis.makeCartFixture=fixture;',harness);
const app=fs.readFileSync(__dirname+'/static/app.js','utf8'),clone=x=>JSON.parse(JSON.stringify(x));
const section=(from,to)=>app.slice(app.indexOf(from),app.indexOf(to,app.indexOf(from)));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}};
const cartError=(code,status=409)=>Object.assign(new Error(code),{code,status});
function server(){
  let state={cartId:'account-A-cart',revision:0,updatedAt:null,items:[],sources:[],preview:{lubang:[],manufacturing:[],standard:[],reviewGroups:[],items:[],totals:{componentTypes:0,kits:0}}};
  const requests=[],accepted=new Map();
  const response=()=>clone(state);
  async function fetch(path,options){
    const body=options?.body?JSON.parse(options.body):null;requests.push({path,body});
    if(path==='/cart')return{json:async()=>response()};
    if(body.cartId!==state.cartId)throw cartError('cart_account_changed');
    if(path==='/cart/add'&&accepted.has(body.requestId))return{json:async()=>response()};
    if(body.revision!==state.revision)throw cartError('cart_conflict');
    if(path.startsWith('/cart/export?'))return{blob:async()=>({selected:response().items.filter(row=>row.selected&&!row.removed)}),headers:{get:()=>null}};
    if(path==='/cart/add'){
      accepted.set(body.requestId,true);state.sources.push({id:'source-'+state.sources.length,name:body.name});
      const incoming=body.payload.rows||[{componentId:'optic',name:'反射镜',kind:'lubang',model:'TEST',unit:'个',quantity:2}];
      for(const row of incoming){const old=state.preview[row.kind].find(r=>r.componentId===row.componentId),item=state.items.find(r=>r.componentId===row.componentId);
        if(old){old.baseQuantity+=row.quantity;old.quantity+=row.quantity;item.quantity+=row.quantity;}else{state.preview[row.kind].push({...clone(row),baseQuantity:row.quantity});state.items.push({componentId:row.componentId,quantity:row.quantity,selected:true,removed:false});}}
      state.preview.totals.componentTypes=state.items.length;state.preview.totals.kits=state.sources.length;
    }else if(path==='/cart/update'){
      // Keep this server stricter than the compatible production endpoint: the UI
      // must never rely on server repair for a selected-and-removed row.
      if(new Set(body.items.map(item=>item.componentId)).size!==body.items.length||body.items.some(item=>typeof item.selected!=='boolean'||typeof item.removed!=='boolean'||item.removed&&item.selected))throw cartError('invalid_cart_item',400);
      state.items=clone(body.items);for(const rows of [state.preview.lubang,state.preview.manufacturing,state.preview.standard])for(const row of rows)row.quantity=state.items.find(item=>item.componentId===row.componentId).quantity;
    }else if(path==='/cart/clear'){
      state.items=[];state.sources=[];state.preview={lubang:[],manufacturing:[],standard:[],items:[],reviewGroups:[],totals:{componentTypes:0,kits:0}};
    }else throw new Error(path);
    state.revision++;state.updatedAt='2026-09-27T00:00:00Z';return{json:async()=>response()};
  }
  return{fetch,requests,response,changeRevision(){state.revision++},switchAccount(){state={...state,cartId:'account-B-cart',revision:0,items:[],sources:[],preview:{lubang:[],manufacturing:[],standard:[],reviewGroups:[],totals:{componentTypes:0,kits:0}}}}};
}
function fixture(service=server()){
  const f=harness.makeCartFixture(),c=f.context;f.state.session={role:'readonly',canDownload:true};
  f.state.cart={mode:'loading',loaded:false,revision:0,cartId:null,updatedAt:null,sources:[],loading:false,saving:false,busy:false,dirty:false,error:'',conflict:false,editRevision:0,epoch:0,timer:null,savePromise:null,pendingAdd:null};f.state.project={name:'画布甲',notes:''};f.state.extras=[];f.state.moduleQuantities=new Map();
  f.state.preview=null;f.state.resultSource='layout';f.state.resultRequest=null;f.state.checkout=new Map();
  c.fetchAPI=service.fetch;c.notify=(...args)=>f.notices.push(args);c.payload=()=>({layout:{board:{widthMm:350,heightMm:225},instances:[]}});c.requestPersist=()=>{};c.deepCopy=clone;c.flushOpticalInputs=()=>{};c.setTimeout=()=>9;c.clearTimeout=()=>{};
  vm.runInContext(section('  function markChanged() {','  function updateButtons() {')+section('  async function generate() {','  function downloadName('),c);
  return{...f,service};
}
(async()=>{
  {
    const f=fixture(),c=f.context;await c.syncCartSession();assert.equal(f.state.cart.loaded,true);assert.equal(f.$('cart-empty').hidden,false);assert.equal(f.$('results').hidden,false);
    await c.generate();assert.equal(f.service.response().sources.length,1);assert.equal(f.state.resultSource,'cart');assert.equal(f.state.resultRequest,null);assert.equal(f.state.checkout.get('optic').quantity,'2');
    f.state.project.name='画布乙';await c.generate();assert.equal(f.service.response().sources.length,2);assert.equal(f.state.checkout.get('optic').quantity,'4','different canvas additions accumulate');assert.match(f.$('result-scope-note').textContent,/画布甲；画布乙/);
    const cartBefore=clone(f.service.response());f.state.quantities.clear();f.editor.validation=()=>({valid:false});f.editor.boardFormDirty=true;f.state.project.name='新的空画布';c.markChanged();c.markModuleChanged();assert.equal(f.$('stale-notice').hidden,true,'new invalid or cleared canvas cannot stale saved cart');c.updateButtons();assert.equal(f.buttons[0].disabled,false);assert.equal(f.buttons[2].disabled,false);await c.exportList('bundle');assert.equal(f.service.requests.at(-1).path,'/cart/export?format=bundle');assert.deepEqual(f.service.response(),cartBefore,'clear/change canvas leaves account cart unchanged');
    const other=fixture(f.service);await other.context.syncCartSession();assert.equal(other.state.checkout.get('optic').quantity,'4','fresh browser loads persisted quantities');assert.equal(other.state.cart.sources.length,2);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({rows:[{componentId:'optic',kind:'lubang',name:'镜片',quantity:2,unit:'片'},{componentId:'post',kind:'manufacturing',name:'底座',quantity:1,unit:'个'}]},'来源');
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'9',setAttribute(){}}});c.onCheckoutChange({target:{dataset:{checkoutSelect:'post'},checked:false}});assert.equal(f.state.cart.dirty,true);
    await c.exportList('lubang');assert.equal(f.service.requests.at(-2).path,'/cart/update');assert.equal(f.service.requests.at(-1).path,'/cart/export?format=lubang');assert.equal(f.service.requests.at(-1).body.revision,f.state.cart.revision,'export waits for saved revision');assert.deepEqual(f.service.response().items.map(i=>[i.componentId,i.quantity,i.selected]),[['optic',9,true],['post',1,false]]);
    c.checkoutAction('remove','optic');assert.equal(f.state.checkout.get('optic').selected,false);await c.flushAccountCart();assert.equal(f.state.cart.error,'');const reloaded=fixture(f.service);await reloaded.context.syncCartSession();assert.equal(reloaded.state.checkout.get('optic').removed,true);assert.equal(reloaded.state.checkout.get('optic').selected,false,'account reload cannot reselect a removed item');assert.equal(reloaded.state.checkout.get('post').selected,false);reloaded.context.checkoutAction('restore','optic');assert.equal(reloaded.state.checkout.get('optic').selected,true);assert.equal(reloaded.state.checkout.get('optic').quantity,'9');reloaded.context.checkoutAction('defaults');assert.equal(reloaded.state.checkout.get('optic').quantity,'2','reset uses original summed source quantity, not previously edited preview.quantity');
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'post'},value:'',setAttribute(){}}});const revision=f.state.revision;await c.clearCart();assert.equal(f.service.response().items.length,0);assert.equal(f.state.revision,revision,'clearing cart leaves canvas untouched');assert.equal(f.$('cart-empty').hidden,false);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({rows:[{componentId:'optic',kind:'lubang',name:'镜片',quantity:2,unit:'片'},{componentId:'post',kind:'manufacturing',name:'底座',quantity:1,unit:'个'}]},'删除并保存');const gate=deferred();let updates=0;
    c.fetchAPI=async(path,options)=>{if(path==='/cart/update'&&++updates===1)await gate.promise;return f.service.fetch(path,options)};
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'6',setAttribute(){}}});const saving=c.flushAccountCart();
    c.checkoutAction('remove','optic');assert.equal(f.state.checkout.get('optic').removed,true);assert.equal(f.state.checkout.get('optic').selected,false);assert.equal(c.cartControlsLocked(),false,'saving does not block continued cart edits');
    const stale={dataset:{checkoutSelect:'optic'},checked:true,disabled:false};c.onCheckoutChange({target:stale});c.onCheckoutChange({target:{dataset:{checkoutGroup:'lubang'},checked:true}});c.onCheckoutChange({target:{id:'checkout-select-all',dataset:{},checked:true}});assert.equal(stale.checked,false);assert.equal(stale.disabled,true);assert.equal(f.state.checkout.get('optic').selected,false);
    gate.resolve();await saving;assert.equal(updates,2,'deletion during an earlier save is persisted in the following revision');assert.deepEqual(f.service.response().items.find(item=>item.componentId==='optic'),{componentId:'optic',quantity:6,selected:false,removed:true});assert.equal(f.state.checkout.get('optic').removed,true,'the earlier save response does not undo optimistic removal');assert.equal(f.state.cart.error,'');assert.equal(f.state.cart.dirty,false);
    const reloaded=fixture(f.service);await reloaded.context.syncCartSession();assert.equal(reloaded.state.checkout.get('optic').removed,true);assert.equal(reloaded.state.checkout.get('optic').selected,false);assert.equal(reloaded.state.checkout.get('optic').quantity,'6');assert.equal(reloaded.state.checkout.get('post').selected,true);
    await c.exportList('bundle');assert.deepEqual(f.service.response().items.filter(item=>item.selected&&!item.removed).map(item=>item.componentId),['post']);assert.equal(f.service.requests.at(-1).path,'/cart/export?format=bundle');
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'删除后恢复');const gate=deferred();let updates=0;
    c.fetchAPI=async(path,options)=>{if(path==='/cart/update'&&++updates===1)await gate.promise;return f.service.fetch(path,options)};
    c.checkoutAction('remove','optic');const saving=c.flushAccountCart();c.checkoutAction('restore','optic');gate.resolve();await saving;assert.equal(updates,2);assert.deepEqual(f.service.requests.filter(request=>request.path==='/cart/update').map(request=>[request.body.items[0].selected,request.body.items[0].removed]),[[false,true],[true,false]],'explicit restore during a deletion save serializes a valid second state');assert.equal(f.state.checkout.get('optic').selected,true);assert.equal(f.state.checkout.get('optic').removed,false);assert.equal(f.service.response().items[0].removed,false);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({rows:[{componentId:'optic',kind:'lubang',name:'镜片',quantity:2,unit:'片'},{componentId:'post',kind:'manufacturing',name:'底座',quantity:1,unit:'个'},{componentId:'screw',kind:'standard',name:'螺钉',quantity:4,unit:'个'}]},'批量删除');c.onCheckoutChange({target:{dataset:{checkoutSelect:'post'},checked:false}});c.checkoutAction('remove-selected');await c.flushAccountCart();assert.deepEqual(f.service.response().items.map(item=>[item.componentId,item.selected,item.removed]),[['optic',false,true],['post',false,false],['screw',false,true]]);assert.equal(f.state.cart.error,'');
    const legacy=f.service.response();legacy.items[0].selected=true;c.applyAccountCart(legacy);assert.equal(f.state.checkout.get('optic').selected,false,'legacy contradictory saved state normalizes on load');assert.equal(f.state.checkout.get('optic').removed,true);assert.doesNotMatch(f.$('lubang-table').innerHTML,/data-checkout-select="optic"/);
    f.state.checkout.get('optic').selected=true;assert.equal(c.allCartItems().find(item=>item.componentId==='optic').selected,false,'outbound normalization remains defensive even against a stale in-memory flag');f.state.checkout.get('optic').selected=false;
    c.checkoutAction('restore-all');await c.flushAccountCart();assert.deepEqual(f.service.response().items.map(item=>[item.componentId,item.selected,item.removed]),[['optic',true,false],['post',false,false],['screw',true,false]],'restore-all restores only removed rows and preserves visible unchecked rows');
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'来源');const gate=deferred();let updates=0;
    c.fetchAPI=async(path,options)=>{if(path==='/cart/update'&&++updates===1){await gate.promise;}return f.service.fetch(path,options)};
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'3',setAttribute(){}}});const saving=c.flushAccountCart();assert.equal(f.state.cart.saving,true);
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'7',setAttribute(){}}});gate.resolve();await saving;assert.equal(updates,2,'edits during saving are serialized into a second revision');assert.equal(f.service.response().items[0].quantity,7);assert.equal(f.state.checkout.get('optic').quantity,'7');assert.equal(f.state.cart.dirty,false);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'来源');const gate=deferred();let first=true;c.fetchAPI=async(path,options)=>{if(path==='/cart/update'&&first){first=false;await gate.promise;}return f.service.fetch(path,options)};
    c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'3',setAttribute(){}}});const saving=c.flushAccountCart();c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'',setAttribute(){}}});gate.resolve();await assert.rejects(saving,/无效数量/);assert.equal(f.state.cart.error,'','temporarily empty typing during autosave must not lock editing behind reload');assert.equal(f.state.cart.dirty,true);c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'8',setAttribute(){}}});await c.flushAccountCart();assert.equal(f.service.response().items[0].quantity,8);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'来源');c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'5',setAttribute(){}}});f.service.changeRevision();await assert.rejects(c.flushAccountCart(),/cart_conflict/);assert.equal(f.state.cart.conflict,true);assert.equal(f.state.cart.dirty,true);assert.match(f.$('cart-save-status').textContent,/其他页面更新/);assert.equal(f.buttons[2].disabled,true);
    const count=f.service.requests.length;await c.exportList('bundle');assert.equal(f.service.requests.length,count,'conflict blocks export instead of overwriting server');await c.loadAccountCart();assert.equal(f.state.checkout.get('optic').quantity,'2');assert.equal(f.state.cart.error,'');
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();let fail=true;
    c.fetchAPI=async(path,options)=>{const response=await f.service.fetch(path,options);if(path==='/cart/add'&&fail){fail=false;throw new Error('连接中断，加入结果暂未确认');}return response};
    await assert.rejects(c.addAccountCart({},'不确定的加入'),/连接中断/);assert.ok(f.state.cart.pendingAdd);assert.equal(f.service.response().sources.length,1);const requestId=f.state.cart.pendingAdd.requestId;
    await c.retryCartAddition();assert.equal(f.service.response().sources.length,1,'retry reuses idempotency key and cannot double-add');assert.equal(f.service.requests.filter(r=>r.path==='/cart/add')[1].body.requestId,requestId);assert.equal(f.state.cart.pendingAdd,null);assert.equal(f.state.checkout.get('optic').quantity,'2');
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'账号 A');c.onCheckoutInput({target:{dataset:{checkoutQuantity:'optic'},value:'15',setAttribute(){}}});f.service.switchAccount();await assert.rejects(c.flushAccountCart(),/cart_account_changed/);assert.equal(f.service.response().items.length,0,'stale A data cannot be written into account B');assert.match(f.$('cart-save-status').textContent,/登录账号已变更/);await c.loadAccountCart();assert.equal(f.state.cart.cartId,'account-B-cart');assert.equal(c.checkoutRows().length,0);
    f.state.session.role='unauthenticated';c.pauseAccountCart();assert.equal(f.state.cart.loaded,false);assert.equal(f.state.cart.pendingAdd,null);const count=f.service.requests.length;await assert.rejects(c.flushAccountCart(),/载入当前账号/);assert.equal(f.service.requests.length,count);
  }
  {
    const f=fixture(),c=f.context;await c.syncCartSession();await c.addAccountCart({},'账号来源');const gate=deferred();c.fetchAPI=async(path,options)=>path==='/cart'?gate.promise:f.service.fetch(path,options);const load=c.loadAccountCart();f.state.session.role='guest';await c.syncCartSession();gate.resolve({json:async()=>f.service.response()});await load;assert.equal(f.state.cart.mode,'guest');assert.equal(c.checkoutRows().length,0,'late account GET cannot expose account rows to guest state');assert.match(f.$('cart-save-status').textContent,/游客临时清单/);
    let tempCalls=0;c.fetchAPI=async(path,options)=>{tempCalls++;assert.equal(path,'/preview');return{json:async()=>({lubang:[{componentId:'temporary',kind:'lubang',quantity:1,name:'临时',unit:'个'}],manufacturing:[],standard:[],items:[],reviewGroups:[],layoutValidation:{valid:true}})}};await c.generate();assert.equal(tempCalls,1);assert.equal(f.state.resultSource,'layout');assert.ok(f.state.resultRequest);assert.equal(f.state.cart.dirty,false,'guest generation never writes account cart');
  }
  assert.doesNotMatch(app.slice(app.indexOf('  function persist()'),app.indexOf('  function requestPersist()')),/state\.cart|checkout/,'account cart data is never written to global localStorage');
  console.log('Account cart UI: independent invalid/cleared canvas export, additive snapshots, reload persistence, deletion clears selection, stale selection rejection, strict-server autosave, remove/restore during pending saves, batch removal, legacy-state normalization, export waits saves, serialized edits, revision conflict, explicit idempotent add retry, account-switch key guard, stale GET isolation, guest fallback and no localStorage account data passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
