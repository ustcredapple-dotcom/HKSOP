/* Shared snapshots UI. Project capture/import and all authenticated I/O stay in app.js. */
(() => {
  'use strict';
  const PAGE_SIZE=6;
  const byId=id=>document.getElementById(id);
  const text=(node,value)=>{const next=String(value??'');if(node.textContent!==next)node.textContent=next};
  function element(tag,className='',value=null){const node=document.createElement(tag);if(className)node.className=className;if(value!==null)text(node,value);return node}
  const authorName=author=>typeof author==='string'?author:String(author?.name||author?.displayName||'实验室成员');
  const dateLabel=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?'':date.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'})};
  const errorMessage=error=>String(error?.message||'操作未完成，请稍后重试。').slice(0,500);
  function thumbnailUrl(kit){
    const fallback=`./api/shared-kits/${encodeURIComponent(String(kit.id))}/thumbnail`;
    try{const url=new URL(kit.thumbnailUrl||fallback,document.baseURI);if(url.origin===new URL(document.baseURI).origin&&['http:','https:'].includes(url.protocol))return url.href}catch{}
    return new URL(fallback,document.baseURI).href;
  }
  function mount(callbacks={}){
    const ids=['shared-kits-region','shared-kits-count','shared-kit-search','shared-kits-refresh','shared-kits-status','shared-kits-recovery','shared-kit-list','shared-kits-more','shared-publish-open','shared-publish-login','shared-publish-access-note','shared-publish-dialog','shared-publish-form','shared-publish-close','shared-publish-cancel','shared-publish-name','shared-publish-description','shared-publish-scope','shared-publish-selection','shared-publish-scope-note','shared-publish-error','shared-publish-submit'];
    const nodes=Object.fromEntries(ids.map(id=>[id,byId(id)]));if(ids.some(id=>!nodes[id]))throw new Error('共享套件界面尚未准备好。');
    const n=id=>nodes[id],state={kits:[],withdrawn:[],limit:PAGE_SIZE,query:'',loading:false,publishing:false,request:0,destroyed:false,busy:new Map(),cards:new Map(),contextKey:null,canManage:false,signedOut:false,downloadRestricted:false};
    const listeners=[];
    function listen(node,type,fn){node.addEventListener(type,fn);listeners.push(()=>node.removeEventListener(type,fn))}
    function notify(message,error=false){callbacks.notify?.(message,error)}
    function context(){return callbacks.getContext?.()||{}}
    function setError(message=''){text(n('shared-publish-error'),message);n('shared-publish-error').hidden=!message}
    function publishAccessNote(ctx){return ctx.role==='guest'?'请登录普通或管理员账号后发布共享套件。':ctx.role==='unauthenticated'?'请重新登录后使用共享套件。':ctx.role==='readonly'?'发布共享套件需要普通或管理员账号。':'发布权限暂未确认，请刷新页面后重试。'}
    function getPublishState(ctx,scope){
      if(ctx.canPublish!==true)return{allowed:false,note:publishAccessNote(ctx)};
      if(ctx.boardDirty)return{allowed:false,note:'面包板参数尚未应用，请先点击“更新面包板”。'};
      if(scope==='board')return ctx.activeBoard&&(Number(ctx.activeBoardCount)>0||ctx.activeBoardIsStage===true)?{allowed:true,note:ctx.activeBoardIsStage?`发布当前位移板及 ${Number(ctx.activeBoardCount)||0} 个器件；保留位移、固定基座和顶板归属。`:'发布当前小板、原沉孔及本板器件的选配；整个方案的全局配件仍留在总装。提交时核对本板布局。'}:{allowed:false,note:'请切换到含有器件的小面包板。'};
      if(scope==='selection')return Number(ctx.selectedCount)>0?{allowed:true,note:`发布选中的 ${ctx.selectedCount} 个器件及其选配、配件；保留板尺寸，不带全局配件和四角沉孔。提交时会检查所选布局。`}:{allowed:false,note:'请先在画布上选择要发布的器件。'};
      if(!(Number(ctx.instanceCount)>0||Number(ctx.stageCount)>0))return{allowed:false,note:'请先在画布上完成至少一个器件的摆放。'};
      if(ctx.valid!==true)return{allowed:false,note:'当前画布布局不可用，请先调整交汇、安装孔或底座位置。也可只发布已完成的选中器件。'};
      return{allowed:true,note:`发布整个画布的 ${Number(ctx.instanceCount)||0} 个器件${Number(ctx.stageCount)>0?'、'+ctx.stageCount+' 个位移板':''}、面包板和选配设置。`};
    }
    function updateContext(){
      if(state.destroyed)return;const ctx=context(),selected=Math.max(0,Number(ctx.selectedCount)||0),key=JSON.stringify([ctx.instanceCount,ctx.stageCount,ctx.activeBoardIsStage,ctx.hasCarrier,ctx.canMountModules,ctx.activeBoard,ctx.activeBoardCount,selected,ctx.valid,ctx.boardDirty,ctx.role,ctx.canPublish,ctx.canDownloadManufacturing,state.publishing,n('shared-publish-scope').value]);
      if(state.contextKey===key)return;state.contextKey=key;n('shared-kit-list').classList.toggle('can-mount-modules',Boolean(ctx.hasCarrier||ctx.canMountModules));
      const canPublish=ctx.canPublish===true,manageChanged=state.canManage!==canPublish,signedOut=ctx.role==='unauthenticated',downloadRestricted=ctx.role==='guest'&&ctx.canDownloadManufacturing===false,accessChanged=state.signedOut!==signedOut||state.downloadRestricted!==downloadRestricted;state.canManage=canPublish;state.signedOut=signedOut;state.downloadRestricted=downloadRestricted;
      n('shared-publish-open').hidden=!canPublish;n('shared-publish-login').hidden=!['guest','unauthenticated'].includes(ctx.role);text(n('shared-publish-login'),ctx.role==='guest'?'登录后发布共享套件':'登录后继续');n('shared-publish-access-note').hidden=canPublish||['guest','unauthenticated'].includes(ctx.role);text(n('shared-publish-access-note'),publishAccessNote(ctx));
      if(manageChanged){if(state.kits.length)renderList();renderRecovery()}else if(accessChanged)for(const id of state.cards.keys())cardBusy(id)
      const boardOption=byId('shared-publish-board');if(boardOption)boardOption.disabled=!ctx.activeBoard||!(Number(ctx.activeBoardCount)>0||ctx.activeBoardIsStage===true);
      const option=n('shared-publish-selection');option.disabled=!selected;text(option,selected?`选中的器件（${selected} 个）`:'选中的器件（尚未选择）');
      const readiness=getPublishState(ctx,n('shared-publish-scope').value||'all');text(n('shared-publish-scope-note'),readiness.note);n('shared-publish-submit').disabled=state.publishing||!readiness.allowed;
      n('shared-publish-open').disabled=!canPublish||state.publishing||!(Number(ctx.instanceCount)>0||Number(ctx.stageCount)>0);n('shared-publish-open').title=Number(ctx.instanceCount)>0||Number(ctx.stageCount)>0?'将已完成的光路共享给登录账号':'先在画布上放置器件，再发布共享套件';
      for(const id of ['shared-publish-name','shared-publish-description','shared-publish-scope'])n(id).disabled=state.publishing;text(n('shared-publish-submit'),state.publishing?'正在发布…':'发布共享套件');
    }
    function openPublish(){if(state.publishing)return;const ctx=context();if(ctx.canPublish!==true){notify(publishAccessNote(ctx),true);return}n('shared-publish-name').value=String(ctx.name||'').slice(0,120);n('shared-publish-description').value=String(ctx.notes||'').slice(0,2000);n('shared-publish-scope').value='all';setError();state.contextKey=null;updateContext();n('shared-publish-dialog').showModal();n('shared-publish-name').focus();n('shared-publish-name').select?.()}
    function closePublish(){n('shared-publish-dialog').close();n('shared-publish-open').focus()}
    async function publish(event){
      event.preventDefault();if(state.publishing||state.destroyed)return;
      const name=n('shared-publish-name').value.trim(),description=n('shared-publish-description').value.trim(),scope=n('shared-publish-scope').value||'all';
      if(!name||name.length>120){setError('请填写套件名称，最多 120 字。');n('shared-publish-name').focus();return}
      if(description.length>2000){setError('说明最多 2000 字，请缩短后再发布。');n('shared-publish-description').focus();return}
      const readiness=getPublishState(context(),scope);if(!readiness.allowed){setError(readiness.note);state.contextKey=null;updateContext();return}
      if(typeof callbacks.onPublish!=='function'){setError('共享发布暂时不可用，请刷新页面后重试。');return}
      setError();state.publishing=true;updateContext();
      try{const result=await callbacks.onPublish({name,description,scope});if(state.destroyed)return;n('shared-publish-dialog').close();n('shared-kits-region').open=true;n('shared-kit-search').value='';state.query='';state.limit=PAGE_SIZE;const warning=result?.backup?.status==='warning';notify(warning?`已发布；${result.backup.message||'备份暂未完成，请稍后联系管理员。'}`:'已发布共享套件，其他账号可使用；游客访问依管理员设置。',warning);await refresh();n('shared-kits-region').focus?.()}
      catch(error){if(!state.destroyed){setError(errorMessage(error));notify(errorMessage(error),true)}}
      finally{state.publishing=false;state.contextKey=null;updateContext()}
    }
    function cardBusy(id){const record=state.cards.get(String(id));if(!record)return;const message=state.busy.get(String(id))||'';for(const button of record.buttons)button.disabled=state.signedOut||!!message||(state.downloadRestricted&&button.getAttribute('data-shared-action')==='bundle');record.accessNote.hidden=!state.downloadRestricted;text(record.status,message);record.status.hidden=!message;record.card.setAttribute('aria-busy',String(!!message))}
    function actionButton(label,handler,className='text-button'){const button=element('button',className,label);button.type='button';button.addEventListener('click',handler);return button}
    async function runAction(kit,kind){
      const id=String(kit.id);if(state.busy.has(id)||state.destroyed)return;if(kind==='bundle'&&context().role==='guest'&&context().canDownloadManufacturing===false){notify('管理员已关闭游客的图纸和三维模型下载。仍可打开、装入和下载工程；完整资料包请登录后下载。',true);return}if(context().role==='unauthenticated'){notify(publishAccessNote(context()),true);return}if(['unpublish','restore'].includes(kind)&&context().canPublish!==true){notify(publishAccessNote(context()),true);return}
      const messages={add:'正在连同小板装入…',open:'正在打开工程…',project:'正在下载工程…',bundle:'正在准备资料包…',unpublish:'正在撤下…',restore:'正在恢复共享…'};
      const fn=kind==='add'?callbacks.onAdd:kind==='open'?callbacks.onOpen:['project','bundle'].includes(kind)?callbacks.onDownload:kind==='unpublish'?callbacks.onUnpublish:callbacks.onRestore;
      if(typeof fn!=='function'){notify('这项操作暂时不可用，请刷新页面后重试。',true);return}
      state.busy.set(id,messages[kind]);cardBusy(id);renderRecovery();
      try{
        const result=await fn(kit,...(['project','bundle'].includes(kind)?[kind]:[]));if(state.destroyed)return;
        if(kind==='unpublish'){
          state.kits=state.kits.filter(item=>String(item.id)!==id);state.withdrawn=[{...kit,status:'unpublished',canRestore:true},...state.withdrawn.filter(item=>String(item.id)!==id)];renderList();renderRecovery();notify('已撤下共享套件，可在“已撤下的套件”中恢复。');await refresh();
        }else if(kind==='restore'){
          state.withdrawn=state.withdrawn.filter(item=>String(item.id)!==id);renderRecovery();notify('已恢复共享套件。');await refresh();
        }
        if(result?.backup?.status==='warning')notify(result.backup.message||'操作已保存，备份暂未完成。',true);
      }catch(error){if(!state.destroyed)notify(errorMessage(error),true)}
      finally{state.busy.delete(id);if(!state.destroyed){cardBusy(id);renderRecovery()}}
    }
    function createCard(kit){
      const card=element('article','shared-kit-card'),preview=element('div','shared-kit-preview'),img=element('img');img.alt=`${kit.name||'共享套件'}的俯视图`;img.loading='lazy';img.decoding='async';img.width=192;img.height=104;img.src=thumbnailUrl(kit);img.addEventListener('error',()=>{img.hidden=true;preview.classList.add('shared-preview-unavailable');if(!preview.querySelector('.shared-preview-note'))preview.appendChild(element('span','shared-preview-note','俯视图暂时无法加载'))},{once:true});preview.appendChild(img);preview.appendChild(element('span','shared-mount-hint','拖到面包板 · 含小板'));preview.title='拖拽此缩略图，将模块连同小面包板安装到当前大板';
      card.draggable=true;card.addEventListener('dragstart',e=>{if(e.target.closest('button,a,input,summary')||state.busy.has(String(kit.id))){e.preventDefault();return}e.dataTransfer.setData('application/x-zzlab-shared-kit',String(kit.id));e.dataTransfer.effectAllowed='copy'});img.draggable=false;
      // Pointer dragging also works in embedded browsers that do not start a
      // native HTML drag. The card buttons remain keyboard alternatives.
      let pointerDrag=null;
      preview.addEventListener('dragstart',e=>e.preventDefault());
      preview.addEventListener('pointerdown',e=>{if(e.button!==0||!(context().hasCarrier||context().canMountModules)||state.busy.has(String(kit.id)))return;pointerDrag={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false};preview.setPointerCapture?.(e.pointerId);e.preventDefault()});
      preview.addEventListener('pointermove',e=>{if(pointerDrag?.id!==e.pointerId)return;if(Math.hypot(e.clientX-pointerDrag.x,e.clientY-pointerDrag.y)>6){pointerDrag.moved=true;card.classList.add('shared-dragging')}});
      const finishDrag=async e=>{const drag=pointerDrag;if(drag?.id!==e.pointerId)return;pointerDrag=null;card.classList.remove('shared-dragging');if(preview.hasPointerCapture?.(e.pointerId))preview.releasePointerCapture(e.pointerId);if(e.type==='pointercancel'||!drag.moved)return;try{await callbacks.onCarrierDrop?.(kit,{clientX:e.clientX,clientY:e.clientY})}catch(error){notify(errorMessage(error),true)}};
      preview.addEventListener('pointerup',finishDrag);preview.addEventListener('pointercancel',finishDrag);
      const content=element('div','shared-kit-content'),title=element('h3','',String(kit.name||'未命名共享套件')),meta=element('p','shared-kit-meta',`${Number(kit.instanceCount)||0} 个器件 · ${Number(kit.board?.widthMm)||'—'} × ${Number(kit.board?.heightMm)||'—'} mm`),author=element('p','shared-kit-author',`${authorName(kit.author)}${dateLabel(kit.createdAt)?' · '+dateLabel(kit.createdAt):''}`);content.append(title,meta,author);
      if(kit.description){const description=String(kit.description);content.appendChild(element('p','shared-kit-description-preview',description.length>80?description.slice(0,80)+'…':description));if(description.length>80){const details=element('details','shared-kit-description');details.append(element('summary','','完整说明'),element('p','',description));content.appendChild(details)}}
      const primary=element('div','shared-kit-primary-actions'),secondary=element('div','shared-kit-secondary-actions'),buttons=[];
      for(const [label,kind,group,className]of [['连同小板装入','add',primary,'secondary-button'],['打开工程','open',primary,'secondary-button'],['下载工程','project',secondary,'text-button'],['下载资料包','bundle',secondary,'text-button']]){const button=actionButton(label,()=>runAction(kit,kind),className);button.title=`${label}：${kit.name||'共享套件'}`;button.setAttribute('data-shared-action',kind);buttons.push(button);group.appendChild(button)}
      if(state.canManage&&kit.canUnpublish===true){const button=actionButton('撤下',()=>runAction(kit,'unpublish'),'text-button shared-unpublish');button.title='从共享列表撤下，之后可恢复';buttons.push(button);secondary.appendChild(button)}
      const accessNote=element('p','shared-download-access-note','图纸和模型下载需登录；工程仍可下载和使用。');accessNote.hidden=!state.downloadRestricted;const status=element('p','shared-card-status');status.hidden=true;status.setAttribute('role','status');content.append(primary,secondary,accessNote,status);card.append(preview,content);state.cards.set(String(kit.id),{card,buttons,status,accessNote});return card;
    }
    function filteredKits(){const query=state.query.toLocaleLowerCase();return query?state.kits.filter(kit=>[kit.name,kit.description,authorName(kit.author)].some(value=>String(value||'').toLocaleLowerCase().includes(query))):state.kits}
    function renderList(){
      if(state.destroyed)return;const filtered=filteredKits(),visible=filtered.slice(0,state.limit);state.cards.clear();n('shared-kit-list').replaceChildren(...visible.map(createCard));for(const kit of visible)cardBusy(kit.id);
      text(n('shared-kits-count'),state.kits.length);text(n('shared-kits-status'),state.loading?'正在读取共享套件…':!state.kits.length?(state.signedOut?'请登录后查看共享套件。':state.canManage?'还没有共享套件。完成光路后，可在“保存工程”旁发布。':'还没有共享套件。'):!filtered.length?'没有找到匹配的共享套件。':`共 ${filtered.length} 个${state.query?'匹配结果':'共享套件'}${filtered.length>visible.length?`，已显示 ${visible.length} 个`:''}`);
      n('shared-kits-more').hidden=visible.length>=filtered.length;text(n('shared-kits-more'),`显示更多（还有 ${Math.max(0,filtered.length-visible.length)} 个）`);
    }
    function renderRecovery(){
      if(state.destroyed)return;const recoverable=state.canManage?state.withdrawn.filter(kit=>kit.canRestore===true):[],container=n('shared-kits-recovery'),wasOpen=container.querySelector('details')?.open;container.hidden=!recoverable.length;if(!recoverable.length){container.replaceChildren();return}
      const details=element('details'),summary=element('summary','',`已撤下的套件 · ${recoverable.length}`);details.open=!!wasOpen;details.appendChild(summary);
      for(const kit of recoverable){const row=element('div','shared-recovery-row'),label=element('span','',String(kit.name||'未命名套件')),button=actionButton(state.busy.has(String(kit.id))?'正在处理…':'恢复共享',()=>runAction(kit,'restore'));button.disabled=state.busy.has(String(kit.id));row.append(label,button);details.appendChild(row)}container.replaceChildren(details);
    }
    async function refresh(){
      if(state.destroyed)return;const request=++state.request;state.loading=true;n('shared-kits-refresh').disabled=true;const list=n('shared-kit-list');list.setAttribute('aria-busy','true');text(n('shared-kits-status'),'正在读取共享套件…');
      try{
        if(typeof callbacks.fetchList!=='function')throw new Error('共享套件暂时无法读取，请稍后刷新。');const result=await callbacks.fetchList();if(state.destroyed||request!==state.request)return;
        const kits=Array.isArray(result)?result:result?.kits;if(!Array.isArray(kits))throw new Error('共享套件列表读取不完整，请重新刷新。');
        const seen=new Set();state.kits=kits.filter(kit=>{if(!kit||kit.id==null||seen.has(String(kit.id)))return false;seen.add(String(kit.id));return kit.status!=='unpublished'});state.withdrawn=Array.isArray(result?.withdrawn)?result.withdrawn:[];state.loading=false;renderList();renderRecovery();
      }catch(error){if(!state.destroyed&&request===state.request){state.loading=false;text(n('shared-kits-status'),`${errorMessage(error)}${state.kits.length&&!state.signedOut?' 已有列表仍可使用。':''}`)}}
      finally{if(!state.destroyed&&request===state.request){state.loading=false;n('shared-kits-refresh').disabled=false;list.setAttribute('aria-busy','false')}}
    }
    listen(n('shared-publish-open'),'click',openPublish);listen(n('shared-publish-close'),'click',closePublish);listen(n('shared-publish-cancel'),'click',closePublish);listen(n('shared-publish-form'),'submit',publish);
    listen(n('shared-publish-scope'),'change',()=>{setError();state.contextKey=null;updateContext()});listen(n('shared-publish-name'),'input',()=>setError());listen(n('shared-publish-description'),'input',()=>setError());listen(n('shared-kits-refresh'),'click',()=>refresh());
    listen(n('shared-kit-search'),'input',()=>{state.query=n('shared-kit-search').value.trim();state.limit=PAGE_SIZE;renderList()});listen(n('shared-kits-more'),'click',()=>{state.limit+=PAGE_SIZE;renderList()});
    updateContext();const ready=Promise.resolve();
    return{refresh,updateContext,ready,destroy(){state.destroyed=true;state.request++;listeners.forEach(remove=>remove());n('shared-kit-list').replaceChildren();n('shared-kits-recovery').replaceChildren();if(n('shared-publish-dialog').open)n('shared-publish-dialog').close()}};
  }
  window.ZZLabSharedKits={mount};
})();
