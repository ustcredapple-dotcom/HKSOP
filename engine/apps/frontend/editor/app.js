(() => {
  'use strict';
  const API = '/optics-kits/api';
  const STORAGE_KEY = 'zzlab.optics-kits.layout.v2';
  const LEGACY_STORAGE_KEY = 'zzlab.optics-kits.plan.v1';
  let editor = null, savedLayout = null, savedProjectUI = null, savedOpticalRendering = undefined, migrationItems = [], sharedLibrary = null, guestAccessManager = null;
  const MAX_QUANTITY = 9999;
  const $ = (id) => document.getElementById(id);
  const state = { catalog: null, kits: new Map(), components: new Map(), quantities: new Map(), extras: [], optical: {}, category: 'all', search: '', revision: 0, previewRevision: -1, preview: null, checkout: new Map(), checkoutRevision: 0, resultRequest: null, resultSource: 'layout', moduleQuantities: new Map(), moduleRevision: 0, previewModuleRevision: -1, generating: false, exporting: false, choosingMounting: false, mountingSelection: {rowParity:'any',columnParity:'any'}, editingExtra: null, storageAvailable: true, session:{role:'unknown',canPublish:false,canDownload:false,canDownloadManufacturing:false,loaded:false} };
  let toastTimer;
  const deepCopy = value => JSON.parse(JSON.stringify(value));
  const newProjectMetadata = () => { const now = new Date().toISOString(); return {name:'未命名光路工程',notes:'',createdAt:now,updatedAt:now}; };
  state.project = newProjectMetadata();
  state.cart = {mode:"loading",loaded:false,revision:0,cartId:null,updatedAt:null,sources:[],loading:false,saving:false,busy:false,dirty:false,error:"",conflict:false,editRevision:0,epoch:0,timer:null,savePromise:null,pendingAdd:null};
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const textValue = (value) => Array.isArray(value) ? value.filter(Boolean).join('；') : String(value ?? '');
  const validQuantity = (value) => /^\d+$/.test(String(value)) && Number(value) >= 1 && Number(value) <= MAX_QUANTITY;
  function statusInfo(status,context=''){
    const raw=String(status??'').trim();
    if(!raw)return{label:'状态未登记',tone:'neutral',raw};
    const pending=/待|未确认|未核实|未核验|未核对|pending|unconfirmed|unknown|tbd/i.test(raw);
    if(/缺失|缺少|待补齐|待补充|missing|incomplete/i.test(raw))return{label:'资料待补齐',tone:'pending',raw};
    if(pending){
      let label='待确认';
      if(/源版本|版本|来源/.test(raw))label='源版本待核对';
      else if(/供应商/.test(raw))label='供应商待确认';
      else if(/型号|选型|规格|别名/.test(raw))label=context==='kit'?'选型待确认':'型号待确认';
      else if(/工艺/.test(raw))label='工艺待确认';
      return{label,tone:'pending',raw};
    }
    if(/已核验|verified/i.test(raw))return{label:/几何/.test(raw)?'几何已核验':'已核验',tone:'confirmed',raw};
    if(/已核对|已确认|已核实|^(confirmed|approved|ready)$/i.test(raw))return{label:'已核对',tone:'confirmed',raw};
    if(/加工审核[版图]/.test(raw))return{label:'加工审核版',tone:'neutral',raw};
    if(/参考.*图|参考图/.test(raw))return{label:'参考图',tone:'neutral',raw};
    if(/图纸已备|图纸齐备/.test(raw))return{label:'图纸已备',tone:'neutral',raw};
    return{label:raw.length>22?raw.slice(0,22)+'…':raw,tone:'neutral',raw};
  }
  function statusTag(status,context=''){const info=statusInfo(status,context);return `<span class="status-tag ${info.tone}"${info.raw&&info.raw!==info.label?` title="${escape(info.raw)}"`:''}>${escape(info.label)}</span>`;}
  function bundleNote(kit) { return kit.bundleStatus === 'blocked' ? `<div class="bundle-kit-note"><span class="status-tag">完整包待补齐</span><p>${escape(kit.bundleNote || '完整加工包资料待补齐。')}</p></div>` : ''; }
  function blockedBundleKits(preview = state.preview) { return (preview?.items || []).map(item => state.kits.get(item.kitId)).filter(kit => kit?.bundleStatus === 'blocked'); }
  function safeUrl(value) { if (!value) return ''; try { const url = new URL(value, window.location.href); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } }
  function link(value, label, cls = '') { const url = safeUrl(value); return url ? `<a class="${cls}" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${label}</a>` : ''; }
  const externalIcon = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3H3v10h10V9M9 3h4v4M7 9l6-6"></path></svg>';
  function notify(message, error = false) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 6500 : 3400); }
  function categoryLabel(id) { return state.catalog?.categories?.find(c => c.id === id)?.label || id || '功能套件'; }
  function artwork(kit) {
    if(kit.layout?.topViewUrl)return `<img class="real-kit-topview" src="${escape(safeUrl(kit.layout.topViewUrl))}" alt="${escape(kit.name)} 俯视图" loading="lazy">`;
    return '<span class="missing-view-label">俯视图待补齐</span>';
  }
  function normalizeMountingSelection(value,holes=[]){
    const allowed=['any','odd','even'],result={};for(const [key,index]of [['rowParity','rowIndex'],['columnParity','columnIndex']]){const supplied=value?.[key];const parities=new Set((holes||[]).map(h=>(h[index]+1)%2));result[key]=allowed.includes(supplied)?supplied:parities.size===1?(parities.has(1)?'odd':'even'):'any';}return result;
  }
  function syncMountingSelection(value,holes=[]){state.mountingSelection=normalizeMountingSelection(value,holes);$('mounting-row-parity').value=state.mountingSelection.rowParity;$('mounting-column-parity').value=state.mountingSelection.columnParity;}
  function persist() {
    clearTimeout(requestPersist.timer);requestPersist.timer=null;
    if(state.autosavePaused){$('save-status').textContent='原草稿已保留；当前工程请使用保存工程下载';return;}
    try { const serialized=JSON.stringify({version:2,catalogVersion:state.catalog.version,requires:['zzlab-metric-supports-v1',...((editor?editor.snapshot():savedLayout)?.glassChamber?['zzlab-glass-chamber-v1']:[]),...(layoutRequirements(editor?editor.snapshot():savedLayout).requires||[])],...(editor?.opticalRenderingPrefs?{opticalRendering:editor.opticalRenderingPrefs()}:savedOpticalRendering?{opticalRendering:savedOpticalRendering}:{}),layout:editor?editor.snapshot():savedLayout,extras:state.extras,optical:state.optical,moduleQuantities:Array.from(state.moduleQuantities),mountingSelection:state.mountingSelection,metadata:state.project,ui:{view:editor?.view||savedProjectUI?.view||null,selectedIds:Array.from(editor?.selectedIds||[]),mountingSelection:state.mountingSelection}});if(serialized!==persist.lastSaved){localStorage.setItem(STORAGE_KEY,serialized);persist.lastSaved=serialized;}state.storageAvailable=true; }
    catch { if (state.storageAvailable) notify('浏览器无法保存方案；当前页面仍可继续使用。', true); state.storageAvailable = false; }
    $('save-status').textContent = state.storageAvailable ? '工程已自动保存在此浏览器' : '当前工程仅保留在本页';
  }
  function requestPersist(){
    if(requestPersist.timer!=null)return;
    requestPersist.timer=setTimeout(persist,200);
  }
  function requestPlanRender(){
    flushOpticalInputs();
    if(requestPlanRender.pending)return;
    requestPlanRender.pending=true;
    queueMicrotask(()=>{requestPlanRender.pending=false;renderPlan()});
  }
  function restore() {
    try {
      const raw=localStorage.getItem(STORAGE_KEY);let saved=raw?JSON.parse(raw):null;
      if(saved?.version===2&&saved.layout){const result=window.ZZLabMetricMigration.migrate(saved,state.catalog);if(result.changed){const backup=STORAGE_KEY+'.before-metric-20261006';try{if(!localStorage.getItem(backup))localStorage.setItem(backup,raw);}catch{state.autosavePaused=true;}saved=result.project;const notice=$('restore-notice');notice.hidden=false;notice.textContent=state.autosavePaused?'已载入公制等效规格；浏览器备份空间不足，原草稿保持不变，请下载保存新工程。':'已将旧支撑件更新为公制等效规格，保留器件位置和选配；原草稿已备份。';}}
      if (saved?.version===2 && saved.layout) { savedLayout=saved.layout;savedOpticalRendering=saved.opticalRendering;savedProjectUI=saved.ui||null;state.mountingSelection=normalizeMountingSelection(saved.ui?.mountingSelection||saved.mountingSelection,saved.layout.board?.mountingHoles);state.extras=Array.isArray(saved.extras)?saved.extras:[];state.optical=saved.optical||{};state.moduleQuantities=new Map((saved.moduleQuantities||[]).filter(pair=>Array.isArray(pair)&&state.kits.has(pair[0])&&validQuantity(pair[1])));if(saved.metadata&&typeof saved.metadata.name==='string'){for(const key of ['name','notes','createdAt','updatedAt'])if(typeof saved.metadata[key]==='string')state.project[key]=saved.metadata[key];if(saved.metadata.moduleElevation)state.project.moduleElevation=deepCopy(saved.metadata.moduleElevation);if(Number.isFinite(saved.metadata.opticalAxisTargetMm))state.project.opticalAxisTargetMm=saved.metadata.opticalAxisTargetMm;}return; }
      const legacy=JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY)||'null');
      if(legacy?.version===1 && Array.isArray(legacy.items) && legacy.items.length){ migrationItems=legacy.items.filter(i=>state.kits.has(i.kitId)&&validQuantity(i.quantity));state.extras=legacy.extras||[];state.optical=legacy.optical||{};$('restore-notice').textContent='发现旧方案：请从套件库重新摆放。旧数量未自动变成未经确认的布局；旧方案仍保留在浏览器。';$('restore-notice').hidden=false; }
    } catch { state.autosavePaused=true;$('save-status').textContent='原草稿已保留，恢复失败；请先下载或备份后再重新打开'; }
  }
  function prepareSavedLayout(catalog) {
    if(!savedLayout)return;
    try {
      if(window.ZZLAB_LOCAL){
        const ids=new Set(catalog.kits.map(kit=>kit.id)),original=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
        const refs=[...(savedLayout.instances||[]).map(instance=>instance.kitId),...(original?.moduleQuantities||[]).map(pair=>pair[0]),...state.extras.map(extra=>extra.kitId),...Object.keys(state.optical).filter(key=>key.startsWith('module:')).map(key=>key.split('::')[0].slice(7))];
        const missing=refs.find(id=>id&&!ids.has(id));
        if(missing)throw new Error('草稿引用的套件 '+missing+' 已不在新版库中，原草稿已保留。');
      }
      const boards=[{board:savedLayout.board},...(savedLayout.subBoards||[])];
      for(const plate of boards){
        const board=plate.board?.registeredBoardId?window.ZZLabRegisteredBoards.normalizeBoard(plate.board,catalog):plate.board;
        if(plate.stageMotion)window.ZZLabMovingStages.normalizeMotion(plate.stageMotion,board,catalog);
        else if(catalog.registeredBoards?.find(b=>b.id===board?.registeredBoardId)?.stageOnly)throw new Error('位移顶板缺少完整模块信息。');
      }
    } catch(error) {
      const fallback=JSON.stringify({version:2,layout:savedLayout,metadata:state.project,optical:state.optical,extras:state.extras,moduleQuantities:Array.from(state.moduleQuantities),mountingSelection:state.mountingSelection,ui:savedProjectUI,opticalRendering:savedOpticalRendering});
      let raw=fallback,backedUp=false;
      try{raw=localStorage.getItem(STORAGE_KEY)||fallback;const key=STORAGE_KEY+'.recovery.'+Date.now();localStorage.setItem(key,raw);backedUp=localStorage.getItem(key)===raw;}catch{}
      state.autosavePaused=window.ZZLAB_LOCAL||!backedUp;
      const notice=$('restore-notice');notice.hidden=false;notice.innerHTML=`原草稿需要更新元件版本，已保留，未自动替换：${escape(error.message)} 当前打开空画布。<button type="button" class="text-button" data-recover-draft>下载原草稿备份</button>`;
      notice.querySelector('[data-recover-draft]').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([raw],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='待恢复原草稿.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000)});
      savedLayout=null;savedProjectUI=null;savedOpticalRendering=undefined;state.optical={};state.extras=[];state.moduleQuantities.clear();state.project=newProjectMetadata();state.mountingSelection={rowParity:'any',columnParity:'any'};
    }
  }
  function updateQuantities(layout) {
    state.quantities.clear();
    for(const i of layout.instances||[])state.quantities.set(i.kitId,(state.quantities.get(i.kitId)||0)+1);
    for(const p of layout.subBoards||[])if(p.stageMotion)state.quantities.set(p.stageMotion.moduleId,(state.quantities.get(p.stageMotion.moduleId)||0)+1);
  }
  function syncLayout(layout) {
    updateQuantities(layout);
    $('board-empty-guide').hidden=layout.instances.length>0||Boolean(layout.subBoards?.length); markChanged();requestPlanRender();renderExtras();
  }
  function markChanged() {
    state.revision++;
    state.project.updatedAt=new Date().toISOString();
    requestPersist();
    if(state.preview&&state.resultSource==='layout')$('stale-notice').hidden=false;
    updateButtons();
  }
  function markModuleChanged(){state.moduleRevision++;state.project.updatedAt=new Date().toISOString();requestPersist();if(state.preview&&state.resultSource==='module')$('stale-notice').hidden=false;updateButtons();}
  function updateButtons() {
    sharedLibrary?.updateContext();
    const validation=editor?.validation(),loginRequired=state.session?.role==='unauthenticated',inputs=[state.session?.role,state.session?.canDownloadManufacturing,validation,editor?.boardFormDirty,editor?.manualMounting,state.revision,state.moduleRevision,state.preview,state.cart?.mode,state.cart?.loaded,state.cart?.loading,state.cart?.saving,state.cart?.busy,state.cart?.dirty,state.cart?.error,state.cart?.pendingAdd,state.checkoutRevision,state.previewRevision,state.previewModuleRevision,state.resultSource,state.generating,state.exporting,state.choosingMounting,state.quantities.size,...state.quantities.values()];
    if(updateButtons.lastInputs?.length===inputs.length&&inputs.every((value,index)=>Object.is(value,updateButtons.lastInputs[index])))return;
    updateButtons.lastInputs=inputs;
    const total = Array.from(state.quantities.values()).reduce((a, b) => a + b, 0);
    $('mobile-plan-total').textContent = `${total} 套`; $('mobile-plan-jump').hidden = !total; $('plan-total').textContent = total; $('plan-count').textContent = total; $('plan-types').textContent = state.quantities.size;
    $('clear-plan').disabled = !editor?.instances?.length;$('clear-plan').textContent=editor?.stacked?'清空当前板':'清空';if($('plan-board-count'))$('plan-board-count').textContent=editor?.baseMode==='table'?`桌子（不生产） · ${editor?.stacked?.subBoards.length||0} 块小板`:`${1+(editor?.stacked?.subBoards.length||0)} 块面包板`;
    const layoutValid=Boolean(editor)&&validation.valid&&!editor.boardFormDirty;
    const cartUnavailable=(state.resultSource==='cart'&&!accountCartActive())||state.session?.role==='unknown'||signedInCartSession()&&(!state.cart?.loaded||state.cart?.loading||state.cart?.busy||Boolean(state.cart?.error)||Boolean(state.cart?.pendingAdd));
    $('generate').disabled = loginRequired || !layoutValid || state.generating || state.exporting || cartUnavailable || Boolean(editor?.manualMounting);
    $('generate').querySelector('span').textContent = loginRequired ? '登录后加入购物车' : state.session?.role==='unknown' ? '正在确认账号…' : state.generating ? '正在加入…' : editor?.manualMounting ? '先应用或取消手动选孔' : editor?.boardFormDirty ? '先更新面包板参数' : !layoutValid ? '调整布局后加入购物车' : state.session?.role==='guest' ? '生成临时清单' : '加入购物车';
    const checkoutData=checkoutReviewData(),blockedFormats=reviewBlockedExports(checkoutData);
    const bundleBlocked = blockedFormats.has('bundle'),manufacturingRestricted=state.session?.role==='guest'&&state.session.canDownloadManufacturing===false;
    if($('manufacturing-download-access-note'))$('manufacturing-download-access-note').hidden=!manufacturingRestricted;
    const persistent=state.resultSource==='cart',resultValid=persistent||state.resultSource==='module'||layoutValid;const resultFresh=persistent?Boolean(state.cart?.loaded):state.resultSource==='module'?state.previewModuleRevision===state.moduleRevision:state.previewRevision===state.revision;
    document.querySelectorAll('[data-export]').forEach(b => { b.disabled = loginRequired || (b.dataset.export==='bundle'&&manufacturingRestricted) || cartUnavailable || !resultValid || (!persistent&&state.preview?.layoutValidation?.valid === false) || state.generating || state.exporting || !resultFresh || !checkoutEligible(b.dataset.export) || !checkoutValid() || blockedFormats.has(b.dataset.export) || (b.dataset.export==='lubang'&&selectedLubangImportBlocked().length>0); });
    document.querySelectorAll('[data-module-generate]').forEach(b=>{b.disabled=loginRequired||cartUnavailable||state.generating||state.exporting});
    document.querySelectorAll('[data-checkout-control]').forEach(control=>{control.disabled=state.exporting||state.generating||cartUnavailable});
    renderCartStatus();
    updateMountingButtons();
    $('save-layout-json').disabled=Boolean(editor?.boardFormDirty);$('save-layout-svg').disabled=loginRequired||Boolean(editor?.boardFormDirty);
    const bundleButton = document.querySelector('[data-export="bundle"]');
    bundleButton.querySelector('span:not(.file-type)').textContent = manufacturingRestricted ? '图纸和模型下载需登录' : bundleBlocked ? '所选资料待补齐' : '结算并导出所选资料包';
    if(manufacturingRestricted)bundleButton.setAttribute('aria-describedby','manufacturing-download-access-note');else if (bundleBlocked) bundleButton.setAttribute('aria-describedby', 'bundle-blocked-note'); else bundleButton.removeAttribute('aria-describedby');
    document.querySelectorAll('[data-selected-badge]').forEach(b => { const card=libraryCards().find(k=>k.id===b.dataset.selectedBadge); const qty = card ? libraryCardQuantity(card) : 0; b.hidden = !qty; b.textContent = `已选 ${qty} 套`; });
  }
  function libraryCards() { return window.ZZLabPeriscopes.cards(state.catalog).filter(k=>k.libraryVisibility!=='compatibility-only'&&!['one-to-three','dp-module'].includes(k.id)); }
  function libraryCardQuantity(card) { return window.ZZLabPeriscopes.quantity(card,state.quantities)+(card.compatibilityKitIds||[]).reduce((total,id)=>total+(state.quantities.get(id)||0),0); }
  function visibleBoards() { return (state.catalog.registeredBoards||[]).filter(b=>!b.stageOnly&&b.libraryVisibility!=='compatibility-only'); }
  function renderFilters() {
    const categories = [{id:'all', label:'全部套件'}, ...(state.catalog.categories || []), ...(visibleBoards().length?[{id:'registered-boards',label:'面包板'}]:[])];
    $('category-filters').innerHTML = categories.map(c => { const count = libraryCards().filter(k => c.id === 'all' || k.category === c.id).length+(['all','registered-boards'].includes(c.id)?visibleBoards().length:0); return `<button type="button" class="filter-button" data-category="${escape(c.id)}" aria-pressed="${state.category === c.id}">${escape(c.label)}<span class="filter-count">${count}</span></button>`; }).join('');
  }
  function renderCards() {
    if (!state.catalog) return;
    flushOpticalInputs();
    const words = state.search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const kits = libraryCards().filter(k => {
      if (state.category !== 'all' && k.category !== state.category) return false;
      const searchable = [(k.periscopeVariants||[]).map(v=>[v.name,v.variant].join(" ")).join(" "), k.name, k.variant, k.description, categoryLabel(k.category), ...(k.components || []).flatMap(ref => { const c = state.components.get(ref.componentId); return c ? [c.name,c.model] : []; })].join(' ').toLocaleLowerCase();
      return words.every(w => searchable.includes(w));
    });
    const boards=visibleBoards().filter(b=>['all','registered-boards'].includes(state.category)&&words.every(w=>[b.name,b.notes,'面包板 Optical Frame'].join(' ').toLocaleLowerCase().includes(w)));
    $('filter-result').textContent = `显示 ${kits.length+boards.length} / ${libraryCards().length+visibleBoards().length} 个套件与面包板`;
    $('search-clear').hidden = !state.search;
    $('kit-grid').innerHTML = kits.map(k => {
      const quantities = k.components || []; const q = libraryCardQuantity(k);
      const detail = quantities.map(ref => { const c = state.components.get(ref.componentId); return `<li><span>${escape(c?.name || ref.componentId)}</span><span>× ${escape(ref.quantity)} ${escape(c?.unit || '')}</span></li>`; }).join('');
      const optional = (k.pendingRequirements || []).map(p => p.label).filter(Boolean);
      const stage=k.stageModuleId,standalone=k.layout?.placementAllowed===false&&!stage,accessory=k.category==='mechanical',dimensionsPending=k.layout?.geometryStatus==='awaiting-dimensions';
      const placementNote=standalone?`<div class="placement-note"><strong>${accessory?'机械配件 · 可按件出单':dimensionsPending?'尺寸资料待补 · 暂不能放入画布':'自带独立底板 · 可整套出单'}</strong><p>${escape(k.layout.note || k.layout.notes || '此模块的安装条件尚未核实，暂不能放入通用面包板。')}</p></div>`:'';
      const moduleControls=standalone&&!dimensionsPending?`<div class="module-order-controls"><label>${accessory?'件数':'套数'}<input data-module-quantity="${escape(k.id)}" type="number" min="1" max="9999" step="1" value="${state.moduleQuantities.get(k.id)||1}" aria-label="${escape(k.name)} ${accessory?'件数':'整套数量'}"></label><button type="button" data-module-generate="${escape(k.id)}" class="secondary-button">加入购物车</button></div>`:'';
      return `<article class="kit-card${standalone?' standalone-module':''}" draggable="${!standalone}" data-kit-id="${escape(k.id)}"${stage?` data-stage-module="${escape(stage)}"`:""} aria-label="${escape(k.name)}"><div class="kit-art">${artwork(k)}<span class="art-category">${escape(categoryLabel(k.category))}</span><span class="art-label">FUNCTION MODULE</span><span class="selected-badge" data-selected-badge="${escape(k.id)}"${q ? '' : ' hidden'}>已选 ${q} 套</span></div><div class="kit-content"><div class="kit-title-line"><h3>${escape(k.name)}</h3>${k.variant ? `<span class="kit-variant">${escape(k.variant)}</span>` : ''}</div><p class="kit-description">${escape(k.description || '根据装配来源整理，可按需求加入方案。')}</p><div class="kit-status-row">${statusTag(k.status,'kit')}<span>${quantities.length} 种已登记器件</span></div>${bundleNote(k)}${placementNote}<div class="kit-bottom">${link(k.sourceUrl, `查看来源 ${externalIcon}`, 'source-link') || (k.sourceReport||k.layout?.sourceReport?`<span class="quiet">${accessory?'来源：用户提供的制造资料':'来源：用户提供的原厂报告'}</span>`:'<span class="quiet">来源待补充</span>')}<button class="add-button" ${stage?`data-add-stage-module="${escape(stage)}"`:`data-add-kit="${escape(k.id)}"`} type="button" aria-label="放置 ${escape(k.name)} 到面包板"${standalone ? ' disabled' : ''}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10"></path></svg>${standalone?'不放入画布':'放置'}</button></div>${standalone&&!dimensionsPending?renderOptical(k,false,`module:${k.id}`):''}${moduleControls}<details class="kit-details"><summary>查看套件组成</summary><ul>${detail || '<li>组成信息待确认</li>'}</ul>${k.notes ? `<p class="kit-notes">${escape(textValue(k.notes))}</p>` : ''}${optional.length ? `<p class="optional-items">可后补：${escape(optional.join('、'))}。未填写不计入。</p>` : ''}</details></div></article>`;
    }).join('');
    if(boards.length)$('kit-grid').insertAdjacentHTML('beforeend',boards.map(b=>{return `<article class="kit-card registered-board-card" draggable="true" data-registered-board="${escape(b.id)}" aria-label="${escape(b.name)} 面包板"><div class="kit-art"><img class="registered-board-preview" src="${escape(window.ZZLabLocalLibrary?window.ZZLabLocalLibrary.imageUrl('./'+(b.cardPreview?.topViewPath||b.topViewPath)):'./'+(b.cardPreview?.topViewPath||b.topViewPath))}" alt="${escape(b.name)} 俯视图" loading="lazy" decoding="async" draggable="false"><span class="art-category">面包板</span></div><div class="kit-content"><h3>${escape(b.name)}</h3><p class="kit-description">${escape(b.displayDimensions||`${b.widthMm} × ${b.heightMm} × ${b.thicknessMm} mm · 原板固定尺寸`)}</p><p class="quiet">${b.holesMm.length} 个已登记孔${b.defaultContents?.length?` · 含 ${b.defaultContents.length} 个可交互器件`:""} · 可直接作为主面包板</p><div class="kit-bottom registered-board-actions"><button class="add-button" type="button" data-use-main-board="${escape(b.id)}" aria-label="将 ${escape(b.name)} 设为主面包板">设为主面包板</button><button class="text-button" type="button" data-add-registered-board="${escape(b.id)}" aria-label="将 ${escape(b.name)} 作为小板加入">作为小板加入</button>${link(b.sourceUrl,'查看来源 '+externalIcon,'source-link')}</div><details class="kit-details"><summary>板件说明</summary><p>${escape(textValue(b.notes)||'孔位与外形来自源模型，不新增加工孔。')}</p></details></div></article>`}).join(''));
    $('catalog-message').hidden = kits.length+boards.length > 0;
    if (!kits.length&&!boards.length) $('catalog-message').innerHTML = `<p>${state.catalog.kits.length ? '没有找到匹配的套件。试试其他名称或功能。' : '套件目录还在整理，稍后即可查看。'}</p>${state.catalog.kits.length ? '<button id="reset-filters" type="button" class="secondary-button">查看全部套件</button>' : ''}`;
  }
  function opticalKey(kitId, slotId) { return `${kitId}::${slotId}`; }
  function opticalType(value) { return ({'半波片':'half-wave','四分之一波片':'quarter-wave'})[value] || value || ''; }
  function modelOptions(slot, selection) {
    if (!(Number(slot.diameterMm) > 0) && !slot.allowedModels?.length) return [];
    const wave = Number(selection.wavelength);
    return (state.catalog.opticalOptions || []).filter(option => {
      if (slot.allowedModels?.length && !slot.allowedModels.includes(option.model)) return false;
      if (option.type !== slot.type || Math.abs(Number(option.diameterMm) - Number(slot.diameterMm)) > .02) return false;
      if (selection.opticalType && opticalType(option.opticalType) !== selection.opticalType) return false;
      if (selection.wavelength?.trim() && Number.isFinite(wave) && wave > 0) {
        if (option.wavelengthNm != null && Math.abs(Number(option.wavelengthNm) - wave) > .01) return false;
        if (Array.isArray(option.wavelengthRange) && (wave < Number(option.wavelengthRange[0]) || wave > Number(option.wavelengthRange[1]))) return false;
      }
      return true;
    });
  }
  function optionListId(kitId, slotId) { return `model-options-${kitId}-${slotId}`; }
  function optionItems(slot, selection) {
    return modelOptions(slot,selection).map(option => {
      const wave = option.wavelengthNm ? `${option.wavelengthNm} nm` : Array.isArray(option.wavelengthRange) ? `${option.wavelengthRange.join('–')} nm` : '';
      return `<option value="${escape(option.model)}" label="${escape([option.name,wave].filter(Boolean).join(' · '))}"></option>`;
    }).join('');
  }
  function modelSource(selection) {
    const known = (state.catalog.opticalOptions || []).find(o => o.model === selection.model?.trim());
    return known ? link(known.sourceUrl,'型号资料 ↗') : '';
  }
  function knownOpticalModel(selection) { const model=selection.model?.trim();return model?((state.catalog.opticalOptions || []).find(option => option.model === model)||(state.catalog.components||[]).find(c=>c.kind==='lubang'&&c.model===model)):null; }
  function opticalKind(selection) { return knownOpticalModel(selection) ? 'lubang' : selection.kind === 'lubang' ? 'lubang' : 'standard'; }
  function opticalPurchaseHint(slot, selection) {
    if(slot.defaultExisting)return selection.inserted===true?'已选择另购替换件，将加入采购清单。':'原装已有'+(slot.existingModel?' '+slot.existingModel:'')+'；未勾选另购，不加入采购清单。';
    if(selection.inserted===false)return '此安装位已明确留空，不采购光学片；原装配自带片也从本实例清单扣除。';
    const original = state.components.get(slot.replacesComponentId);
    const destination = opticalKind(selection) === 'standard' ? '其他配套件清单' : '麓邦采购单';
    return selection.inserted===true?`已绑定本实例；${selection.model?.trim()?'计入'+destination:'型号未定，仍计入'+destination+'的待选项'}。更换或移除前持续保留。`:original ? `原装配为 ${original.model || original.name}，填写型号可替换；选配计入${destination}。` : `按填写的型号计入${destination}，波长仅作备注。`;
  }
  function renderOptical(originalKit, isOpen, instanceId) {
    const kit={...originalKit,id:instanceId || originalKit.id};
    const slots = kit.opticalSlots || [];
    if (!slots.length) return '';
    const populated = slots.filter(s => (state.optical[opticalKey(kit.id,s.id)]?.inserted??Boolean(state.optical[opticalKey(kit.id,s.id)]?.model?.trim()))).length;
    const included = slots.filter(s => s.replacesComponentId||s.defaultExisting).length;
    return `<details class="optical-options" data-optical-details="${escape(kit.id)}"${isOpen ? ' open' : ''}><summary>光学选配 <span>${populated ? `已填 ${populated} 项` : included ? `原装配含 ${included} 项 · 可替换` : '可选 · 不填不计入'}</span></summary>${slots.map(slot => {
      const v = {...(slot.defaultExisting?{model:slot.existingModel||'',inserted:false}:{}),...(state.optical[opticalKey(kit.id,slot.id)]||{})};
      const waveplate = /waveplate|retarder|波片/.test(`${slot.type} ${slot.label}`.toLowerCase());
      return `<div class="optical-slot" data-slot="${escape(slot.id)}"><p class="optical-slot-title">${escape(slot.label || '光学片')} <span>${slot.diameterMm ? `${slot.type === 'pbs' ? '边长 ' : 'Ø'}${escape(slot.diameterMm)} mm · ` : ''}每套 ${escape(slot.quantity || 1)} ${escape(slot.unit || '片')}</span></p>${'inserted'in v||slot.defaultExisting ? `<label class="optical-toggle"><input type="checkbox" data-optical-field="inserted" data-instance="${escape(kit.id)}" data-slot="${escape(slot.id)}" aria-label="${escape(slot.label)} ${slot.defaultExisting?'另购替换件并加入清单':'已安装并加入清单'}"${v.inserted?' checked':''}>${slot.defaultExisting?'另购替换件并加入清单':'已安装并加入清单'}</label><div class="optical-slot-fields"><div class="form-field"><label>器件名称<input data-optical-field="name" data-instance="${escape(kit.id)}" data-slot="${escape(slot.id)}" maxlength="256" value="${escape(v.name||slot.label)}"></label></div><div class="form-field"><label>供应商<input data-optical-field="supplier" data-instance="${escape(kit.id)}" data-slot="${escape(slot.id)}" maxlength="256" value="${escape(v.supplier||'')}" placeholder="可留空"></label></div></div>`:''}<div class="optical-slot-fields">${waveplate ? `<div class="form-field"><label>波片类型<select data-optical-field="opticalType" data-instance="${escape(kit.id)}" data-kit="${escape(kit.id)}" data-slot="${escape(slot.id)}" aria-label="${escape(kit.name)} ${escape(slot.label)} 波片类型"><option value="">可选</option><option value="half-wave"${v.opticalType === 'half-wave' ? ' selected' : ''}>半波片</option><option value="quarter-wave"${v.opticalType === 'quarter-wave' ? ' selected' : ''}>四分之一波片</option></select></label></div>` : ''}<div class="form-field"><label>波长（nm）<input data-optical-field="wavelength" data-instance="${escape(kit.id)}" data-kit="${escape(kit.id)}" data-slot="${escape(slot.id)}" value="${escape(v.wavelength || '')}" list="wavelengths" maxlength="60" placeholder="可选，如 532" aria-label="${escape(kit.name)} ${escape(slot.label)} 波长"></label></div><div class="form-field optical-model"><label>型号<input data-optical-field="model" data-instance="${escape(kit.id)}" data-kit="${escape(kit.id)}" data-slot="${escape(slot.id)}" value="${escape(v.model || '')}" list="${escape(optionListId(kit.id,slot.id))}" maxlength="160" placeholder="选取或填写型号，可留空" aria-label="${escape(kit.name)} ${escape(slot.label)} 型号"></label><datalist id="${escape(optionListId(kit.id,slot.id))}">${optionItems(slot,v)}</datalist></div><div class="form-field optical-supplier"${v.inserted||v.model?.trim() ? '' : ' hidden'}><label>采购分类<select data-optical-field="kind" data-instance="${escape(kit.id)}" data-kit="${escape(kit.id)}" data-slot="${escape(slot.id)}" aria-label="${escape(kit.name)} ${escape(slot.label)} 采购分类"${knownOpticalModel(v) ? ' disabled' : ''}><option value="lubang"${opticalKind(v) === 'lubang' ? ' selected' : ''}>麓邦</option><option value="standard"${opticalKind(v) === 'standard' ? ' selected' : ''}>其他供应商</option></select></label></div></div><p class="optical-slot-hint" data-purchase-hint="${escape(opticalKey(kit.id,slot.id))}">${escape(opticalPurchaseHint(slot,v))}</p><p class="optical-slot-hint" data-model-source="${escape(opticalKey(kit.id,slot.id))}">${modelSource(v)}</p><p class="slot-saved" data-slot-status="${escape(opticalKey(kit.id,slot.id))}"${v.model?.trim() ? '' : ' hidden'}>${slot.defaultExisting&&v.inserted!==true?'原装已有，未选择另购':'已选填，将随清单汇总'}</p></div>`;
    }).join('')}</details>`;
  }
  function storeOpticalInput(input) {
    const scopeId=input.dataset.instance||input.dataset.kit;if(typeof scopeId!=='string'||!['opticalType','wavelength','model','kind','name','supplier','inserted'].includes(input.dataset.opticalField))return null;
    const moduleKit=scopeId.startsWith('module:')?state.kits.get(scopeId.slice(7)):null;
    const isModule=moduleKit?.layout?.placementAllowed===false,instance=isModule?null:editor?.instances.find(i=>i.id===scopeId);
    if(!isModule&&!instance)return null;
    const kit=isModule?moduleKit:state.kits.get(instance.kitId),slot=kit?.opticalSlots?.find(s=>s.id===input.dataset.slot);if(!slot)return null;
    const key=opticalKey(scopeId,slot.id),current=state.optical[key]||{},field=input.dataset.opticalField,value=field==='inserted'?Boolean(input.checked):input.value,changed=(field==='inserted'?current[field]:current[field]||'')!==value;
    if(changed){
      state.optical[key]={...current,[field]:value};
      if(instance?.optics&&['model','opticalType','wavelength','inserted'].includes(field)&&!['coupler','source'].includes(instance.optics.elementType)){
        const optics=deepCopy(instance.optics);
        if(field==='inserted'&&value===false){
          if(optics.elementType==='waveplate'&&Array.isArray(optics.waveplates)){
            const index=kit.opticalSlots.filter(s=>s.type==='waveplate').findIndex(s=>s.id===slot.id);
            if(optics.waveplates[index])optics.waveplates[index].inserted=false;
            optics.inserted=optics.waveplates.some(p=>p.inserted);
          }else optics.inserted=false;
          optics.configured=true;
        }else{
          // A changed SKU cannot prove a focal length or retardance. Pause the
          // simulation for confirmation while retaining the other plate's data.
          optics.configured=false;optics.inserted=false;
          if(field==='model'&&optics.elementType==='lens')optics.focalLengthMm=null;
          if(field==='model'&&optics.elementType==='mirror')optics.mirror={mode:'data',model:String(value).trim(),samples:[]};
        }
        instance.optics=optics;
      }
      const internal=kit.layout?.opticalAssembly?.internalElements?.find(part=>part.slotId===slot.id),savedInternal=internal&&instance?.internalOptics?.[internal.id];
      if(savedInternal&&(field==='model'||['opticalType','wavelength'].includes(field)&&internal.type==='waveplate'||field==='inserted'&&!slot.defaultExisting)){
        const optics=deepCopy(savedInternal);
        if(field==='inserted'){optics.inserted=value;optics.configured=value===false;if(optics.waveplates)optics.waveplates.forEach(p=>p.inserted=value);}
        else{optics.configured=false;if(!slot.defaultExisting)optics.inserted=false;if(optics.elementType==='mirror')optics.mirror={mode:'data',model:String(value).trim(),samples:[]};if(optics.elementType==='dichroic')optics.dichroic={mode:'data',model:String(value).trim(),samples:[]};if(internal.type==='waveplate'){delete optics.waveplates;delete optics.fastAxisDeg;delete optics.retardanceDeg;delete optics.designWavelengthNm;optics.inserted=state.optical[key].inserted!==false;}}
        instance.internalOptics={...instance.internalOptics,[internal.id]:optics};
      }
      editor?.renderOptics?.();
    }
    return {key,kit:{...kit,id:scopeId},slot,changed,isModule};
  }
  function opticalPurchaseRows(instanceId){
    const instance=(editor?.allInstances?.()||editor?.instances||[]).find(i=>i.id===instanceId),kit=state.kits.get(instance?.kitId);if(!kit)return [];
    return (kit.opticalSlots||[]).map(slot=>{
      const key=opticalKey(instanceId,slot.id),v=state.optical[key]||{},original=state.components?.get(slot.replacesComponentId),model=v.model??original?.model??(slot.defaultExisting?slot.existingModel:'')??'',kind=opticalKind({...v,model,...(!v.kind&&original?{kind:original.kind}:{})});
      let selected=slot.defaultExisting?v.inserted===true:typeof v.inserted==='boolean'?v.inserted:Boolean(v.model?.trim()||v.opticalType||original);
      // Earlier projects kept simulation-only installation data. Migrate this
      // only when no purchase entry was ever made; an explicit removal wins.
      if(!slot.defaultExisting&&!Object.keys(v).length&&instance.optics){
        const optics=instance.optics;
        if(optics.elementType==='waveplate'&&slot.type==='waveplate'){
          const index=kit.opticalSlots.filter(s=>s.type==='waveplate').findIndex(s=>s.id===slot.id);
          selected=Boolean(optics.waveplates?optics.waveplates[index]?.inserted:index===0&&optics.inserted);
        }else if(['mirror','lens','pbs'].includes(optics.elementType)&&(kit.opticalSlots||[]).length===1)selected=Boolean(optics.inserted);
      }
      if(!slot.defaultExisting&&typeof v.inserted!=='boolean'){const assembly=kit.layout?.opticalAssembly,internal=assembly?.internalElements?.find(part=>part.slotId===slot.id),nominal=assembly?.version===2&&internal?.type==='waveplate'?internal.opticalDefaults:null,optics=internal&&(instance.internalOptics?.[internal.id]||nominal);if(optics&&(nominal||!Object.keys(v).length))selected=Boolean(optics.inserted);}
      return{slotId:slot.id,label:slot.label,type:slot.type,inserted:selected,name:v.name||original?.name||slot.label,model,supplier:v.supplier??(kind==='lubang'?'麓邦':''),kind,quantity:slot.quantity||1,unit:slot.unit||'片',wavelength:v.wavelength||'',opticalType:v.opticalType||'',notes:v.notes||''};
    });
  }
  function saveOpticalPurchases(instanceId,rows){
    const instance=(editor?.allInstances?.()||editor?.instances||[]).find(i=>i.id===instanceId),kit=state.kits.get(instance?.kitId),slots=kit?.opticalSlots||[];
    if(!kit||!Array.isArray(rows)||rows.length!==slots.length)throw new Error('光学安装位已改变，请重新打开属性。');
    const candidate=deepCopy(state.optical),seen=new Set(),allowed=new Set(['slotId','label','type','inserted','name','model','supplier','kind','quantity','unit','wavelength','opticalType','notes']);
    for(const row of rows){const slot=slots.find(s=>s.id===row?.slotId);if(!slot||seen.has(row.slotId)||Object.keys(row).some(k=>!allowed.has(k))||typeof row.inserted!=='boolean')throw new Error('光学片安装位或安装状态无效。');seen.add(row.slotId);if(row.quantity!==undefined&&row.quantity!==(slot.quantity||1))throw new Error('每个安装位的数量须与套件一致；订购数量可在购物车修改。');
      const value={inserted:row.inserted,quantity:slot.quantity||1,unit:slot.unit||'片'};
      for(const key of ['name','model','supplier','wavelength','opticalType','notes']){const text=row[key]??'';if(typeof text!=='string'||text.length>({notes:2000,wavelength:80}[key]||256)||/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text))throw new Error('光学片名称、型号或供应商文字无效。');value[key]=text.trim();}
      value.name||=slot.label||'光学片';if(!['','half-wave','quarter-wave'].includes(value.opticalType)||value.opticalType&&slot.type!=='waveplate')throw new Error('波片类型与安装位不匹配。');if(row.kind!==undefined&&!['standard','lubang',''].includes(row.kind))throw new Error('采购分类无效。');value.kind=opticalKind({...value,kind:row.kind||'standard'});candidate[opticalKey(instanceId,slot.id)]=value;
    }
    // Clear old controls before the caller's single history commit captures state.
    // Otherwise flushOpticalInputs would overwrite these new values with stale DOM.
    $('plan-body').replaceChildren();
    if(instance)for(const internal of kit.layout?.opticalAssembly?.internalElements||[]){if(internal.type!=='waveplate')continue;const key=opticalKey(instanceId,internal.slotId),before=state.optical[key]||{},after=candidate[key]||{},saved=instance.internalOptics?.[internal.id];if(!saved)continue;const optics=deepCopy(saved);if(['model','opticalType','wavelength'].some(k=>(before[k]||'')!==(after[k]||''))){optics.configured=false;delete optics.waveplates;delete optics.fastAxisDeg;delete optics.retardanceDeg;delete optics.designWavelengthNm;}if(after.inserted===false){optics.inserted=false;optics.configured=true;if(optics.waveplates)optics.waveplates.forEach(p=>p.inserted=false);}else if(before.inserted===false&&after.inserted===true){optics.inserted=true;optics.configured=false;}instance.internalOptics={...instance.internalOptics,[internal.id]:optics};}
    state.optical=candidate;state.extras=state.extras.filter(e=>!(e.instanceId===instanceId&&seen.has(e.slotId)));
    return opticalPurchaseRows(instanceId);
  }
  function flushOpticalInputs() {
    let layoutChanged=false,moduleChanged=false;document.querySelectorAll('#plan-body [data-optical-field], #kit-grid [data-optical-field]').forEach(input=>{const update=storeOpticalInput(input);if(update?.changed){if(update.isModule)moduleChanged=true;else layoutChanged=true}});if(layoutChanged)markChanged();if(moduleChanged)markModuleChanged();
  }
  function syncProjectFields(){ $('project-name').value=state.project.name; $('project-notes').value=state.project.notes;editor?.updateGlobalHeightLabel?.(); }
  function captureExternalState(){
    flushOpticalInputs();
    return deepCopy({...(window.ZZLabLocalLibrary?{localLibrarySnapshot:window.ZZLabLocalLibrary.snapshot}:{}),...(editor?.opticalRenderingPrefs?{opticalRendering:editor.opticalRenderingPrefs()}:{}),extras:state.extras,optical:state.optical,moduleQuantities:Array.from(state.moduleQuantities),mountingSelection:state.mountingSelection,project:state.project,view:editor?.view||null});
  }
  function restoreExternalState(saved){
    if(!saved)return;
    // Discard old input nodes before rendering a different project's selections.
    $('plan-body').replaceChildren();$('kit-grid').replaceChildren();
    state.extras=deepCopy(saved.extras);state.optical=deepCopy(saved.optical);state.moduleQuantities=new Map(saved.moduleQuantities);state.project=deepCopy(saved.project);
    syncMountingSelection(saved.mountingSelection);syncProjectFields();
    if(editor&&saved.view)editor.view=deepCopy(saved.view);
    state.moduleRevision++;if(state.preview&&state.resultSource!=='cart')$('stale-notice').hidden=false;
    resetExtraForm();renderCards();editor?.restoreOpticalRenderingPrefs?.(saved.opticalRendering);
  }
  function copyAttachments(ids){
    flushOpticalInputs();const selected=new Set(ids);
    return deepCopy({optical:Object.fromEntries(Object.entries(state.optical).filter(([key])=>selected.has(key.split('::')[0]))),extras:state.extras.filter(e=>selected.has(e.instanceId))});
  }
  function pasteAttachments(mapping,metadata){
    if(!metadata)return;
    for(const {fromId,toId} of mapping){
      for(const [key,value]of Object.entries(metadata.optical||{}))if(key.startsWith(fromId+'::'))state.optical[toId+key.slice(fromId.length)]=deepCopy(value);
      for(const extra of metadata.extras||[])if(extra.instanceId===fromId)state.extras.push({...deepCopy(extra),id:`extra-${crypto.randomUUID()}`,instanceId:toId});
    }
  }
  function removeAttachments(ids){
    const selected=new Set(ids);$('plan-body').replaceChildren();
    state.optical=Object.fromEntries(Object.entries(state.optical).filter(([key])=>!selected.has(key.split('::')[0])));
    state.extras=state.extras.filter(e=>!selected.has(e.instanceId));if(state.editingExtra&&!state.extras.some(e=>e.id===state.editingExtra))resetExtraForm();
  }
  function renderPlan() {
    flushOpticalInputs();
    const chosen=editor?.selected(), kit=chosen?state.kits.get(chosen.kitId):null;
    const adapter=chosen?.laserAdapter?.enabled===true?editor.validation().laserAdapters?.find(r=>r.instanceId===chosen.id):null;
    const viewNote=adapter?`使用光轴对齐垫板；激光器原安装孔由垫板承接，四个圆柱沉孔固定到面包板。${chosen.laserAdapter.mountingDatumConfirmed?'安装孔基准已按实物核对。':'安装孔基准待实物核对；当前按加工审核版出图。'}`:kit?.layout?.note||kit?.layout?.notes||'按套件俯视外形显示。';
    const mounting=chosen&&kit.layout?.minimumAlignedMountingHoles?editor.validation().mountingAlignment?.find(m=>m.instanceId===chosen.id):null;
    const axis=chosen?editor?.validation().axisHeights?.find(r=>r.instanceId===chosen.id):null;
    const mechanicalOnly=!kit?.layout?.opticalType&&!kit?.layout?.opticalAssembly&&axis?.opticalAxisHeightMm===null;
    const axisStatus=mechanicalOnly?'<div class="instance-axis-status"><p>纯机械器件 · 不参与整体光高换柱</p></div>':axis?`<div class="instance-axis-status"><p>本体光轴到底座：${axis.effectiveExternalAxisHeightsMm?.length?'多端口光高':axis.opticalAxisHeightMm===null?'待确认':axis.opticalAxisHeightMm+' mm'}</p><p>总光轴高度：<strong>${axis.heightResolved===false?'当前柱高无法实现':axis.effectiveExternalAxisHeightsMm?.length?axis.effectiveExternalAxisHeightsMm.map(h=>h+' mm').join(' ↔ '):axis.effectiveAxisHeightMm===null?'待确认':axis.effectiveAxisHeightMm+' mm'}</strong></p><button type="button" class="text-button" data-elevation-instance="${escape(chosen.id)}">光学属性</button></div>`:'';
    const mountingStatus=mounting?`<div class="instance-mounting-status ${mounting.alignedCount<mounting.requiredCount?'insufficient':mounting.partial?'partial':'complete'}" role="status"><strong>${adapter?'垫板固定孔':mounting.alignedCount<mounting.requiredCount?'安装孔不足':mounting.partial?'部分孔已对齐':'安装孔全部对齐'} · ${mounting.alignedCount} / ${mounting.totalCount}</strong><p>${adapter?`垫板厚 ${chosen.laserAdapter.thicknessMm} mm · ${adapter.beamAligned?'出光线已对齐大板孔行 / 孔列':'出光线尚未对齐大板孔阵'}`:`至少需要 ${mounting.requiredCount} 个孔对齐。${mounting.partial?'未对齐的孔不作为固定孔。':''}`}</p></div>`:'';
    const instances=editor?.instances||[],selectedIds=editor?.selectedIds||new Set(),selectionCount=selectedIds.size;
    const layout=editor?.snapshot(),modules=layout?.subBoards||[],module=modules.find(p=>p.id===editor?.selectedModuleId);
    const moduleInspector=module?`<div class="instance-inspector module-inspector"><div class="selected-instance-title"><span class="instance-number">▤</span><div><h3>${escape(module.name)}</h3><p>小板与 ${layout.instances.filter(i=>i.boardId===module.id).length} 个元件一起移动</p></div></div><p class="instance-view-status">${module.board.widthMm} × ${module.board.heightMm} mm · X ${module.xMm} · Y ${module.yMm}</p><button type="button" class="secondary-button" data-edit-module="${escape(module.id)}">编辑小板模块</button></div>`:'';
    const moduleList=modules.length?`<div class="placed-list-heading">小板模块 <span>${modules.length} 个</span></div><div class="placed-list">${modules.map(p=>`<div class="placed-list-row"><button type="button" data-select-module="${escape(p.id)}" class="placed-list-item${p.id===editor.selectedModuleId||p.id===editor.activeBoardId?' active':''}"><span class="instance-number">▤</span><span><strong>${escape(p.name)}</strong><small>${layout.instances.filter(i=>i.boardId===p.id).length} 个元件 · ${p.board.widthMm} × ${p.board.heightMm} mm</small></span></button><button type="button" class="text-button" data-edit-module="${escape(p.id)}" aria-label="编辑 ${escape(p.name)}">编辑</button></div>`).join('')}</div>`:'';
    $('plan-body').innerHTML=(module?moduleInspector:chosen?`<div class="instance-inspector"><div class="selected-instance-title"><span class="instance-number">${escape(editor.label(chosen))}</span><div><h3>${escape(kit.name)}</h3><p>此实例单独选配 · 不影响其他同款器件</p></div></div><div class="instance-position"><label>X（mm）<input type="number" data-position="x" value="${chosen.xMm}" step="${editor.board.pitchMm}"></label><label>Y（mm）<input type="number" data-position="y" value="${chosen.yMm}" step="${editor.board.pitchMm}"></label><label>方向<select data-position="rotation">${[0,90,180,270].map(a=>`<option value="${a}"${a===chosen.rotationDeg?' selected':''}>${a}°</option>`).join('')}</select></label></div>${mountingStatus}${axisStatus}<p class="instance-view-status">${kit.layout?.topViewUrl ? escape(viewNote) : '真实俯视图待补齐，画布暂显示带标记占位框。'}</p>${bundleNote(kit)}${renderOptical(kit,true,chosen.id)}</div>`:selectionCount>1?`<div class="instance-inspector multi-inspector"><h3>已选择 ${selectionCount} 个器件</h3><p>拖动其中任意一个，整体移动。复制、粘贴和删除对整组选中器件生效。</p><p>Ctrl / ⌘ / Shift 点选可增加或取消选择。</p></div>`:`<div class="inspector-empty"><span>⌖</span><h3>${instances.length?'点选画布上的器件':'开始摆放你的光路'}</h3><p>${instances.length?'查看坐标与选配；Ctrl / ⌘ / Shift 点选可多选。':'从左侧拖入套件，或点击「放置」后点选格点。'}</p></div>`)+ moduleList+(instances.length?`<div class="placed-list-heading">${editor?.activeBoardId?'模块内元件':'直接安装的元件'} <span>${instances.length} 个</span></div><div class="placed-list">${instances.map(i=>`<div class="placed-list-row"><button type="button" data-select-instance="${escape(i.id)}" class="placed-list-item${selectedIds.has(i.id)?' active':''}" aria-pressed="${selectedIds.has(i.id)}"><span class="instance-number">${editor.label(i)}</span><span><strong>${escape(state.kits.get(i.kitId).name)}</strong><small>X ${i.xMm} · Y ${i.yMm} · ${i.rotationDeg}°</small></span></button><button type="button" class="placed-item-remove" data-remove-instance="${escape(i.id)}" aria-label="删除第 ${editor.label(i)} 个器件">×</button></div>`).join('')}</div>`:'');
    renderScope();updateButtons();
    $('layout-coordinate').textContent=chosen?`X ${chosen.xMm} · Y ${chosen.yMm} mm`:'左下角为坐标原点';
  }
  function addKit(id) {if(!state.kits.has(id)||state.kits.get(id).layout?.placementAllowed===false)return;editor?.beginPlace(id);}
  function renderScope() {
    const previous = $('extra-scope').value;
    $('extra-scope').innerHTML='<option value="">当前生成的整个方案</option>'+Array.from(state.quantities,([id,q])=>`<option value="${escape(id)}">${escape(state.kits.get(id).name)}（画布 ${q} 套）</option>`).join('')+libraryCards().filter(k=>!state.quantities.has(k.id)&&k.layout?.geometryStatus!=='awaiting-dimensions').map(k=>`<option value="${escape(k.id)}">${escape(k.name)}（${k.layout?.placementAllowed===false?'整套 · 每套':'未放置 · 每套'}）</option>`).join('');
    if(state.kits.has(previous))$('extra-scope').value=previous;
    updateScopeLabel();
  }
  function updateScopeLabel() { $('extra-quantity-label').innerHTML = `${$('extra-scope').value ? '每套数量' : '总数量'} <span aria-hidden="true">*</span>`; }
  function renderExtras() {
    const automatic=[],count=state.extras.length+automatic.length;
    $('extras-count').textContent = count ? `（${count} 项）` : '';
    if($('elevation-accessories'))$('elevation-accessories').innerHTML=automatic.length?`<div class="elevation-auto-heading"><strong>垫高配套材料</strong><span>随垫高设置自动计入清单</span></div>`+automatic.map(group=>`<div class="extra-entry elevation-auto-entry"><div><strong>${escape(group.name)} · ${group.mode==='universalPostReplacement'?'更换万能柱增高':'垫高'} ${group.elevationMm} mm</strong><p>${group.mode==='universalPostReplacement'?'按套件原柱数量替换 · 计入生产清单':group.supportCount+' 组支撑'}</p>${group.materials.map(m=>`<p>${m.replacesComponentId?escape(state.components.get(m.replacesComponentId)?.name||m.replacesComponentId)+' → ':''}${escape(m.name)}${m.model?'（'+escape(m.model)+'）':''} × ${m.quantity} ${escape(m.unit)}</p>`).join('')}</div><button type="button" class="text-button" data-elevation-target="${escape(group.targetId)}" data-elevation-type="${escape(group.targetType)}">修改垫高</button></div>`).join(''):'';
    $('extras-list').innerHTML = state.extras.map(e => {
      const k=state.kits.get(e.kitId),standalone=k?.layout?.placementAllowed===false,instance=e.instanceId?(editor?.allInstances?.()||editor?.instances||[]).find(i=>i.id===e.instanceId):null;const active=e.instanceId?Boolean(instance):!e.kitId||state.quantities.has(e.kitId)||standalone;
      const scope=e.instanceId?`${instance?'第 '+editor.label(instance)+' 个器件':'原实例'} · ${k?.name||'套件'} · ${e.quantity} ${e.unit||'个'}`:standalone?`${k.name} · 每套 ${e.quantity} ${e.unit||'个'}，生成该整套模块时计入`:e.kitId?`${k?.name||'原套件'} · 每套 ${e.quantity} ${e.unit||'个'}${active?`，画布合计 ${e.quantity*state.quantities.get(e.kitId)}`:' · 画布未放置，本次不计入'}`:`当前生成的整个方案 · 总计 ${e.quantity} ${e.unit||'个'}`;
      return `<div class="extra-entry${active ? '' : ' inactive'}"><div><strong>${escape(e.name)}</strong><p>${escape(e.model || '型号待确认')} · ${e.kind === 'lubang' ? '麓邦采购' : '其他采购'}</p><p>${escape(scope)}</p>${e.notes ? `<p>${escape(e.notes)}</p>` : ''}</div><div class="extra-entry-actions"><button type="button" class="text-button" data-edit-extra="${escape(e.id)}" aria-label="编辑 ${escape(e.name)}">编辑</button><button type="button" class="remove-button" data-remove-extra="${escape(e.id)}" aria-label="删除 ${escape(e.name)}"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8"></path></svg></button></div></div>`;
    }).join('');
  }
  function resetExtraForm() { state.editingExtra = null; $('extra-scope').disabled=false; $('extras-form').reset(); $('extra-save').textContent = '＋ 添加补充器件'; $('extra-cancel').hidden = true; updateScopeLabel(); }
  function layoutRequirements(layout){const requires=[];if(layout?.subBoards?.some(p=>p.stageMotion))requires.push('zzlab-stage-motion-v2');if(layout?.collisionOverrides?.length)requires.push('zzlab-collision-overrides-v1');if(layout?.instances?.some(i=>Object.hasOwn(i,'manualMount')||state.catalog?.kits?.some(k=>k.id===i.kitId&&k.layout?.manualMountingPolicy)))requires.push('zzlab-manual-source-mount-v1');return requires.length?{requires}:{};}
  function payload() {
    const extras=state.extras.filter(e=>e.instanceId?(editor?.allInstances?.()||editor?.instances||[]).some(i=>i.id===e.instanceId):!e.kitId||state.quantities.has(e.kitId)).map(e=>({...e}));
    for(const instance of (editor?.allInstances?.()||editor?.instances||[]))for(const slot of state.kits.get(instance.kitId).opticalSlots||[]){
      let opt=state.optical[opticalKey(instance.id,slot.id)];
      if((!opt||!Object.keys(opt).length)&&['waveplate','mirror','pbs','lens'].includes(instance.optics?.elementType)&&!extras.some(e=>e.slotId===slot.id&&e.kitId===instance.kitId&&(!e.instanceId||e.instanceId===instance.id))){
        const legacy=opticalPurchaseRows(instance.id).find(row=>row.slotId===slot.id);
        if(legacy&&(legacy.inserted||instance.optics.configured))opt=legacy;
      }
      if(slot.defaultExisting&&opt?.inserted!==true)continue;
      if(!opt || !('inserted'in opt) && ![opt.model,opt.wavelength,opt.opticalType].some(v=>String(v||'').trim()))continue;
      extras.push({id:`optical:${instance.id}:${slot.id}`,instanceId:instance.id,kitId:instance.kitId,kind:opticalKind(opt),name:opt.name||slot.label||'光学选配',model:(opt.model||'').trim(),quantity:slot.quantity||1,unit:slot.unit||'片',notes:opt.notes||'',slotId:slot.id,wavelength:opt.wavelength||'',opticalType:opt.opticalType||'',...('inserted'in opt?{inserted:opt.inserted}:{}),...(opt.supplier?{supplier:opt.supplier}:{})});
    }
    const layout=editor?.snapshot();
    return {catalogVersion:state.catalog.version,layout,extras,...layoutRequirements(layout)};
  }
  function modulePayload(kitId,quantity) {
    const kit=state.kits.get(kitId),extras=state.extras.filter(e=>!e.instanceId&&(!e.kitId||e.kitId===kitId)).map(e=>({...e}));
    for(const slot of kit.opticalSlots||[]){const opt=state.optical[opticalKey(`module:${kitId}`,slot.id)];if(!opt||!('inserted'in opt)&&![opt.model,opt.wavelength,opt.opticalType].some(v=>String(v||'').trim()))continue;extras.push({id:`module-optical:${kitId}:${slot.id}`,kitId,kind:opticalKind(opt),name:opt.name||slot.label||'光学选配',model:(opt.model||'').trim(),quantity:slot.quantity||1,unit:slot.unit||'片',notes:opt.notes||'',slotId:slot.id,wavelength:opt.wavelength||'',opticalType:opt.opticalType||'',...('inserted'in opt?{inserted:opt.inserted}:{}),...(opt.supplier?{supplier:opt.supplier}:{})});}
    return{catalogVersion:state.catalog.version,items:[{kitId,quantity}],extras};
  }
  async function fetchAPI(path, options = {}) {
    if(window.ZZLAB_LOCAL && !/^\/(?:session|catalog|preview|mounting-holes|export\?format=layout-(?:json|svg))$/.test(path))throw new Error('本地版没有下单、购物车或共享发布功能。');
    // Glass tracing belongs to the optical project. Mechanical APIs receive
    // their existing geometry schema; the saved project retains the chamber.
    if(/^\/(?:preview|mounting-holes|export(?:\?|$))/.test(path)&&typeof options.body==='string'){
      const body=JSON.parse(options.body);
      if(body.layout?.glassChamber){
        delete body.layout.glassChamber;
        if(Array.isArray(body.requires))body.requires=body.requires.filter(x=>x!=='zzlab-glass-chamber-v1');
        options={...options,body:JSON.stringify(body)};
      }
    }
    const response = await fetch(API + path, {headers:{'Content-Type':'application/json'},...options});
    let loginRedirect=false;
    if(response.redirected&&response.url){try{loginRedirect=new URL(response.url).pathname.replace(/\/+$/,'')==='/auth/login'}catch{}}
    if(loginRedirect){markLoginRequired();const error=new Error('请重新登录后继续。当前草稿仍保留在本页，可先保存工程。');error.status=401;error.code='login_required';throw error;}
    if (!response.ok) {
      let body; try { body = await response.json(); } catch { /* The network may return a non-JSON error page. */ }
      if(response.status===401)markLoginRequired();
      if(response.status===403&&body?.error?.code==='manufacturing_download_forbidden'&&state.session?.role==='guest'){loadSessionCapabilities.request=(loadSessionCapabilities.request||0)+1;state.session={...state.session,canDownloadManufacturing:false};renderSessionStatus();}
      const error = new Error(response.status===401?'请重新登录后继续。当前草稿仍保留在本页，可先保存工程。':body?.error?.message || `暂时无法完成请求（${response.status}），请稍后重试。`);
      error.status = response.status; error.code = body?.error?.code; throw error;
    }
    return response;
  }
  function signedInCartSession(){return ['readonly','user','admin'].includes(state.session?.role);}
  function accountCartActive(){return signedInCartSession()&&state.cart?.mode==='account';}
  function cartControlsLocked(){return Boolean(state.exporting||state.generating||(state.resultSource==='cart'&&!accountCartActive())||(accountCartActive()&&(!state.cart.loaded||state.cart.loading||state.cart.busy||state.cart.error||state.cart.pendingAdd)));}
  function emptyCartPreview(){return {lubang:[],manufacturing:[],standard:[],items:[],reviewGroups:[],warnings:[],optionalNotes:[],totals:{kits:0,componentTypes:0}};}
  function renderCartStatus(){
    const cart=state.cart;if(!cart)return;
    const account=accountCartActive(),pending=Boolean(cart.pendingAdd);
    let text=cart.mode==='guest'?'游客临时清单仅保留在当前页面。登录后可使用账号购物车，跨画布和设备继续整理。':cart.mode==='unavailable'?'请登录或刷新登录状态后使用账号购物车。':'正在读取账号购物车…';
    if(account){text=cart.error||(cart.loading?'正在读取账号购物车…':cart.busy?'正在更新购物车…':cart.saving?'正在保存购物车…':cart.dirty?!checkoutValid()?'已勾选器件的数量尚未填完整，修正后会自动保存。':'购物车有修改，正在等待保存…':cart.loaded?'购物车已保存到当前账号 · 清空或更换画布不会影响这里。':'正在读取账号购物车…');}
    $('cart-save-status').textContent=text;$('cart-save-status').classList.toggle('cart-status-error',Boolean(cart.error));
    $('cart-reload').hidden=!signedInCartSession();$('cart-reload').disabled=cart.loading||cart.saving||cart.busy||state.generating||state.exporting;
    $('cart-retry-add').hidden=!pending;$('cart-retry-add').disabled=cart.loading||cart.saving||cart.busy||state.generating||state.exporting||!account;
    $('cart-clear').disabled=!state.preview||!checkoutRows().length||cartControlsLocked();
    $('cart-navigation-count').textContent=String(selectedCheckoutRows().length);
    $('cart-empty').hidden=checkoutRows().length>0;
    $('checkout-persistence-note').textContent=account?'勾选、数量和移除操作自动保存到当前账号。每次“加入购物车”都会累加一份当时的方案；画布修改不影响已加入内容。':'勾选要导出的器件，可直接修改数量或移除项目。游客清单仅保留本页，重新生成会替换临时清单。';
  }
  function cartFailure(error){
    const cart=state.cart;if(!cart)return;
    clearTimeout(cart.timer);cart.timer=null;cart.conflict=error.status===409;
    cart.error=error.code==='cart_account_changed'?'登录账号已变更，请重新载入当前账号的购物车。':error.status===409?'购物车已在其他页面更新，本页修改尚未保存。请重新载入购物车后继续。':error.status===401?'登录已过期，购物车已停止保存。请登录后重新载入。':error.code==='cart_identity_required'?'当前登录身份未绑定个人账号，暂不能使用账号购物车。':error.message||'购物车暂时无法保存，请重新载入后确认。';
    renderCartStatus();updateButtons();
  }
  function applyAccountCart(data){
    if(!data||typeof data.cartId!=='string'||!Number.isInteger(data.revision)||!Array.isArray(data.items)||!data.preview)throw new Error('购物车数据暂时无法读取，请重新载入。');
    const cart=state.cart;cart.mode='account';cart.loaded=true;cart.cartId=data.cartId;cart.revision=data.revision;cart.updatedAt=data.updatedAt;cart.sources=Array.isArray(data.sources)?data.sources:[];cart.dirty=false;cart.error='';cart.conflict=false;
    state.preview=data.preview;state.checkout=new Map(data.items.map(item=>[item.componentId,{selected:item.selected===true&&item.removed!==true,quantity:String(item.quantity),lastValidQuantity:item.quantity,removed:item.removed===true}]));state.checkoutRevision=(state.checkoutRevision||0)+1;state.resultSource='cart';state.resultRequest=null;
    renderResults(data.preview,{keepCheckout:true});updateButtons();
  }
  async function loadAccountCart({confirmDiscard=false}={}){
    if(!signedInCartSession()||state.cart.loading||state.cart.saving||state.cart.busy)return;
    const cart=state.cart;if(confirmDiscard&&cart.dirty&&!window.confirm('重新载入会替换本页尚未保存的购物车修改，继续吗？'))return;
    clearTimeout(cart.timer);cart.timer=null;const epoch=++cart.epoch;cart.mode='account';cart.loading=true;cart.loaded=false;cart.error='';renderCartStatus();updateButtons();
    try{const data=await(await fetchAPI('/cart')).json();if(epoch!==cart.epoch||!signedInCartSession())return;applyAccountCart(data);}
    catch(error){if(epoch===cart.epoch)cartFailure(error);}
    finally{if(epoch===cart.epoch){cart.loading=false;renderCartStatus();updateButtons();}}
  }
  function pauseAccountCart(mode='unavailable'){
    const cart=state.cart;if(!cart)return;clearTimeout(cart.timer);cart.timer=null;cart.epoch++;cart.mode=mode;cart.loaded=false;cart.loading=false;cart.busy=false;cart.saving=false;cart.savePromise=null;cart.error='';cart.pendingAdd=null;renderCartStatus();
  }
  async function syncCartSession(){
    if(!state.cart)return;
    if(signedInCartSession()){if(!accountCartActive()||!state.cart.loaded)await loadAccountCart();return;}
    if(state.session?.role==='guest'){
      if(state.cart.mode!=='guest'){pauseAccountCart('guest');state.preview=emptyCartPreview();state.resultSource='layout';state.resultRequest=null;renderResults(state.preview);}
      renderCartStatus();return;
    }
    pauseAccountCart();
  }
  function allCartItems(){
    return checkoutRows().map(({row})=>{const entry=checkoutEntry(row);return {componentId:row.componentId,quantity:validCheckoutQuantity(entry.quantity)?Number(entry.quantity):(entry.lastValidQuantity||row.quantity),selected:entry.selected===true&&entry.removed!==true,removed:entry.removed===true};});
  }
  function queueCartSave(){
    if(!accountCartActive()||!state.cart.loaded)return;
    const cart=state.cart;cart.dirty=true;cart.editRevision++;clearTimeout(cart.timer);cart.timer=null;
    if(!cart.error&&checkoutValid())cart.timer=setTimeout(()=>{cart.timer=null;void flushAccountCart().catch(()=>{});},450);
    renderCartStatus();
  }
  async function flushAccountCart(){
    const cart=state.cart;if(!accountCartActive()||!cart.loaded)throw new Error('请先载入当前账号的购物车。');
    clearTimeout(cart.timer);cart.timer=null;
    if(cart.savePromise){await cart.savePromise;if(cart.dirty)return flushAccountCart();return;}
    if(cart.error)throw new Error(cart.error);
    if(!checkoutValid())throw Object.assign(new Error('请先修改已勾选器件的无效数量。'),{code:'cart_quantity_invalid'});
    if(!cart.dirty)return;
    const epoch=cart.epoch;cart.saving=true;renderCartStatus();updateButtons();
    const work=(async()=>{
      while(cart.dirty){
        if(!accountCartActive()||epoch!==cart.epoch)throw new Error('登录状态已变化，请重新载入购物车。');
        if(!checkoutValid())throw Object.assign(new Error('请先修改已勾选器件的无效数量。'),{code:'cart_quantity_invalid'});
        const editRevision=cart.editRevision,request={cartId:cart.cartId,revision:cart.revision,items:allCartItems()};
        const data=await(await fetchAPI('/cart/update',{method:'POST',body:JSON.stringify(request)})).json();
        if(epoch!==cart.epoch||!accountCartActive())throw new Error('登录状态已变化，请重新载入购物车。');
        if(data.cartId!==cart.cartId||!Number.isInteger(data.revision))throw new Error('购物车保存结果无法确认，请重新载入。');
        cart.revision=data.revision;cart.updatedAt=data.updatedAt;cart.dirty=editRevision!==cart.editRevision;
      }
    })();cart.savePromise=work;
    try{await work;}
    catch(error){if(epoch===cart.epoch&&error.code!=='cart_quantity_invalid')cartFailure(error);throw error;}
    finally{if(epoch===cart.epoch){cart.savePromise=null;cart.saving=false;renderCartStatus();updateButtons();}}
  }
  function newCartRequestId(){return globalThis.crypto?.randomUUID?.()||`cart-${Date.now()}-${Math.random().toString(36).slice(2,14)}`;}
  async function sendCartAddition(pending){
    const cart=state.cart,epoch=cart.epoch;cart.busy=true;cart.error='';renderCartStatus();updateButtons();
    try{
      const data=await(await fetchAPI('/cart/add',{method:'POST',body:JSON.stringify(pending)})).json();
      if(epoch!==cart.epoch||!accountCartActive())return;
      cart.pendingAdd=null;applyAccountCart(data);notify('已加入购物车。可以继续换一个画布，或在购物车中结算导出。');
    }catch(error){if(epoch===cart.epoch){if(error.status&&error.status<500)cart.pendingAdd=null;if([400,413,422].includes(error.status))cart.error='';else cartFailure(error);}throw error;}
    finally{if(epoch===cart.epoch){cart.busy=false;renderCartStatus();updateButtons();}}
  }
  async function addAccountCart(request,name){
    const cart=state.cart;if(!accountCartActive()||!cart.loaded)throw new Error('请先载入当前账号的购物车。');
    if(cart.pendingAdd)throw new Error('上次加入结果尚未确认，请先点击“重试上次加入”。');
    flushCheckoutInputs();await flushAccountCart();
    const pending={cartId:cart.cartId,revision:cart.revision,requestId:newCartRequestId(),name,payload:deepCopy(request)};cart.pendingAdd=pending;
    await sendCartAddition(pending);
  }
  async function retryCartAddition(){
    const cart=state.cart;if(!cart?.pendingAdd||!accountCartActive()||cart.loading||cart.busy||state.exporting)return;
    state.generating=true;updateButtons();try{await sendCartAddition(cart.pendingAdd);}catch(error){notify(error.message,true);}finally{state.generating=false;updateButtons();}
  }
  async function clearCart(){
    if(cartControlsLocked()||!checkoutRows().length)return;
    if(!window.confirm('清空购物车中的所有项目？画布和工程文件会保留。'))return;
    if(!accountCartActive()){state.preview=emptyCartPreview();state.resultRequest=null;renderResults(state.preview);updateButtons();return;}
    const cart=state.cart;clearTimeout(cart.timer);cart.timer=null;cart.busy=true;updateButtons();
    try{if(cart.savePromise){try{await cart.savePromise;}catch(error){if(error.code!=='cart_quantity_invalid')throw error;}}const epoch=cart.epoch;const data=await(await fetchAPI('/cart/clear',{method:'POST',body:JSON.stringify({cartId:cart.cartId,revision:cart.revision})})).json();if(epoch!==cart.epoch)return;applyAccountCart(data);notify('购物车已清空，画布保留。');}
    catch(error){cartFailure(error);notify(error.message,true);}
    finally{cart.busy=false;updateButtons();}
  }
  function checkoutRows(data=state.preview){return ['lubang','manufacturing','standard'].flatMap(kind=>(data?.[kind]||[]).map(row=>({row,kind})));}
  function resetCheckout(data=state.preview){
    state.checkout=new Map(checkoutRows(data).map(({row})=>[row.componentId,{selected:true,quantity:String(row.baseQuantity??row.quantity),lastValidQuantity:row.baseQuantity??row.quantity,removed:false}]));
    state.checkoutRevision=(state.checkoutRevision||0)+1;
  }
  function checkoutEntry(row){return state.checkout?.get(row.componentId)||{selected:true,quantity:String(row.quantity),removed:false};}
  function validCheckoutQuantity(value){return /^\d+$/.test(String(value))&&Number(value)>=1&&Number(value)<=10000000;}
  function selectedCheckoutRows(){return checkoutRows().filter(({row})=>{const entry=checkoutEntry(row);return entry.selected&&!entry.removed});}
  function checkoutValid(){return selectedCheckoutRows().every(({row})=>validCheckoutQuantity(checkoutEntry(row).quantity));}
  function checkoutEligible(format){return selectedCheckoutRows().some(({kind})=>format==='bundle'||kind===format);}
  function checkoutPayload(){return {items:selectedCheckoutRows().map(({row})=>({componentId:row.componentId,quantity:Number(checkoutEntry(row).quantity)}))};}
  function checkoutReviewData(){
    const data=state.preview||{},selected=selectedCheckoutRows(),ids=new Set(selected.flatMap(({row})=>row.componentIds||[row.componentId])),kits=new Set(selected.flatMap(({row})=>(row.kits||[]).map(kit=>kit.kitId)));
    const reviewGroups=(data.reviewGroups||[]).map(group=>{
      const items=(group.items||[]).filter(item=>item.componentIds?.length?item.componentIds.some(id=>ids.has(id)):item.kitIds?.length?item.kitIds.some(id=>kits.has(id)):selected.length>0);
      return {...group,items,summary:'',blocking:items.some(item=>item.blocking),blockedExports:[...new Set(items.filter(item=>item.blocking).flatMap(item=>item.blockedExports||[]))]};
    }).filter(group=>group.items.length);
    return {...data,reviewGroups,warnings:reviewGroups.length?[]:(data.reviewGroups?.length?[]:data.warnings||[])};
  }
  function selectedLubangImportBlocked(){
    const selected=new Map(selectedCheckoutRows().map(({row})=>[row.componentId,checkoutEntry(row)]));
    return (state.preview?.lubangImport?.blocked||[]).filter(row=>selected.has(row.componentId)).map(row=>({...row,quantity:selected.get(row.componentId).quantity}));
  }
  function renderLubangImportNotice(){
    const note=$('lubang-import-note');if(!note)return;
    const blocked=selectedLubangImportBlocked();
    note.innerHTML='<p>此表按麓邦网站的购物车导入模板生成，仅用于该网站的批量导入。</p>'+(blocked.length?`<p class="lubang-import-warning"><strong>已勾选 ${blocked.length} 项型号待确认，暂不能单独下载导入表。</strong>请补充明确型号或取消勾选。结算完整资料包时，这些项目会另列在“麓邦待确认清单.xlsx”，其余有效型号照常生成导入表。</p><details><summary>查看待确认项目</summary><ul>${blocked.map(row=>`<li>${escape(row.name)} · ${escape(row.model||'型号待确认')} × ${escape(row.quantity)}：${escape(row.reason||'采购型号需确认')}</li>`).join('')}</ul></details>`:'<p>未确认型号需补充或取消勾选；完整资料包会将待确认采购另列，避免误导入。</p>');
  }
  function renderCheckoutReviews(){
    renderLubangImportNotice();
    const data=checkoutReviewData(),blockingItems=normalizedReviewGroups(data).flatMap(group=>group.items).filter(item=>item.blocking&&item.blockedExports?.includes('bundle'));
    const messages=[...new Set(blockingItems.map(item=>item.summary+(item.details?'：'+item.details:'')))];
    $('bundle-blocked-note').hidden=!messages.length;
    $('bundle-blocked-note').innerHTML=messages.length?`<strong>所选资料包暂不可用 · 缺少生产资料</strong><ul>${messages.map(message=>`<li>${escape(message)}</li>`).join('')}</ul><p>可取消勾选缺少资料的器件，再导出其余所选项目；采购单和生产清单仍可下载。</p>`:'';
    const html=renderReviewGroups(data);$('result-warnings').className='review-notice';$('result-warnings').hidden=!html;$('result-warnings').innerHTML=html;
  }
  function renderCheckoutSummary(){
    const rows=checkoutRows(),visible=rows.filter(({row})=>!checkoutEntry(row).removed),selected=selectedCheckoutRows(),removed=rows.filter(({row})=>checkoutEntry(row).removed),invalid=selected.filter(({row})=>!validCheckoutQuantity(checkoutEntry(row).quantity));
    const unitTotals=new Map();for(const {row}of selected){const quantity=checkoutEntry(row).quantity;if(validCheckoutQuantity(quantity))unitTotals.set(row.unit||'个',(unitTotals.get(row.unit||'个')||0)+Number(quantity));}
    const totals=[...unitTotals].map(([unit,quantity])=>`${quantity.toLocaleString('zh-CN')} ${unit}`).join('、');
    $('checkout-summary').textContent=`已勾选 ${selected.length} / ${visible.length} 种器件`+(totals?` · 共 ${totals}`:'')+(removed.length?` · 已移除 ${removed.length} 种`:'');
    $('checkout-error').hidden=!invalid.length;$('checkout-error').textContent=invalid.length?'请将已勾选器件的数量填写为 1–10,000,000 的整数，再导出。':'';
    const all=$('checkout-select-all');all.checked=visible.length>0&&selected.length===visible.length;all.indeterminate=selected.length>0&&selected.length<visible.length;
    for(const kind of ['lubang','manufacturing','standard']){
      const group=visible.filter(item=>item.kind===kind),picked=selected.filter(item=>item.kind===kind);
      $(kind+'-count').textContent=`已勾选 ${picked.length} / ${group.length} 种`;
      const toggle=$(kind+'-table').querySelector('[data-checkout-group]');if(toggle){toggle.checked=group.length>0&&picked.length===group.length;toggle.indeterminate=picked.length>0&&picked.length<group.length;}
    }
    $('checkout-removed').hidden=!removed.length;$('checkout-removed-count').textContent=`已移除的器件 · ${removed.length} 种`;
    $('checkout-removed-list').innerHTML=removed.map(({row})=>`<li><span>${escape(row.name)} <small>${escape(row.model||'型号待确认')}</small></span><button type="button" class="text-button" data-checkout-control data-checkout-restore="${escape(row.componentId)}">恢复</button></li>`).join('');
  }
  function renderCheckoutTables(){
    const active=document.activeElement,focusField=active?.dataset?.checkoutSelect!==undefined?'checkoutSelect':active?.dataset?.checkoutGroup!==undefined?'checkoutGroup':null,focusValue=focusField?active.dataset[focusField]:null;
    for(const kind of ['lubang','manufacturing','standard'])$(kind+'-table').innerHTML=renderTable(state.preview?.[kind]||[],kind);
    if(focusField)for(const el of document.querySelectorAll(focusField==='checkoutSelect'?'[data-checkout-select]':'[data-checkout-group]'))if(el.dataset[focusField]===focusValue)el.focus({preventScroll:true});
  }
  function checkoutChanged(redraw=true){
    state.checkoutRevision=(state.checkoutRevision||0)+1;
    if(redraw)renderCheckoutTables();
    renderCheckoutSummary();renderCheckoutReviews();queueCartSave();updateButtons();
  }
  function checkoutAction(action,componentId){
    if(cartControlsLocked()||!state.preview)return;
    const entry=state.checkout.get(componentId);
    if(action==='remove'&&entry){entry.removed=true;entry.selected=false;}
    else if(action==='restore'&&entry&&entry.removed){entry.removed=false;entry.selected=true;}
    else if(action==='remove-selected'){for(const item of state.checkout.values())if(item.selected&&!item.removed){item.removed=true;item.selected=false;}}
    else if(action==='restore-all'){for(const item of state.checkout.values())if(item.removed){item.removed=false;item.selected=true;}}
    else if(action==='defaults')resetCheckout();
    else return;
    checkoutChanged();
  }
  function onCheckoutInput(e){
    const input=e.target,id=input.dataset?.checkoutQuantity;
    if(id===undefined||cartControlsLocked())return;
    const entry=state.checkout.get(id);if(!entry||entry.removed)return;
    entry.quantity=input.value;if(validCheckoutQuantity(input.value))entry.lastValidQuantity=Number(input.value);input.setAttribute('aria-invalid',String(!validCheckoutQuantity(input.value)));
    checkoutChanged(false);
  }
  function flushCheckoutInputs(){
    let changed=false;for(const input of document.querySelectorAll('[data-checkout-quantity]')){const entry=state.checkout?.get(input.dataset.checkoutQuantity);if(entry&&!entry.removed&&entry.quantity!==input.value){entry.quantity=input.value;if(validCheckoutQuantity(input.value))entry.lastValidQuantity=Number(input.value);input.setAttribute('aria-invalid',String(!validCheckoutQuantity(input.value)));changed=true;}}
    if(changed)checkoutChanged(false);
  }
  function onCheckoutChange(e){
    const input=e.target;if(cartControlsLocked())return;
    if(input.dataset?.checkoutSelect!==undefined){const entry=state.checkout.get(input.dataset.checkoutSelect);if(entry?.removed){const changed=entry.selected;entry.selected=false;input.checked=false;input.disabled=true;if(changed)checkoutChanged();}else if(entry){entry.selected=input.checked;checkoutChanged();}}
    else if(input.dataset?.checkoutGroup!==undefined){for(const {row,kind}of checkoutRows())if(kind===input.dataset.checkoutGroup&&!checkoutEntry(row).removed)state.checkout.get(row.componentId).selected=input.checked;checkoutChanged();}
    else if(input.id==='checkout-select-all'){for(const entry of state.checkout.values())if(!entry.removed)entry.selected=input.checked;checkoutChanged();}
  }
  function reviewBlockedExports(data){
    const result=new Set();for(const group of data?.reviewGroups||[])for(const entry of [group,...(group.items||[])])if(entry.blocking)for(const format of entry.blockedExports||[])result.add(format);return result;
  }
  function normalizedReviewGroups(data){
    const titles={manufacture:'通用工艺',procurement:'采购选型',sourceFiles:'资料核验'};
    const source=Array.isArray(data.reviewGroups)?data.reviewGroups:[];
    if(source.length)return source.map(group=>{const seen=new Set();return{id:group.id,title:titles[group.id]||group.title||'待确认事项',summary:String(group.summary||'').startsWith(String(group.title||'')+'：')?String(group.summary).slice(String(group.title||'').length+1):(group.summary||''),items:(group.items||[]).filter(item=>{const key=String(item.code||'')+'|'+String(item.summary||'')+'|'+String(item.details||'');if(seen.has(key))return false;seen.add(key);return true}).map(item=>({...item,blocking:Boolean(item.blocking??group.blocking),blockedExports:item.blockedExports||group.blockedExports||[]}))}});
    const groups=new Map();for(const warning of new Set((data.warnings||[]).map(textValue).map(x=>x.trim()).filter(Boolean))){
      if(/布局不可用|布局校验|碰撞轮廓|碰撞包络/.test(warning))continue;
      const id=/材料|表面处理|公差|粗糙|螺纹精度|加工工艺/.test(warning)?'manufacture':/采购|选型|型号|舵机|波长|光学片/.test(warning)?'procurement':'sourceFiles';
      if(!groups.has(id))groups.set(id,{id,title:titles[id],summary:'',items:[]});groups.get(id).items.push({summary:warning,details:'',blocking:false});
    }return Array.from(groups.values());
  }
  function renderReviewGroups(data){
    const groups=normalizedReviewGroups(data).map(group=>({...group,items:group.items.filter(item=>!item.blocking)})).filter(group=>group.items.length);
    if(!groups.length)return '';
    return `<div class="review-heading"><strong>加工与采购待确认事项</strong><span>以下是待确认信息，不代表布局报错</span></div><div class="review-groups">${groups.map(group=>{
      const summaries=[...new Set(group.items.map(item=>item.summary).filter(Boolean))],summary=group.summary&&!normalizedReviewGroups(data).find(g=>g.id===group.id)?.items.some(i=>i.blocking)?group.summary:summaries.join('；');
      return `<section class="review-group"><h4>${escape(group.title)}</h4><p>${escape(summary)}</p><details><summary>查看详情 · ${group.items.length} 项</summary><ul>${group.items.map(item=>`<li><strong>${escape(item.summary)}</strong>${item.details?`<p>${escape(item.details)}</p>`:''}${item.componentNames?.length?`<p class="review-components">涉及：${escape([...new Set(item.componentNames)].join('、'))}</p>`:''}</li>`).join('')}</ul></details></section>`;
    }).join('')}</div>`;
  }
  function manufacturingSpec(row){
    const board=row.generatedBoard?(row.boardSpec||row.generatedBoard?.boardSpec||{}):{};
    return {...board,...(board.manufacturingSpec||{}),...(row.manufacturingSpec||{})};
  }
  function specificationText(value){if(value===null||value===undefined||value==='')return '待确认';if(typeof value==='object')return String(value.value||value.label||value.name||'待确认');return String(value)}
  function renderManufacturingSpec(row){
    const spec=manufacturingSpec(row);
    return `<dl class="manufacturing-spec"><div><dt>材料</dt><dd>${escape(specificationText(spec.material))}</dd></div><div><dt>表面处理</dt><dd>${escape(specificationText(spec.surfaceTreatment))}</dd></div></dl>`;
  }

  function renderTable(rows, kind) {
    const visible=rows.filter(row=>!checkoutEntry(row).removed),groupName={lubang:'麓邦采购',manufacturing:'自制生产',standard:'其他配套'}[kind];
    if (!visible.length) return `<p class="table-empty">${rows.length?'这类器件已全部移除，可在“已移除的器件”中恢复。':`本方案没有${groupName}件。`}</p>`;
    return `<table class="checkout-table"><thead><tr><th scope="col" class="checkout-select-cell"><input type="checkbox" data-checkout-control data-checkout-group="${escape(kind)}" aria-label="全选${groupName}器件"></th><th scope="col">器件名称</th><th scope="col">型号 / 编号</th><th scope="col">导出数量</th>${kind==='manufacturing'?'<th scope="col">材料与表面处理</th>':''}<th scope="col">核验状态</th><th scope="col">${kind === 'manufacturing' ? '资料与来源' : '来源'}</th><th scope="col">操作</th></tr></thead><tbody>${visible.map(r => {
      const entry=checkoutEntry(r),sources=(r.kits||[]).map(k => `${k.name}：${k.kitQuantity} ${k.kitId ? '套' : '份'} × ${k.perKitQuantity} ${r.unit || '个'}/${k.kitId ? '套' : '份'}`).join('；');
      const notes=textValue(r.notes);
      const files = kind === 'manufacturing' ? ((r.generatedBoard||r.generatedLaserAdapter) ? '<span>STEP 按参数生成</span><span>三视图按参数生成</span>' : `${r.stepPath ? '<span>STEP 已备</span>' : '<span class="pending-file">STEP 待补充</span>'}${r.drawingPath ? '<span>图纸已备</span>' : '<span class="pending-file">图纸待补充</span>'}`) : '';
      return `<tr${entry.selected?'':' class="checkout-unselected"'}><td class="checkout-select-cell"><input type="checkbox" data-checkout-control data-checkout-select="${escape(r.componentId)}" aria-label="导出 ${escape(r.name)}"${entry.selected?' checked':''}></td><td class="checkout-name-cell"><span class="cell-name">${escape(r.name)}</span>${sources ? `<div class="cell-note">${sources.length>110?`<details class="cell-details"><summary>原方案使用数量与套件来源</summary><p>${escape(sources)}</p></details>`:escape(sources)}</div>` : ''}${notes ? `<details class="cell-details cell-source-notes"><summary>备注与核验记录</summary><p>${escape(notes)}</p></details>` : ''}</td><td class="cell-model">${escape(r.model || '待确认')}</td><td class="cell-quantity"><div class="checkout-quantity"><input type="number" min="1" max="10000000" step="1" inputmode="numeric" required data-checkout-control data-checkout-quantity="${escape(r.componentId)}" value="${escape(entry.quantity)}" aria-label="${escape(r.name)} 导出数量" aria-invalid="${!validCheckoutQuantity(entry.quantity)}"><small>${escape(r.unit || '个')}</small></div><small class="checkout-original">原方案 ${escape(r.baseQuantity??r.quantity)} ${escape(r.unit||'个')}</small></td>${kind==='manufacturing'?`<td class="cell-manufacturing-spec">${renderManufacturingSpec(r)}</td>`:''}<td>${statusTag(r.status,kind)}</td><td><div class="table-links">${files}${link(r.sourceUrl,'核对来源 ↗') || (kind === 'manufacturing' ? '' : '<span class="quiet">手动补充</span>')}</div></td><td><button type="button" class="text-button checkout-remove" data-checkout-control data-checkout-remove="${escape(r.componentId)}" aria-label="从清单移除 ${escape(r.name)}">移除</button></td></tr>`;
    }).join('')}</tbody></table>`;
  }
  function renderResults(data,{keepCheckout=false}={}) {
    const groups = ['lubang','manufacturing','standard'];
    if(!keepCheckout)resetCheckout(data);renderCheckoutTables();renderCheckoutSummary();
    $('standard-section').hidden = !data.standard?.length;
    const types = data.totals?.componentTypes ?? groups.reduce((a,k) => a + (data[k]?.length || 0),0);
    const quantity = data.totals?.kits ?? Array.from(state.quantities.values()).reduce((a,b) => a+b,0);
    const resultKit=state.resultSource==='module'?state.kits.get(state.resultRequest?.items?.[0]?.kitId):null,moduleName=resultKit?.name,accessory=resultKit?.category==='mechanical';
    $('results-title').textContent=state.resultSource==='cart'?'我的购物车':moduleName?`${moduleName} · 临时清单`:'临时清单';
    $('results-summary').textContent=moduleName?`原方案：${quantity} ${accessory?'件机械配件':'套完整模块'} · ${types} 种器件。本次导出以勾选项目为准。`:`原方案：${state.preview?.totals?.boards??1} 块面包板 + ${quantity} 套 · ${types} 种器件。本次导出以勾选项目为准。`;
    if(state.resultSource==='cart')$('results-summary').textContent=`已加入 ${state.cart.sources.length} 份方案 · ${types} 种器件。可继续添加其他画布或整套模块。`;
    $('result-scope-note').hidden=state.resultSource==='cart'?!state.cart.sources.length:!moduleName;$('result-scope-note').textContent=moduleName&&accessory?`本次清单包含 ${moduleName} × ${quantity} 件及手动补充的配件。`:moduleName?`本次清单包含 ${moduleName} × ${quantity} 套及符合范围的光学选配、补充器件。若要导出面包板上的方案，请点击画布右侧的「加入购物车」。`:'';
    if(state.resultSource==='cart')$('result-scope-note').textContent='已加入：'+state.cart.sources.map(source=>source.name).join('；');
    renderCheckoutReviews();renderCartStatus();
    let optional = $('optional-result-notes');
    if (!optional) { optional = document.createElement('div'); optional.id = 'optional-result-notes'; optional.className = 'optional-result-notes'; $('result-warnings').after(optional); }
    const optionalNotes = Array.isArray(data.optionalNotes) ? data.optionalNotes : [];
    optional.hidden = !optionalNotes.length;
    optional.innerHTML = optionalNotes.length ? `<details><summary>光学片与螺钉可后补 · 未填写不自动计入</summary><ul>${optionalNotes.map(n => `<li>${escape(textValue(n))}</li>`).join('')}</ul></details>` : '';
    $('stale-notice').hidden = true; $('results').hidden = false;
  }
  async function generate() {
    flushOpticalInputs();
    if(state.generating||state.exporting||!editor||!editor.validation().valid||editor.boardFormDirty||editor.manualMounting)return;
    const revision=state.revision,request=payload();state.generating=true;updateButtons();
    try{
      if(signedInCartSession())await addAccountCart(request,state.project.name||'画布方案');
      else{
        if(state.session?.role!=='guest')throw new Error('请先登录并载入购物车。');
        const data=await(await fetchAPI('/preview',{method:'POST',body:JSON.stringify(request)})).json();
        if(revision!==state.revision){notify('方案刚刚有调整，请重新生成临时清单。');return;}
        state.preview=data;state.previewRevision=revision;state.resultSource='layout';state.resultRequest=request;renderResults(data);notify('临时清单已生成。登录后可使用账号购物车。');
      }
      $('results-title').focus({preventScroll:true});$('results').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
    }catch(error){notify(error.message,true);}
    finally{state.generating=false;updateButtons();}
  }
  async function generateModule(kitId) {
    flushOpticalInputs();
    const kit=state.kits.get(kitId);if(!kit||kit.layout?.placementAllowed!==false||state.generating||state.exporting)return;
    const quantityInput=Array.from(document.querySelectorAll('[data-module-quantity]')).find(input=>input.dataset.moduleQuantity===kitId),quantity=Number(quantityInput?.value??state.moduleQuantities.get(kitId)??1);
    if(!validQuantity(quantity))return notify('套数请输入 1–9999 的整数。',true);
    if(quantity!==(state.moduleQuantities.get(kitId)||1)){state.moduleQuantities.set(kitId,quantity);markModuleChanged();}
    const request=modulePayload(kitId,quantity),revision=state.moduleRevision;state.generating=true;updateButtons();
    try{
      if(signedInCartSession())await addAccountCart(request,`${kit.name} × ${quantity} ${kit.category==='mechanical'?'件':'套'}`);
      else{
        if(state.session?.role!=='guest')throw new Error('请先登录并载入购物车。');
        const data=await(await fetchAPI('/preview',{method:'POST',body:JSON.stringify(request)})).json();
        if(revision!==state.moduleRevision)return notify('整套数量已调整，请重新生成。');
        state.resultSource='module';state.resultRequest=request;state.preview=data;state.previewModuleRevision=revision;renderResults(data);notify(`${kit.name} 临时清单已生成。`);
      }
      $('results').scrollIntoView({behavior:'smooth',block:'start'});$('results-title').focus({preventScroll:true});
    }catch(error){notify(error.message,true);}finally{state.generating=false;updateButtons();}
  }
  function downloadName(header, format) {
    const utf = header?.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
    if (utf) { try { return decodeURIComponent(utf[1]).replace(/[\/\\]/g,'_'); } catch { /* Use the ordinary filename or fallback. */ } }
    const plain = header?.match(/filename\s*=\s*"?([^";]+)"?/i);
    return plain ? plain[1].replace(/[\/\\]/g,'_') : {lubang:'麓邦采购.xlsx',manufacturing:'生产清单.xlsx',bundle:'光路套件生产包.zip'}[format];
  }
  async function exportList(format) {
    if(format==='bundle'&&state.session?.role==='guest'&&state.session.canDownloadManufacturing===false)return notify('管理员已关闭游客的图纸和三维模型下载。仍可下载清单表格与工程；完整资料包请登录后下载。',true);
    flushOpticalInputs();flushCheckoutInputs();
    const persistent=state.resultSource==='cart',moduleResult=state.resultSource==='module',fresh=persistent?state.cart?.loaded:moduleResult?state.previewModuleRevision===state.moduleRevision:state.previewRevision===state.revision;
    if(!['lubang','manufacturing','bundle'].includes(format)||state.exporting||state.generating||!fresh||!checkoutEligible(format))return;
    if(persistent){if(!accountCartActive()||state.cart.error||state.cart.pendingAdd)return;}
    else if(!state.resultRequest||(!moduleResult&&(!editor?.validation().valid||editor.boardFormDirty||state.preview?.layoutValidation?.valid===false)))return;
    if(!checkoutValid())return notify('请先修改已勾选器件的无效数量。',true);
    if(reviewBlockedExports(checkoutReviewData()).has(format))return;
    const unresolved=selectedLubangImportBlocked();if(format==='lubang'&&unresolved.length)return notify(`有 ${unresolved.length} 项采购型号待确认，请补充明确型号或取消勾选后下载麓邦导入表。`,true);
    state.exporting=true;updateButtons();notify(format==='bundle'?(unresolved.length?`正在整理资料；${unresolved.length} 项型号待确认采购将另列，不写入麓邦导入表。`:'正在整理所选资料与清单…'):format==='lubang'?'正在生成麓邦购物车导入表…':'正在生成表格…');
    try{
      if(persistent)await flushAccountCart();
      const request=persistent?{cartId:state.cart.cartId,revision:state.cart.revision}:{...state.resultRequest,checkout:checkoutPayload()};
      const response=await fetchAPI((persistent?'/cart/export?format=':'/export?format=')+format,{method:'POST',body:JSON.stringify(request)}),blob=await response.blob();
      const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=downloadName(response.headers.get('Content-Disposition'),format);document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);notify('文件已准备好，正在下载。');
    }catch(error){if(persistent&&(error.code==='cart_conflict'||error.code==='cart_account_changed'||error.status===401))cartFailure(error);notify(error.message,true);}
    finally{state.exporting=false;updateButtons();}
  }
  function normalizedSession(raw){
    if(!raw||!['guest','readonly','user','admin'].includes(raw.role))throw new Error('访问身份暂时无法确认。');
    if('canDownloadManufacturing'in raw&&typeof raw.canDownloadManufacturing!=='boolean')throw new Error('下载权限暂时无法确认。');
    return{role:raw.role,canPublish:['user','admin'].includes(raw.role)&&raw.canPublish===true,canDownload:true,canDownloadManufacturing:raw.role!=='guest'||raw.canDownloadManufacturing!==false,loaded:true};
  }
  function renderSessionStatus(){
    if(window.ZZLAB_LOCAL){$('access-status-text').textContent='本地专业编辑 · 无下单功能';$('access-login').hidden=true;if(editor)updateButtons();return;}
    const session=state.session||{},role=session.role,labels={guest:session.canDownloadManufacturing===false?'游客 · 可编辑与下载清单，图纸和模型需登录':'游客 · 可编辑与下载',readonly:'只读账号 · 可编辑与下载',user:'已登录 · 可编辑与下载',admin:'管理员 · 可编辑与下载',unauthenticated:'请登录后继续 · 草稿保留在本页'};
    $('access-status-text').textContent=labels[role]||(session.loaded?'登录状态暂无法确认，请刷新重试。':'正在确认登录状态…');
    $('access-login').hidden=!['guest','unauthenticated'].includes(role);sharedLibrary?.updateContext();guestAccessManager?.updateContext();if(editor)updateButtons();
  }
  function markLoginRequired(){
    // Invalidate older capability responses without touching the user's project or undo stack.
    loadSessionCapabilities.request=(loadSessionCapabilities.request||0)+1;
    state.session={role:'unauthenticated',canPublish:false,canDownload:false,canDownloadManufacturing:false,loaded:true};pauseAccountCart();renderSessionStatus();
  }
  async function loadSessionCapabilities(){
    const request=loadSessionCapabilities.request=(loadSessionCapabilities.request||0)+1;
    try{const response=await fetchAPI('/session'),session=normalizedSession(await response.json());if(request!==loadSessionCapabilities.request)return;state.session=session;}
    catch(error){if(request!==loadSessionCapabilities.request)return;if(error.status===401){markLoginRequired();return}if(state.session?.role!=='unauthenticated')state.session={role:'unknown',canPublish:false,canDownload:false,canDownloadManufacturing:false,loaded:true};}
    renderSessionStatus();await syncCartSession();
  }
  function requireAccessAdministrator(){if(state.session?.role!=='admin')throw new Error('访问管理仅限管理员账号。');}
  async function readGuestAccess(){requireAccessAdministrator();return(await fetchAPI('/admin/guest-access')).json();}
  async function saveGuestAccess(settings){
    requireAccessAdministrator();return(await fetchAPI('/admin/guest-access',{method:'POST',body:JSON.stringify({guestAccessEnabled:settings.guestAccessEnabled,guestManufacturingDownloadsEnabled:settings.guestManufacturingDownloadsEnabled!==false,revision:settings.revision})})).json();
  }
  function initGuestAccessManager(){
    if(!window.ZZLabGuestAccess)return;guestAccessManager?.destroy();guestAccessManager=window.ZZLabGuestAccess.mount({getContext:()=>state.session,load:readGuestAccess,save:saveGuestAccess,onSaved:()=>loadSessionCapabilities(),notify});
  }
  async function loadCatalog() {
    void loadSessionCapabilities();
    $('catalog-message').hidden = false; $('catalog-message').innerHTML = '<span class="loader" aria-hidden="true"></span><p>正在读取套件信息</p>';
    try {
      const response = await fetchAPI('/catalog'); let catalog = await response.json();
      let localPin=response.headers.get('X-ZZLab-Library');
      if(window.ZZLabLocalLibrary){
        // Resolve the saved draft before constructing an editor: a newer board
        // revision must never make restoration silently drop the old layout.
        try{
          const draft=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
          if(draft?.layout){const resolved=await window.ZZLabLocalLibrary.resolve(draft);catalog=resolved.catalog;localPin=resolved.snapshot;}
        }catch(error){$('restore-notice').hidden=false;$('restore-notice').textContent='原草稿版本暂未恢复：'+error.message;}
      }
      if (!Array.isArray(catalog.kits) || !Array.isArray(catalog.components) || !Array.isArray(catalog.categories)) throw new Error('套件目录暂不可用，请稍后重试。');
      if(window.ZZLabLocalLibrary){window.ZZLabLocalLibrary.prepare(catalog,localPin);window.ZZLabLocalLibrary.pin(localPin);}
      state.catalog = catalog; state.kits = new Map(catalog.kits.map(k => [k.id,k])); state.components = new Map(catalog.components.map(c => [c.id,c]));
      $('catalog-count').textContent = libraryCards().length+visibleBoards().length;
      if (catalog.updatedAt) { const date = new Date(catalog.updatedAt); if (!Number.isNaN(date.valueOf())) $('catalog-updated').textContent = `更新于 ${date.toLocaleDateString('zh-CN')}`; }
      restore();prepareSavedLayout(catalog);
      editor=new window.BreadboardEditor({catalog,saved:savedLayout,notify,onChange:syncLayout,onSelect:()=>{requestPlanRender();requestPersist()},onCopy:copyAttachments,onPaste:pasteAttachments,onRemove:removeAttachments,captureExternalState,restoreExternalState});editor.onBeforeContextChange=flushOpticalInputs; editor.onKitConfigurationChange=instances=>{state.extras=window.ZZLabPeriscopes.rebindExtras(state.extras,instances);};editor.opticalPurchases=()=>state.optical;editor.opticalPurchaseRows=opticalPurchaseRows;editor.saveOpticalPurchases=saveOpticalPurchases;editor.onOpticalRenderingChange=requestPersist;editor.initStacked?.(savedLayout);editor.initElevation?.();editor.initGlobalHeight?.({getTarget:()=>state.project.opticalAxisTargetMm,setTarget:value=>{state.project.opticalAxisTargetMm=value;},preview:async layout=>(await(await fetchAPI('/preview',{method:'POST',body:JSON.stringify({layout,extras:[],catalogVersion:state.catalog.version,...layoutRequirements(layout)})})).json())});if(savedLayout?.subBoards&&editor.loadLayout){const selectedOwner=savedLayout.instances.find(i=>savedProjectUI?.selectedIds?.includes(i.id))?.boardId||null;editor.loadLayout(savedLayout,selectedOwner)}syncMountingSelection(state.mountingSelection);syncProjectFields();
      if(window.ZZLabLocalLibrary){
        const restoreHistory=editor.restoreHistory;
        editor.restoreHistory=function(saved){
          const snapshot=saved.externalState?.localLibrarySnapshot;
          if(snapshot&&snapshot!==window.ZZLabLocalLibrary.snapshot)useLocalProjectLibrary({catalog:window.ZZLabLocalLibrary.catalog(snapshot),snapshot});
          return restoreHistory.call(this,saved);
        };
      }
      if(savedProjectUI?.view&&['x','y','w','h'].every(k=>Number.isFinite(savedProjectUI.view[k]))&&savedProjectUI.view.w>0&&savedProjectUI.view.h>0)editor.view=deepCopy(savedProjectUI.view);
      editor.setSelection(Array.isArray(savedProjectUI?.selectedIds)?savedProjectUI.selectedIds:[]);editor.render();
      const scopes=new Set([...(editor.allInstances?.()||editor.instances).map(i=>i.id),...catalog.kits.filter(k=>k.layout?.placementAllowed===false).map(k=>'module:'+k.id)]);state.optical=Object.fromEntries(Object.entries(state.optical).filter(([key])=>scopes.has(key.split('::')[0])));
      updateQuantities(editor.snapshot());
      $('board-empty-guide').hidden=Boolean((editor.allInstances?.()||editor.instances).length||editor.stacked?.subBoards.length);
      renderFilters();renderCards();renderPlan();renderExtras();initSharedLibrary();editor.restoreOpticalRenderingPrefs?.(savedOpticalRendering);
    } catch (error) { $('filter-result').textContent = '套件库暂时不可用'; $('catalog-message').innerHTML = `<p>${escape(error.message)}</p><button id="retry-catalog" class="secondary-button" type="button">重新加载</button>`; }
  }
  $('category-filters').addEventListener('click', e => { const b=e.target.closest('[data-category]'); if (!b) return; state.category=b.dataset.category; renderFilters(); renderCards(); document.querySelectorAll('[data-category]').forEach(el => { if (el.dataset.category === state.category) el.focus({preventScroll:true}); }); });
  $('kit-search').addEventListener('input', e => { state.search=e.target.value; renderCards(); });
  $('search-clear').addEventListener('click', () => { state.search=''; $('kit-search').value=''; renderCards(); $('kit-search').focus(); });
  $('catalog-message').addEventListener('click', e => { if(e.target.closest('#retry-catalog')) loadCatalog(); if(e.target.closest('#reset-filters')) {state.search=''; state.category='all'; $('kit-search').value=''; renderFilters(); renderCards();} });
  $('kit-grid').addEventListener('click',e=>{const main=e.target.closest('[data-use-main-board]');if(main){try{requireSharedEditor();editor.setRegisteredMainBoard(main.dataset.useMainBoard)}catch(error){notify(error.message,true)}return;}const stage=e.target.closest('[data-add-stage-module]');if(stage){try{requireSharedEditor();editor.addStageModule(stage.dataset.addStageModule)}catch(error){notify(error.message,true)}return;}const registered=e.target.closest('[data-add-registered-board]');if(registered){try{requireSharedEditor();editor.addRegisteredBoard(registered.dataset.addRegisteredBoard)}catch(error){notify(error.message,true)}return;}const b=e.target.closest('[data-add-kit]');if(b)addKit(b.dataset.addKit);const m=e.target.closest('[data-module-generate]');if(m)generateModule(m.dataset.moduleGenerate);});
  $('kit-grid').addEventListener('change',e=>{const input=e.target;if(!input.matches('[data-module-quantity]'))return;if(!validQuantity(input.value)){input.value=state.moduleQuantities.get(input.dataset.moduleQuantity)||1;return notify('套数请输入 1–9999 的整数。',true)}state.moduleQuantities.set(input.dataset.moduleQuantity,Number(input.value));markModuleChanged();});
  $('plan-body').addEventListener('click',e=>{const height=e.target.closest('[data-elevation-instance], [data-elevation-board]');if(height){editor.openElevationProperties?.(height.dataset.elevationBoard?'board':'instance',height.dataset.elevationBoard||height.dataset.elevationInstance);return}const edit=e.target.closest('[data-edit-module]');if(edit){editor.editModule?.(edit.dataset.editModule);return}const module=e.target.closest('[data-select-module]');if(module){editor.selectModule?.(module.dataset.selectModule);return}const remove=e.target.closest('[data-remove-instance]');if(remove){editor.select(remove.dataset.removeInstance);editor.remove();return}const select=e.target.closest('[data-select-instance]');if(select)editor.select(select.dataset.selectInstance,{toggle:e.ctrlKey||e.metaKey||e.shiftKey});});
  $('plan-body').addEventListener('change',e=>{if(!e.target.matches('[data-position]'))return;const inputs=$('plan-body').querySelectorAll('[data-position]');const v=Object.fromEntries([...inputs].map(i=>[i.dataset.position,Number(i.value)]));if(Number.isFinite(v.x)&&Number.isFinite(v.y))editor.position(v.x,v.y,v.rotation);});
  function onOpticalInput(e) {
    const input=e.target;if(!input.matches('[data-optical-field]'))return;const stored=storeOpticalInput(input);if(!stored)return;const {key,kit,slot,changed,isModule}=stored;if(changed){if(isModule)markModuleChanged();else markChanged();}
    const details=input.closest('[data-optical-details]'),populated=(kit.opticalSlots||[]).filter(s=>(state.optical[opticalKey(kit.id,s.id)]?.inserted??Boolean(state.optical[opticalKey(kit.id,s.id)]?.model?.trim()))).length;if(details)details.querySelector('summary span').textContent=populated?`已填 ${populated} 项`:'可选 · 不填不计入';
    const selection=state.optical[key]||{},list=document.getElementById(optionListId(kit.id,slot.id));if(list)list.innerHTML=optionItems(slot,selection);
    const slotElement=input.closest('.optical-slot'),supplier=slotElement?.querySelector('[data-optical-field="kind"]');if(supplier){supplier.value=opticalKind(selection);supplier.disabled=Boolean(knownOpticalModel(selection));supplier.closest('.optical-supplier').hidden=!(selection.inserted||selection.model?.trim());}
    if(slotElement){slotElement.querySelector('[data-purchase-hint]').textContent=opticalPurchaseHint(slot,selection);slotElement.querySelector('[data-model-source]').innerHTML=modelSource(selection);slotElement.querySelector('[data-slot-status]').hidden=!selection.model?.trim();slotElement.querySelector('[data-slot-status]').textContent=slot.defaultExisting&&selection.inserted!==true?'原装已有，未选择另购':'已选填，将随清单汇总';}
  }
  $('plan-body').addEventListener('input',onOpticalInput);
  $('plan-body').addEventListener('change',onOpticalInput);
  $('kit-grid').addEventListener('input',onOpticalInput);
  $('kit-grid').addEventListener('change',onOpticalInput);
  $('clear-plan').addEventListener('click',()=>{if(!editor?.instances?.length)return;if(!window.confirm(editor.stacked?'清空当前编辑面包板上的器件？其他板与购物车保持不变，可撤销恢复。':'清空画布上的所有套件？可使用撤销恢复摆放。'))return;editor.clear();notify(editor.stacked?'当前板的器件已清空，可撤销恢复。':'画布已清空，可撤销恢复。');});
  $('generate').addEventListener('click',generate);
  document.querySelectorAll('[data-export]').forEach(b => b.addEventListener('click', () => exportList(b.dataset.export)));
  $('results').addEventListener('input',onCheckoutInput);
  $('results').addEventListener('change',onCheckoutChange);
  $('results').addEventListener('click',e=>{
    const remove=e.target.closest('[data-checkout-remove]'),restore=e.target.closest('[data-checkout-restore]'),action=e.target.closest('[data-checkout-action]');
    if(remove)checkoutAction('remove',remove.dataset.checkoutRemove);
    else if(restore)checkoutAction('restore',restore.dataset.checkoutRestore);
    else if(action)checkoutAction(action.dataset.checkoutAction);
  });
  $('cart-reload').addEventListener('click',()=>loadAccountCart({confirmDiscard:true}));
  $('cart-retry-add').addEventListener('click',retryCartAddition);
  $('cart-clear').addEventListener('click',clearCart);
  $('extra-scope').addEventListener('change',updateScopeLabel);
  $('extra-cancel').addEventListener('click',resetExtraForm);
  $('extras-form').addEventListener('submit', e => {
    e.preventDefault(); if(!$('extras-form').reportValidity()) return;
    const name=$('extra-name').value.trim(); if(!name) { $('extra-name').focus(); return; }
    const extra={id:state.editingExtra || `extra-${Date.now()}-${Math.random().toString(36).slice(2,7)}`,kitId:$('extra-scope').value || null,kind:$('extra-kind').value,name,model:$('extra-model').value.trim(),quantity:Number($('extra-quantity').value),unit:$('extra-unit').value.trim() || '个',notes:$('extra-notes').value.trim()};
    if(!validQuantity(extra.quantity)) return notify('数量请输入 1–9999 的整数。',true);
    const index=state.extras.findIndex(x=>x.id===extra.id);if(index>=0&&state.extras[index].instanceId){extra.instanceId=state.extras[index].instanceId;extra.kitId=state.extras[index].kitId;} if(index<0) state.extras.push(extra); else state.extras[index]=extra;
    markChanged();markModuleChanged();renderExtras();resetExtraForm();notify('补充器件已保存。');
  });
  $('elevation-accessories')?.addEventListener('click',e=>{const button=e.target.closest('[data-elevation-target]');if(button)editor.openElevationProperties?.(button.dataset.elevationType,button.dataset.elevationTarget)});
  $('extras-list').addEventListener('click', e => {
    const remove=e.target.closest('[data-remove-extra]'); if(remove) {state.extras=state.extras.filter(x=>x.id!==remove.dataset.removeExtra); markChanged();markModuleChanged();renderExtras();if(state.editingExtra===remove.dataset.removeExtra) resetExtraForm(); return;}
    const edit=e.target.closest('[data-edit-extra]'); if(!edit) return;
    const extra=state.extras.find(x=>x.id===edit.dataset.editExtra); if(!extra) return;
    state.editingExtra=extra.id; $('extra-scope').disabled=Boolean(extra.instanceId); $('extra-scope').value=state.kits.has(extra.kitId)?extra.kitId:''; $('extra-kind').value=extra.kind; $('extra-name').value=extra.name; $('extra-model').value=extra.model || ''; $('extra-quantity').value=extra.quantity; $('extra-unit').value=extra.unit || '个'; $('extra-notes').value=extra.notes || ''; $('extra-save').textContent='保存修改'; $('extra-cancel').hidden=false; updateScopeLabel(); $('extra-name').focus();
  });
  let catalogPointerDrag=null;
  $('kit-grid').addEventListener('pointerdown',e=>{
    const art=e.target.closest('.kit-art'),card=art?.closest('[data-kit-id],[data-registered-board]');
    if(e.button!==0||!editor||!card||(!card.dataset.stageModule&&state.kits.get(card.dataset.kitId)?.layout?.placementAllowed===false))return;
    catalogPointerDrag={pointerId:e.pointerId,kitId:card.dataset.kitId,stageModuleId:card.dataset.stageModule,registeredBoardId:card.dataset.registeredBoard,card,x:e.clientX,y:e.clientY,moved:false};
    $('kit-grid').setPointerCapture?.(e.pointerId);e.preventDefault();
  });
  $('kit-grid').addEventListener('pointermove',e=>{const d=catalogPointerDrag;if(!d||e.pointerId!==d.pointerId)return;if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>6){d.moved=true;d.card.classList.add('dragging')}});
  function finishCatalogDrag(e){
    const d=catalogPointerDrag;if(!d||e.pointerId!==d.pointerId)return;catalogPointerDrag=null;d.card.classList.remove('dragging');
    if($('kit-grid').hasPointerCapture?.(e.pointerId))$('kit-grid').releasePointerCapture(e.pointerId);
    if(e.type==='pointercancel'||!d.moved||!editor)return;
    const rect=$('board-svg').getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)return;
    try{requireSharedEditor();const p=editor.sceneWorld?editor.sceneWorld(e):editor.world(e),b=editor.snapshot().board;if(p.xMm<0||p.yMm<0||p.xMm>b.widthMm||p.yMm>b.heightMm)return;d.stageModuleId?editor.addStageModule(d.stageModuleId,p):d.registeredBoardId?editor.addRegisteredBoard(d.registeredBoardId,p):editor.placeAtEvent?editor.placeAtEvent(d.kitId,e):editor.add(d.kitId,p)}catch(error){notify(error.message,true)}
  }
  $('kit-grid').addEventListener('pointerup',finishCatalogDrag);$('kit-grid').addEventListener('pointercancel',finishCatalogDrag);
  $('kit-grid').addEventListener('dragstart',e=>{const card=e.target.closest('[data-kit-id],[data-registered-board]');if(catalogPointerDrag||!card||e.target.closest('button,a,input,summary')||(!card.dataset.stageModule&&state.kits.get(card.dataset.kitId)?.layout?.placementAllowed===false)){e.preventDefault();return}e.dataTransfer.setData(card.dataset.stageModule?'application/x-zzlab-stage-module':card.dataset.registeredBoard?'application/x-zzlab-registered-board':'application/x-zzlab-kit',card.dataset.stageModule||card.dataset.registeredBoard||card.dataset.kitId);e.dataTransfer.effectAllowed='copy';card.classList.add('dragging')});
  $('kit-grid').addEventListener('dragend',()=>{document.querySelectorAll('.dragging').forEach(c=>c.classList.remove('dragging'));$('board-viewport').classList.remove('drop-target')});
  function updateMountingButtons(){
    $('mounting-auto').disabled=state.session?.role==='unauthenticated'||Boolean(editor?.boardFormDirty)||Boolean(editor?.manualMounting)||state.choosingMounting||!editor;const manual=$('mounting-manual');if(manual)manual.disabled=state.session?.role==='unauthenticated'||Boolean(editor?.boardFormDirty)||state.choosingMounting||!editor;$('mounting-auto').textContent=state.choosingMounting?'正在选孔…':editor?.board.registeredBoardId?(window.ZZLabRegisteredBoards?.recordFor(editor.board,editor.catalog)?.customMountingHoles?'自动选择沉孔':'自动选择原板固定孔'):'自动选择四角孔';for(const id of ['mounting-row-parity','mounting-column-parity','mounting-count'])if($(id))$(id).disabled=state.choosingMounting||(Boolean(editor?.board.registeredBoardId)&&!(id==='mounting-count'&&window.ZZLabRegisteredBoards?.recordFor(editor.board,editor.catalog)?.customMountingHoles));const all=$('stack-auto-all');if(all)all.disabled=$('mounting-auto').disabled||!editor?.stacked?.subBoards.length;
  }
  async function chooseMountingHoles(all=false){
    if(editor?.manualMounting)return notify('请先应用或取消手动选孔，再自动选孔。',true);
    if(!editor||editor.boardFormDirty||state.choosingMounting)return;
    if(all!==true&&editor.snapshot().subBoards?.find(p=>p.id===(editor.activeBoardId||editor.selectedModuleId))?.stageMotion)return notify('位移模块使用已登记的固定基座安装孔，上板不重新选孔。');
    if(all!==true&&editor.selectedModuleId&&!editor.editModule(editor.selectedModuleId))return;
    if(all!==true&&editor.board.registeredBoardId&&!window.ZZLabRegisteredBoards.recordFor(editor.board,state.catalog)?.customMountingHoles){try{const r=window.ZZLabRegisteredBoards.recordFor(editor.board,state.catalog),holes=(r.mountingHoleIds||[]).map(holeId=>({holeId})).filter(h=>!editor.manualMountingError(h,[]));const minimum=r.minimumAlignedMountingHoles||Math.min(4,r.mountingHoleIds.length);if(holes.length<minimum)throw new Error(`原板可用固定孔不足 ${minimum} 个，请移动器件或调整整板位置。`);editor.setMountingHoles(holes);notify('已选用未遮挡且与底板对齐的原板固定孔，没有新增孔。');}catch(error){notify(error.message,true)}return;}
    const selectionNow=()=>({rowParity:$('mounting-row-parity').value,columnParity:$('mounting-column-parity').value,holeCount:Number($('mounting-count')?.value||4),...(editor.stacked?{boardId:all===true?'all':editor.activeBoardId||null}:{})});
    const layout=editor.snapshot(),selection=selectionNow(),fingerprint=JSON.stringify({layout,...selection});state.choosingMounting=true;$('mounting-error').hidden=true;updateButtons();
    try{const response=await fetchAPI('/mounting-holes',{method:'POST',body:JSON.stringify({catalogVersion:state.catalog.version,layout,...layoutRequirements(layout),...selection})});const data=await response.json();if(editor.boardFormDirty||JSON.stringify({layout:editor.snapshot(),...selectionNow()})!==fingerprint){notify('布局或选孔条件刚刚有调整，请再次点击自动选孔。',true);return}
      if(Array.isArray(data.boards)){
        const before=editor.historySnapshot(),next=editor.snapshot();for(const chosen of data.boards){if(!Array.isArray(chosen.mountingHoles)||(!chosen.mountingHoles.every(h=>h.holeId)&&chosen.mountingHoles.length!==selection.holeCount))throw new Error('返回孔数与所选模式不一致。');const board=chosen.boardId?next.subBoards.find(p=>p.id===chosen.boardId)?.board:next.board;if(!board)throw new Error('小板已不存在。');board.mountingHoles=chosen.mountingHoles}editor.loadLayout(next,editor.activeBoardId);editor.commit(before);
      }else{if(!Array.isArray(data.mountingHoles)||data.mountingHoles.length!==selection.holeCount)throw new Error(data.message||'未找到满足条件的安装孔。');editor.setMountingHoles(data.mountingHoles)}
      $('mounting-settings').open=false;editor.render();notify(data.note||'安装孔已保存到当前布局。');}
    catch(error){const message=error.message||'自动选孔失败，请调整器件位置或行列条件。';$('mounting-error').textContent=message;$('mounting-error').hidden=false;notify(message,true)}finally{state.choosingMounting=false;updateButtons();}
  }
  for(const id of ['mounting-row-parity','mounting-column-parity'])$(id).addEventListener('change',()=>{syncMountingSelection({rowParity:$('mounting-row-parity').value,columnParity:$('mounting-column-parity').value});requestPersist();});
  $('mounting-auto').addEventListener('click',chooseMountingHoles);
  $('stack-auto-all')?.addEventListener('click',()=>chooseMountingHoles(true));
  $('stack-import-file')?.addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{requireSharedEditor();if(file.size>window.ZZLabProjectFile.MAX_BYTES)throw new Error('工程文件不能超过8 MiB。');const epoch=state.sharedReadEpoch||0,text=await file.text();requireSharedEditor();if(epoch!==(state.sharedReadEpoch||0))throw new Error('工程已切换，请重新装入模块。');const source=window.ZZLabProjectFile.parse(text,projectOptions()).project;flushOpticalInputs();const current=window.ZZLabProjectFile.create(projectData(),projectOptions()),result=window.ZZLabSharedProject.mountOnBoard(current,source,projectOptions());applyProject(result.project,{focusModule:result.boardId});notify('模块已装入当前画布。拖动可整体移动，右键小板可编辑内部布局；原沉孔不重合时需重新选孔。')}catch(error){notify(error.message,true)}finally{e.target.value=''}});
  $('mounting-clear').addEventListener('click',()=>{if(!editor)return;if(editor.selectedModuleId&&!editor.editModule(editor.selectedModuleId))return;editor.setMountingHoles([]);$('mounting-error').hidden=true;notify('已清除安装沉孔。')});
  async function saveLayout(format){
    flushOpticalInputs();if(!editor)return;if(editor.manualMounting)return notify('请先应用或取消手动选孔，再保存当前画布。',true);
    try{
      const overlay=format==='layout-svg'?editor.captureOpticalExport?.():null,layoutSignature=JSON.stringify(editor.snapshot()),request=JSON.stringify(payload());
      const r=await fetchAPI('/export?format='+format,{method:'POST',body:request});
      let blob=format==='layout-json'?new Blob([JSON.stringify({...await r.json(),ui:{mountingSelection:state.mountingSelection}},null,2)+'\n'],{type:'application/json;charset=utf-8'}):await r.blob();
      if(overlay)blob=new Blob([window.ZZLabOpticalRenderer.composeSvg(await blob.text(),overlay)],{type:'image/svg+xml;charset=utf-8'});
      if(layoutSignature!==JSON.stringify(editor.snapshot())||(overlay&&!editor.isOpticalExportCurrent(overlay)))throw new Error('导出期间画布或光路已变化，请重新点击下载，避免混合不同状态。');
      const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=downloadName(r.headers.get('Content-Disposition'),format)||(format==='layout-json'?'光路布局.json':'光路总俯视图.svg');document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);notify(overlay?'含当前光路的总俯视图已准备好。':'布局文件已准备好。');
    }catch(error){notify(error.message,true)}
  }
  function sharedContext(){
    const plates=editor?.snapshot().subBoards||[],activeId=editor?.activeBoardId||editor?.selectedModuleId;
    return {stageCount:plates.filter(p=>p.stageMotion).length,activeBoardIsStage:Boolean(plates.find(p=>p.id===activeId)?.stageMotion),name:state.project.name,notes:state.project.notes,instanceCount:(editor?.allInstances?.()||editor?.instances||[]).length,selectedCount:editor?.selectedIds.size||0,valid:Boolean(editor?.validation().valid),boardDirty:Boolean(editor?.boardFormDirty),role:state.session?.role||'unknown',canPublish:state.session?.canPublish===true,canDownload:state.session?.canDownload===true,canDownloadManufacturing:state.session?.role==='guest'?state.session.canDownloadManufacturing!==false:state.session?.canDownload===true,hasCarrier:Boolean(editor?.stacked),canMountModules:Boolean(editor),activeBoard:Boolean(editor?.activeBoardId||editor?.selectedModuleId),activeBoardCount:editor?(editor.snapshot().instances.filter(i=>i.boardId===(editor.activeBoardId||editor.selectedModuleId)).length):0};
  }
  function requireSharedEditor(){
    if(!editor||!state.catalog)throw new Error('请等待套件库加载完成。');
    if(editor.boardFormDirty)throw new Error('请先更新面包板参数。');if(editor.manualMounting)throw new Error('请先应用或取消手动选孔。');
  }
  function requireSharedPublisher(){
    if(state.session?.canPublish===true&&['user','admin'].includes(state.session.role))return;
    throw new Error(state.session?.role==='guest'?'请登录普通或管理员账号后发布共享套件。':state.session?.role==='unauthenticated'?'请重新登录后发布共享套件。':state.session?.role==='readonly'?'发布和管理共享套件需要普通或管理员账号；当前账号仍可编辑与下载。':'发布权限暂时无法确认，请刷新页面后重试。');
  }
  async function publishSharedKit({name,description,scope}){
    requireSharedPublisher();requireSharedEditor();
    if(!['all','selection','board'].includes(scope))throw new Error('请选择要发布的器件范围。');
    const complete=window.ZZLabProjectFile.create(projectData(),projectOptions());
    const project=scope==='board'?window.ZZLabSharedProject.extractBoard(complete,editor.activeBoardId||editor.selectedModuleId,projectOptions()):window.ZZLabSharedProject.subset(complete,scope==='selection'?Array.from(editor.selectedIds):null,projectOptions());
    project.metadata.name=String(name||'').trim();project.metadata.notes=String(description||'').trim();
    const response=await fetchAPI('/shared-kits',{method:'POST',body:JSON.stringify({name:project.metadata.name,description:project.metadata.notes,project})});
    return response.json();
  }
  async function readSharedProject(kit){
    const response=await fetchAPI('/shared-kits/'+encodeURIComponent(kit.id)+'/project');
    return window.ZZLabProjectFile.parse(await response.text(),projectOptions());
  }
  async function addSharedKit(kit,platePosition=null){
    requireSharedEditor();const epoch=state.sharedReadEpoch||0,{project:shared,warnings}=await readSharedProject(kit);requireSharedEditor();
    if(epoch!==(state.sharedReadEpoch||0))throw new Error('工程已切换，本次加入已取消；请在当前工程重新点击加入。');
    const current=window.ZZLabProjectFile.create(projectData(),projectOptions());
    const result=window.ZZLabSharedProject.mountOnBoard(current,shared,{...projectOptions(),...(platePosition?{platePosition}:{})});
    applyProject(result.project,{keepSharedReads:true,focusModule:result.boardId});editor.keyboardActive=true;$('board-svg').focus({preventScroll:true});editor.viewport.scrollIntoView({behavior:'smooth',block:'nearest'});
    const messages=[`已装入「${kit.name}」及其小面包板，内部位置与原沉孔保留。可直接整体拖动，右键小板编辑内部布局。`,...warnings,...(result.warnings||[])];
    if(!editor.validation().valid)messages.push('请按画布提示调整位置，再生成清单。');
    notify(messages.join(' '));
  }
  async function openSharedKit(kit){
    requireSharedEditor();flushOpticalInputs();const epoch=state.sharedReadEpoch=(state.sharedReadEpoch||0)+1,revision=state.revision;
    const {project,warnings}=await readSharedProject(kit);requireSharedEditor();
    if(epoch!==state.sharedReadEpoch)throw new Error('已有更新的工程打开操作，本次打开已取消。');
    flushOpticalInputs();if(revision!==state.revision)throw new Error('等待期间当前工程已修改，请重新点击打开，避免覆盖刚才的修改。');
    applyProject(project);editor.viewport.scrollIntoView({behavior:'smooth',block:'nearest'});
    notify([`已打开「${kit.name}」；可撤销回到之前的工程。`,...warnings].join(' '));
  }
  async function downloadSharedKit(kit,format){
    if(!['project','bundle'].includes(format))throw new Error('下载格式无效。');
    if(format==='bundle'&&state.session?.role==='guest'&&state.session.canDownloadManufacturing===false)throw new Error('管理员已关闭游客的图纸和三维模型下载。工程仍可下载；完整资料包请登录后下载。');
    const response=await fetchAPI('/shared-kits/'+encodeURIComponent(kit.id)+'/'+format),blob=await response.blob();
    const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;
    anchor.download=downloadName(response.headers.get('Content-Disposition'),format)||String(kit.name).replace(/[\\/:*?"<>|]/g,'_')+(format==='project'?'.zzoptics.json':'.zip');
    document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);notify('文件已准备好，正在下载。');
  }
  async function dropSharedOnCarrier(kit,position){
    if(!editor)return;
    const svg=$('board-svg'),rect=svg.getBoundingClientRect();
    if(position.clientX<rect.left||position.clientX>rect.right||position.clientY<rect.top||position.clientY>rect.bottom)return;
    const pt=svg.createSVGPoint();pt.x=position.clientX;pt.y=position.clientY;
    const p=pt.matrixTransform(svg.getScreenCTM().inverse()),board=editor.snapshot().board;
    if(p.x<0||p.y<0||p.x>board.widthMm||p.y>board.heightMm)return;
    await addSharedKit(kit,{xMm:p.x,yMm:board.heightMm-p.y});
  }
  function bindStackLibraryDrop(){
    if(bindStackLibraryDrop.bound)return;bindStackLibraryDrop.bound=true;
    for(const id of ['board-svg']){
      const svg=$(id),active=()=>Boolean(editor);
      svg?.addEventListener('dragover',e=>{if(active()&&Array.from(e.dataTransfer.types).includes('application/x-zzlab-shared-kit')){e.preventDefault();e.dataTransfer.dropEffect='copy'}});
      svg?.addEventListener('drop',async e=>{const kitId=e.dataTransfer.getData('application/x-zzlab-shared-kit');if(!active()||!kitId)return;e.preventDefault();try{await dropSharedOnCarrier({id:kitId,name:'共享模块'},{clientX:e.clientX,clientY:e.clientY})}catch(error){notify(error.message,true)}});
    }
  }
  function initSharedLibrary(){
    bindStackLibraryDrop();
    if(!window.ZZLabSharedKits)return;
    sharedLibrary?.destroy();
    sharedLibrary=window.ZZLabSharedKits.mount({getContext:sharedContext,notify,fetchList:async()=> (await fetchAPI('/shared-kits')).json(),onPublish:publishSharedKit,onAdd:addSharedKit,onCarrierDrop:dropSharedOnCarrier,onOpen:openSharedKit,onDownload:downloadSharedKit,onUnpublish:async kit=>{requireSharedPublisher();return(await fetchAPI('/shared-kits/'+encodeURIComponent(kit.id)+'/unpublish',{method:'POST',body:'{}'})).json()},onRestore:async kit=>{requireSharedPublisher();return(await fetchAPI('/shared-kits/'+encodeURIComponent(kit.id)+'/restore',{method:'POST',body:'{}'})).json()}});
    sharedLibrary.refresh();
  }
  function projectData(){
    flushOpticalInputs();
    return {...(editor.opticalRenderingPrefs?{opticalRendering:deepCopy(editor.opticalRenderingPrefs())}:{}),metadata:deepCopy(state.project),catalogVersion:state.catalog.version,layout:editor.snapshot(),optical:deepCopy(state.optical),extras:deepCopy(state.extras),moduleQuantities:Array.from(state.moduleQuantities),ui:{mountingSelection:deepCopy(state.mountingSelection),view:deepCopy(editor.view),selectedIds:Array.from(editor.selectedIds)}};
  }
  function useLocalProjectLibrary({catalog,snapshot}){
    if(!catalog)throw new Error('原工程的元件库未载入，当前工程保留。');
    state.catalog=catalog;state.kits=new Map(catalog.kits.map(k=>[k.id,k]));state.components=new Map(catalog.components.map(c=>[c.id,c]));
    editor.catalog=catalog;editor.kits=state.kits;window.ZZLabRegisteredBoards?.configure(catalog);
    window.ZZLabLocalLibrary.pin(snapshot);
    editor._validationCache=null;editor._stackValidation=null;editor._stackLocalCache=null;editor._opticalSceneCache=null;editor._opticalHoleCache=null;
    editor.stopOpticalAuto?.();
    state.preview=null;state.previewRevision=-1;
    $('catalog-count').textContent=libraryCards().length+visibleBoards().length;
    if(catalog.updatedAt){const date=new Date(catalog.updatedAt);if(!Number.isNaN(date.valueOf()))$('catalog-updated').textContent=`更新于 ${date.toLocaleDateString('zh-CN')}`;}
    renderFilters();
  }
  function parseProjectWithLibrary(text,catalog){
    // Validation uses the candidate catalog without changing the live editor.
    const validator=Object.create(editor);validator.catalog=catalog;
    try{return window.ZZLabProjectFile.parse(text,{catalog,validateBoard:board=>validator.validBoard(board)});}
    finally{window.ZZLabRegisteredBoards?.configure(state.catalog);}
  }
  function projectOptions(){return {catalog:state.catalog,validateBoard:board=>editor.validBoard(board)};}
  function saveProject(){
    if(editor?.manualMounting)return notify('请先应用或取消手动选孔，再保存工程。',true);
    if(!editor)return;if(editor.boardFormDirty)return notify('请先更新面包板参数，再保存工程。',true);
    try{
      const project=window.ZZLabProjectFile.create(projectData(),projectOptions());
      const blob=new Blob([JSON.stringify(project,null,2)+'\n'],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download=project.metadata.name.replace(/[\/:*?"<>|]/g,'_').slice(0,100)+window.ZZLabProjectFile.EXTENSION;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      notify('工程已保存；下次打开此文件即可继续编辑。');
    }catch(error){notify(error.message||'工程未能保存。',true)}
  }
  function applyProject(project,{keepSharedReads=false,focusModule=null,localLibrary=null}={}){
    if(!keepSharedReads)state.sharedReadEpoch=(state.sharedReadEpoch||0)+1;
    const before=editor.historySnapshot();
    try{
      if(localLibrary)useLocalProjectLibrary(localLibrary);
      editor.measurement=null;
      if(editor.loadLayout)editor.loadLayout(project.layout,focusModule?null:project.layout.instances.find(i=>project.ui.selectedIds.includes(i.id))?.boardId||null);else{editor.board=editor.validBoard(project.layout.board);editor.instances=deepCopy(project.layout.instances)}if(focusModule&&editor.selectModule)editor.selectModule(focusModule);else editor.setSelection(project.ui.selectedIds);editor.pendingKitId=null;editor.drag=null;
      restoreExternalState({opticalRendering:project.opticalRendering,extras:project.extras,optical:project.optical,moduleQuantities:project.moduleQuantities,mountingSelection:project.ui.mountingSelection,project:project.metadata,view:project.ui.view});
      editor.syncFields();if(!project.ui.view)editor.fit();
      if(!editor.commit(before))editor.changed();
    }catch(error){editor.restoreHistory(before);editor.changed();throw error}
  }
  $('save-layout-json').addEventListener('click',saveProject);
  $('stack-save-module')?.addEventListener('click',()=>{try{requireSharedEditor();const project=window.ZZLabSharedProject.extractBoard(window.ZZLabProjectFile.create(projectData(),projectOptions()),editor.activeBoardId||editor.selectedModuleId,projectOptions()),blob=new Blob([JSON.stringify(project,null,2)+'\n'],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=project.metadata.name.replace(/[\\/:*?"<>|]/g,'_').slice(0,100)+window.ZZLabProjectFile.EXTENSION;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);notify('小板模块工程已保存，包含本板器件、选配和原沉孔。')}catch(error){notify(error.message,true)}});
  $('save-layout-svg').addEventListener('click',()=>saveLayout('layout-svg'));
  let projectOpenEpoch=0;
  async function openProjectFile(file){
    if(!file)return;
    const epoch=++projectOpenEpoch,revision=state.revision;state.openingProject=true;
    try{
      if(!editor)throw new Error('请等待套件库加载后再打开工程。');
      if(file.size>window.ZZLabProjectFile.MAX_BYTES)throw new Error('工程文件不能超过 8 MiB。');
      if(editor.manualMounting||editor.boardFormDirty)throw new Error('请先完成当前板的参数或选孔编辑。');
      const text=await file.text();
      const localLibrary=window.ZZLabLocalLibrary?await window.ZZLabLocalLibrary.resolve(JSON.parse(text)):null;
      if(epoch!==projectOpenEpoch||revision!==state.revision)throw new Error('读取期间工程已变化，请重新打开文件；当前编辑已保留。');
      const {project,legacy,warnings}=localLibrary?parseProjectWithLibrary(text,localLibrary.catalog):window.ZZLabProjectFile.parse(text,projectOptions());
      if(legacy)project.metadata.name=file.name.replace(/(?:\.zzoptics)?\.json$/i,'').slice(0,120)||'导入的光路工程';
      applyProject(project,{localLibrary});
      notify((legacy?'旧布局已转为可继续编辑的工程。':'工程已打开，已恢复布局和选配。')+(warnings.length?' '+warnings.join(' '):' 可用撤销恢复打开前的工程。'),Boolean(warnings.length));
    }catch(error){if(epoch===projectOpenEpoch)notify(error.name==='SyntaxError'?'JSON 格式不正确，当前工程未改变。':error.message||'工程文件无法读取，当前工程未改变。',true)}finally{if(epoch===projectOpenEpoch)state.openingProject=false}
  }
  $('import-layout').addEventListener('change',e=>{
    const file=e.target.files[0];e.target.value='';void openProjectFile(file);
  });
  window.ZZLabProjectDrop.bind({document,window,overlay:$('project-drop-overlay'),openFile:openProjectFile,notify});
  $('project-name').addEventListener('input',e=>{state.project.name=e.target.value.trim()||'未命名光路工程';markChanged()});
  $('project-name').addEventListener('blur',()=>{$('project-name').value=state.project.name});
  $('project-notes').addEventListener('input',e=>{state.project.notes=e.target.value;markChanged()});
  let viewSaveTimer;
  for(const event of ['pointerup','wheel'])$('board-svg').addEventListener(event,()=>{clearTimeout(viewSaveTimer);viewSaveTimer=setTimeout(requestPersist,250)});
  function saveBeforeLeaving(){flushOpticalInputs();persist()}
  window.addEventListener('beforeunload',saveBeforeLeaving);window.addEventListener('pagehide',saveBeforeLeaving);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')saveBeforeLeaving()});
  $('mobile-plan-jump').addEventListener('click',()=>{ $('plan-panel').scrollIntoView({behavior:'smooth',block:'start'}); $('plan-title').setAttribute('tabindex','-1'); $('plan-title').focus({preventScroll:true}); });
  if ('IntersectionObserver' in window) new IntersectionObserver(entries=>{ $('mobile-plan-jump').classList.toggle('plan-in-view',entries[0].isIntersecting); },{threshold:0.15}).observe($('plan-panel'));
  document.addEventListener('layout-validity-change',updateButtons);
  function localCatalogRevisionIssue(catalog,values){
    const boards=new Map((catalog.registeredBoards||[]).map(row=>[row.id,row]));
    const modules=new Map((catalog.stageModules||[]).map(row=>[row.id,row]));
    const check=value=>{
      if(!value||typeof value!=='object')return '';
      if(value.registeredBoardId){
        const record=boards.get(value.registeredBoardId);
        if(!record||String(record.revision)!==String(value.registeredBoardRevision))return '面包板版本已变化';
      }
      if(value.stageMotion){
        const record=modules.get(value.stageMotion.moduleId);
        if(!record||record.revision!==value.stageMotion.revision)return '位移模块版本已变化';
        try{window.ZZLabMovingStages?.normalizeMotion(value.stageMotion,value.board,catalog);}catch{return '位移模块不再兼容';}
      }
      for(const child of Object.values(value)){const issue=check(child);if(issue)return issue;}
      return '';
    };
    return check(values);
  }
  // Local adapter only: update the catalog without reconstructing the editor.
  // Geometry, optical inputs, selected IDs and both undo stacks remain in place.
  if(window.ZZLAB_LOCAL)window.ZZLabLocalEditor={
    updateCatalog(raw,snapshot){
      if(state.openingProject||!editor||editor.drag||editor.stackDrag||editor.manualMounting||editor.boardFormDirty||editor.pendingKitId||
        state.generating||state.exporting||state.choosingMounting||document.querySelector('dialog[open]')||
        document.activeElement?.matches('input,textarea,select,[contenteditable="true"]'))
        return{ok:false,message:'新元件库已就绪，当前编辑结束后自动载入'};
      const catalog=window.ZZLabLocalLibrary.prepare(deepCopy(raw),snapshot);
      const previous=state.catalog,previousKits=state.kits,previousComponents=state.components,previousPin=window.ZZLabLocalLibrary.snapshot;
      // Never lose an object referenced by an old undo entry or clipboard.
      for(const field of ['kits','components','registeredBoards','stageModules']){
        const ids=new Set((catalog[field]||[]).map(item=>item.id));
        if((previous[field]||[]).some(item=>!ids.has(item.id)))return{ok:false,message:'新版库移除了旧记录，当前工程继续使用原库；保存工程后重新打开可载入新版'};
      }
      // History entries carry their own immutable catalog and restoreHistory pins it.
      // Only entries without a usable catalog must constrain the active palette.
      const unpinnedHistory=[...editor.history,...editor.future].filter(saved=>{
        const own=window.ZZLabLocalLibrary.catalog(saved.externalState?.localLibrarySnapshot);
        return !own||Boolean(localCatalogRevisionIssue(own,saved));
      });
      const revisionIssue=localCatalogRevisionIssue(catalog,[editor.snapshot(),unpinnedHistory,editor.moduleClipboard,editor.clipboard]);
      if(revisionIssue)return{ok:false,message:'新版元件库已同步；当前工程保留原版本，保持原孔位和器件布局'};
      try{
        window.ZZLabProjectFile.create(projectData(),{catalog,validateBoard:board=>editor.validBoard(board)});
        state.catalog=catalog;state.kits=new Map(catalog.kits.map(k=>[k.id,k]));state.components=new Map(catalog.components.map(c=>[c.id,c]));
        editor.catalog=catalog;editor.kits=state.kits;window.ZZLabRegisteredBoards?.configure(catalog);
        editor._validationCache=null;editor._stackValidation=null;editor._stackLocalCache=null;editor._opticalSceneCache=null;editor._opticalHoleCache=null;
        window.ZZLabLocalLibrary.pin(snapshot);
        editor.invalidateOpticalTrace?.();editor.render();
        $('catalog-count').textContent=libraryCards().length+visibleBoards().length;
        if(catalog.updatedAt){const date=new Date(catalog.updatedAt);if(!Number.isNaN(date.valueOf()))$('catalog-updated').textContent=`更新于 ${date.toLocaleDateString('zh-CN')}`;}
        renderFilters();renderCards();renderPlan();renderExtras();
        state.revision++;state.preview=null;state.previewRevision=-1;updateButtons();persist();
        return{ok:true};
      }catch(error){
        state.catalog=previous;state.kits=previousKits;state.components=previousComponents;
        editor.catalog=previous;editor.kits=previousKits;window.ZZLabRegisteredBoards?.configure(previous);
        window.ZZLabLocalLibrary.pin(previousPin);editor._validationCache=null;editor._opticalSceneCache=null;
        editor.invalidateOpticalTrace?.();editor.render();
        return{ok:false,message:'新版库暂不适用于当前工程，继续使用原库：'+error.message};
      }
    }
  };
  initGuestAccessManager();loadCatalog();
})();
