'use strict';
// Real app/session hooks + existing editor/project fixture. UI role controls have a separate DOM test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync(__dirname+'/static/app.js','utf8'),sharedTest=fs.readFileSync(__dirname+'/test_shared_app.cjs','utf8');
const harness={require,__dirname,console};vm.createContext(harness);vm.runInContext(sharedTest.slice(0,sharedTest.indexOf('async function run(){'))+'\nglobalThis.createSessionFixture=fixture;',harness);
const section=(from,to)=>app.slice(app.indexOf(from),app.indexOf(to,app.indexOf(from)));
const clone=value=>JSON.parse(JSON.stringify(value));
function fixture(role='readonly'){
  const f=harness.createSessionFixture(),c=f.context;f.state.session={role,canPublish:false,canDownload:true,loaded:true};let updates=0;
  c.sharedLibrary={updateContext(){updates++}};c.guestAccessManager=null;c.sessionUpdates=()=>updates;
  vm.runInContext(section('  function normalizedSession(', '  async function loadCatalog('),c);
  vm.runInContext(section('  async function generate() {', '  async function generateModule('),c);
  vm.runInContext(section('  async function exportList(', '  function normalizedSession('),c);
  vm.runInContext(section('  function signedInCartSession(', '  function reviewBlockedExports('),c);
  f.state.cart={mode:role==='guest'?'guest':'account',loaded:role!=='guest',revision:0,cartId:'fixture-cart',sources:[],error:'',epoch:0,dirty:false};f.state.checkout=new Map();c.clearTimeout=()=>{};c.renderResults=()=>{};c.blockedBundleKits=()=>[];c.reviewBlockedExports=()=>new Set();c.window.matchMedia=()=>({matches:true});c.$('results').scrollIntoView=()=>{};
  return f;
}
const pending=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}};
(async()=>{
  for(const role of ['guest','readonly']){
    const f=fixture(role),c=f.context,requests=[];const incoming=c.window.ZZLabProjectFile.create(c.projectData(),c.projectOptions());incoming.metadata.name='登录共享方案';
    c.fetchAPI=async(path,options)=>{requests.push({path,options});const preview={layoutValidation:{valid:true},items:[],lubang:[{componentId:'buy',quantity:1}],manufacturing:[{componentId:'make',quantity:1}]};return{json:async()=>path==='/cart/add'?{cartId:'fixture-cart',revision:1,preview,items:[{componentId:'buy',quantity:1,selected:true,removed:false},{componentId:'make',quantity:1,selected:true,removed:false}],sources:[{id:'s',name:'Source'}]}:preview,text:async()=>JSON.stringify(incoming),blob:async()=>({contents:'file'}),headers:{get:()=>null}}};
    const originalX=f.editor.instances[0].xMm;f.editor.move(12.5,0);assert.equal(f.editor.instances[0].xMm,originalX+12.5,role+' retains editing');f.editor.undo();
    await c.generate();assert.ok(requests.some(r=>r.path===(role==='guest'?'/preview':'/cart/add')),role+' adds its own BOM');assert.ok(role==='guest'?f.state.resultRequest:f.state.resultSource==='cart');
    for(const format of ['lubang','manufacturing','bundle']){await c.exportList(format);assert.ok(requests.some(r=>r.path===(role==='guest'?'/export?format=':'/cart/export?format=')+format),role+' exports '+format)}
    const downloads=f.downloads.length;c.saveProject();assert.equal(f.downloads.length,downloads+1,role+' saves a local project');
    c.applyProject(incoming);assert.equal(f.state.project.name,'登录共享方案',role+' imports a local project');
    await c.openSharedKit({id:'public',name:'登录共享方案'});assert.equal(f.state.project.name,'登录共享方案');
    const originalLayout=clone(f.editor.snapshot());await c.addSharedKit({id:'public',name:'登录共享方案'});
    assert.equal(f.editor.instances.length,2,role+' retains directly mounted root components in the shared canvas');assert.equal(f.editor.allInstances().length,4,role+' adds permitted shared geometry to the complete assembly');
    const layout=f.editor.snapshot();assert.equal(layout.subBoards.length,1,role+' keeps the shared module on its small board');assert.equal(f.editor.activeBoardId,null);assert.equal(f.editor.selectedModuleId,layout.subBoards[0].id,role+' selects the complete module');assert.equal(f.editor.selectedIds.size,0);
    assert.deepEqual(clone(layout.instances.filter(i=>!i.boardId)),originalLayout.instances,role+' preserves original carrier components while mounting');
    await c.downloadSharedKit({id:'public',name:'登录共享方案'},'project');await c.downloadSharedKit({id:'public',name:'登录共享方案'},'bundle');assert.ok(requests.some(r=>r.path==='/shared-kits/public/project'));assert.ok(requests.some(r=>r.path==='/shared-kits/public/bundle'));
    const count=requests.length;await assert.rejects(c.publishSharedKit({name:'forbidden',description:'',scope:'all'}),/普通或管理员/);assert.equal(requests.length,count,'publication is rejected before sending for '+role);
    const context=c.sharedContext();assert.equal(context.role,role);assert.equal(context.canPublish,false);assert.equal(context.canDownload,true);
  }
  {
    const f=fixture(),c=f.context;assert.equal(c.normalizedSession({role:'guest',canPublish:true}).canPublish,false,'guest capability never permits publishing');assert.equal(c.normalizedSession({role:'readonly',canPublish:true}).canPublish,false);assert.equal(c.normalizedSession({role:'user',canPublish:false}).canPublish,false,'user without stable identity does not gain publication');assert.equal(c.normalizedSession({role:'admin',canPublish:true}).canPublish,true);assert.throws(()=>c.normalizedSession({role:'other'}));
    c.fetchAPI=async path=>{assert.equal(path,'/session');return{json:async()=>({role:'user',canPublish:true,canDownload:true})}};await c.loadSessionCapabilities();assert.equal(c.$('access-login').hidden,true);assert.match(c.$('access-status-text').textContent,/已登录/);assert.equal(c.sessionUpdates(),1);
    c.fetchAPI=async()=>({json:async()=>({role:'readonly',canPublish:false,canDownload:true})});await c.loadSessionCapabilities();assert.equal(c.$('access-login').hidden,true);assert.match(c.$('access-status-text').textContent,/只读账号/);
    const before=clone(f.editableState());c.fetchAPI=async()=>{throw new Error('network')};await c.loadSessionCapabilities();assert.equal(f.state.session.canPublish,false);assert.equal(f.state.session.canDownload,false);assert.equal(f.state.session.role,'unknown');assert.deepEqual(clone(f.editableState()),before,'session failure cannot reset local work');assert.match(c.$('access-status-text').textContent,/登录状态暂无法确认/);
  }
  {
    const f=fixture(),c=f.context,a=pending(),b=pending();let calls=0;c.fetchAPI=()=>++calls===1?a.promise:b.promise;const old=c.loadSessionCapabilities(),latest=c.loadSessionCapabilities();b.resolve({json:async()=>({role:'readonly',canPublish:false,canDownload:true})});await latest;a.resolve({json:async()=>({role:'admin',canPublish:true,canDownload:true})});await old;assert.equal(f.state.session.role,'readonly','older capability response cannot restore stale publication permission');assert.equal(c.sessionUpdates(),1);
  }
  {
    const f=fixture(),c=f.context,session=pending();let catalogRead=false,libraryStarted=false;c.savedLayout=null;c.savedProjectUI=null;c.restore=()=>{};c.renderFilters=()=>{};c.initSharedLibrary=()=>{libraryStarted=true};c.window.BreadboardEditor=class{constructor(){return f.editor}};
    // Startup timing is tested with a renderless DOM; board control binding is
    // covered separately, while the actual initStacked state hook still runs.
    f.editor.bindStacked=()=>{};
    c.fetchAPI=path=>path==='/session'?session.promise:Promise.resolve({json:async()=>{catalogRead=true;return{...f.state.catalog,components:[],categories:[]}}});
    vm.runInContext(section('  async function loadCatalog(', "  $('category-filters').addEventListener"),c);await c.loadCatalog();assert.ok(catalogRead&&libraryStarted,'pending capability response never blocks the authenticated editor or shared library');session.resolve({json:async()=>({role:'readonly',canPublish:false,canDownload:true})});await Promise.resolve();await Promise.resolve();
  }
  {
    const f=fixture('user'),c=f.context;f.state.session.canPublish=true;const before=clone(f.editableState()),history=f.editor.history.slice(),future=f.editor.future.slice();let redirects=0;c.window.location={assign(){redirects++},replace(){redirects++}};c.API='/optics-kits/api';
    vm.runInContext(section('  async function fetchAPI(', '  function reviewBlockedExports('),c);
    c.fetch=async()=>({ok:false,status:401,json:async()=>({error:{message:'Unauthorized'}})});await assert.rejects(c.fetchAPI('/export?format=bundle',{method:'POST'}),/请重新登录.*草稿仍保留/);
    assert.equal(f.state.session.role,'unauthenticated');assert.equal(f.state.session.canPublish,false);assert.equal(f.state.session.canDownload,false);assert.equal(c.$('access-login').hidden,false);assert.match(c.$('access-status-text').textContent,/请登录后继续/);assert.ok(!/可编辑与下载|访客/.test(c.$('access-status-text').textContent));assert.deepEqual(clone(f.editableState()),before);assert.deepEqual(f.editor.history,history);assert.deepEqual(f.editor.future,future);assert.equal(redirects,0,'login expiry does not navigate away from unsaved work');
    const count=f.downloads.length;c.saveProject();assert.equal(f.downloads.length,count+1,'already open local draft can still be saved before logging in');
    await c.loadSessionCapabilities();assert.equal(f.state.session.role,'unauthenticated','session 401 remains login-required');
    const NativeURL=URL;c.URL=Object.assign(class extends NativeURL{},c.URL);let parsedLogin=false;c.fetch=async()=>({ok:true,status:200,redirected:true,url:'https://zzlab.example/auth/login?next=%2Foptics-kits%2F',json:async()=>{parsedLogin=true;return{}},blob:async()=>{parsedLogin=true;return{}}});
    const savedCount=f.downloads.length;await assert.rejects(c.downloadSharedKit({id:'old',name:'工程'},'project'),error=>error.status===401&&error.code==='login_required');await assert.rejects(c.downloadSharedKit({id:'old',name:'工程'},'bundle'),/请重新登录/);assert.equal(parsedLogin,false,'login HTML is never parsed as a project or downloaded as a ZIP');assert.equal(f.downloads.length,savedCount);assert.deepEqual(clone(f.editableState()),before);assert.deepEqual(f.editor.history,history);assert.equal(redirects,0);

  }
  {
    const f=fixture('user'),c=f.context,old=pending();c.fetchAPI=()=>old.promise;const request=c.loadSessionCapabilities();c.markLoginRequired();old.resolve({json:async()=>({role:'admin',canPublish:true,canDownload:true})});await request;assert.equal(f.state.session.role,'unauthenticated','a late old capability response cannot overwrite a newer 401');
  }
  {
    const f=fixture('admin'),c=f.context,calls=[];c.fetchAPI=async(path,options)=>{calls.push({path,options});return{json:async()=>({guestAccessEnabled:false,revision:4,updatedAt:null})}};
    await c.readGuestAccess();await c.saveGuestAccess({guestAccessEnabled:true,guestManufacturingDownloadsEnabled:false,revision:4,untrusted:'discard'});assert.equal(calls[0].path,'/admin/guest-access');assert.equal(calls[1].path,'/admin/guest-access');assert.deepEqual(JSON.parse(calls[1].options.body),{guestAccessEnabled:true,guestManufacturingDownloadsEnabled:false,revision:4});
    for(const role of ['user','readonly','guest','unauthenticated']){f.state.session.role=role;const count=calls.length;await assert.rejects(c.readGuestAccess(),/仅限管理员/);await assert.rejects(c.saveGuestAccess({guestAccessEnabled:true,revision:4}),/仅限管理员/);assert.equal(calls.length,count)}
  }
  {
    const f=fixture('guest'),c=f.context,requests=[];f.state.session=c.normalizedSession({role:'guest',canPublish:false,canDownload:true,canDownloadManufacturing:false});c.renderSessionStatus();assert.match(c.$('access-status-text').textContent,/图纸和模型需登录/);assert.equal(c.sharedContext().canDownload,true);assert.equal(c.sharedContext().canDownloadManufacturing,false);
    const preview={layoutValidation:{valid:true},items:[],lubang:[{componentId:'buy',quantity:1}],manufacturing:[{componentId:'make',quantity:1}]};c.fetchAPI=async(path,options)=>{requests.push(path);return{json:async()=>preview,blob:async()=>({contents:'file'}),headers:{get:()=>null}}};
    await c.generate();assert.ok(requests.includes('/preview'));for(const format of ['lubang','manufacturing'])await c.exportList(format);assert.ok(requests.includes('/export?format=lubang'));assert.ok(requests.includes('/export?format=manufacturing'));
    await c.exportList('bundle');assert.ok(!requests.includes('/export?format=bundle'),'guest bundle blocked before request');await c.downloadSharedKit({id:'public',name:'Shared'},'project');assert.ok(requests.includes('/shared-kits/public/project'));await assert.rejects(c.downloadSharedKit({id:'public',name:'Shared'},'bundle'),/管理员已关闭/);assert.ok(!requests.includes('/shared-kits/public/bundle'));
    const downloads=f.downloads.length;c.saveProject();assert.equal(f.downloads.length,downloads+1,'restricted guest still saves project');assert.equal(c.normalizedSession({role:'guest'}).canDownloadManufacturing,true,'old session response remains compatible');assert.equal(c.normalizedSession({role:'readonly',canDownloadManufacturing:false}).canDownloadManufacturing,true,'guest restriction never changes readonly account');assert.throws(()=>c.normalizedSession({role:'guest',canDownloadManufacturing:'false'}),/下载权限/);
  }
  {
    const f=fixture('guest'),c=f.context,before=clone(f.editableState());c.API='/optics-kits/api';vm.runInContext(section('  async function fetchAPI(', '  function reviewBlockedExports('),c);c.fetch=async()=>({ok:false,status:403,json:async()=>({error:{code:'manufacturing_download_forbidden',message:'管理员已关闭游客的图纸和三维模型下载权限'}})});await assert.rejects(c.fetchAPI('/export?format=bundle'),error=>error.code==='manufacturing_download_forbidden');assert.equal(f.state.session.role,'guest','download restriction does not expire session');assert.equal(f.state.session.canDownloadManufacturing,false);assert.equal(f.state.session.canDownload,true);assert.deepEqual(clone(f.editableState()),before,'403 preserves canvas and project');assert.match(c.$('access-status-text').textContent,/图纸和模型需登录/);
  }
  console.log('Signed-in access integration: session normalization/status/race/failure, nonblocking catalog startup, local edit/import/save, BOM plus all export formats, authenticated shared add/open/download, controlled guest/readonly publication rejection, 401 login guidance with preserved draft/history, no redirect, and expired capability invalidation passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
