/* The server owns guest policy and authorization; this dialog edits an explicit revision. */
(() => {
  'use strict';
  const put=(node,value)=>{const text=String(value??'');if(node.textContent!==text)node.textContent=text};
  function settingsValue(raw){if(!raw||typeof raw.guestAccessEnabled!=='boolean'||('guestManufacturingDownloadsEnabled'in raw&&typeof raw.guestManufacturingDownloadsEnabled!=='boolean')||!Number.isSafeInteger(raw.revision)||raw.revision<0||!(raw.updatedAt===null||typeof raw.updatedAt==='string'))throw new Error('设置读取不完整，请重新载入。');return{guestAccessEnabled:raw.guestAccessEnabled,guestManufacturingDownloadsEnabled:raw.guestManufacturingDownloadsEnabled!==false,revision:raw.revision,updatedAt:raw.updatedAt}}
  function mount({getContext,load,save,onSaved,notify}={}){
    const ids=['guest-access-open','guest-access-dialog','guest-access-form','guest-access-close','guest-access-cancel','guest-access-fields','guest-access-enabled','guest-access-manufacturing-downloads-enabled','guest-access-updated','guest-access-status','guest-access-error','guest-access-reload','guest-access-save'];
    const nodes=Object.fromEntries(ids.map(id=>[id,document.getElementById(id)]));if(ids.some(id=>!nodes[id]))throw new Error('访问管理界面尚未准备好。');const n=id=>nodes[id];
    const state={settings:null,loading:false,saving:false,reloadRequired:false,inflightSave:null,request:0,destroyed:false},listeners=[];
    const admin=()=>getContext?.()?.role==='admin';
    function listen(id,event,fn){n(id).addEventListener(event,fn);listeners.push(()=>n(id).removeEventListener(event,fn))}
    function error(message=''){put(n('guest-access-error'),message);n('guest-access-error').hidden=!message}
    const changed=()=>Boolean(state.settings&&(n('guest-access-enabled').checked!==state.settings.guestAccessEnabled||n('guest-access-manufacturing-downloads-enabled').checked!==state.settings.guestManufacturingDownloadsEnabled));
    const summary=settings=>`游客访问${settings.guestAccessEnabled?'已开启':'已关闭'}；游客图纸和三维模型下载${settings.guestManufacturingDownloadsEnabled?'允许':'不允许'}。`;
    function controls(){const blocked=!admin()||state.loading||state.saving||state.reloadRequired||!state.settings;n('guest-access-fields').disabled=blocked;n('guest-access-save').disabled=blocked||!changed();n('guest-access-reload').disabled=state.loading||state.saving;put(n('guest-access-save'),state.saving?'正在保存…':'保存设置')}
    function applySettings(settings){state.settings=settings;state.reloadRequired=false;n('guest-access-enabled').checked=settings.guestAccessEnabled;n('guest-access-manufacturing-downloads-enabled').checked=settings.guestManufacturingDownloadsEnabled;n('guest-access-fields').hidden=false;put(n('guest-access-status'),'当前设置：'+summary(settings));const date=settings.updatedAt?new Date(settings.updatedAt):null;put(n('guest-access-updated'),date&&!Number.isNaN(date.valueOf())?`上次更新：${date.toLocaleString('zh-CN')}`:settings.revision===0&&!settings.guestAccessEnabled?'尚未修改；游客访问默认关闭。':'尚无更新时间记录。')}
    function close(){state.request++;state.loading=false;state.saving=false;if(n('guest-access-dialog').open)n('guest-access-dialog').close();if(admin())n('guest-access-open').focus()}
    function updateContext(){if(state.destroyed)return;const allowed=admin();n('guest-access-open').hidden=!allowed;if(!allowed){if(n('guest-access-dialog').open)close();state.settings=null;n('guest-access-fields').hidden=true;}controls()}
    async function reload(){
      if(state.destroyed||!admin())return;const request=++state.request;state.loading=true;state.reloadRequired=false;state.settings=null;error();n('guest-access-fields').hidden=true;n('guest-access-reload').hidden=true;put(n('guest-access-status'),state.inflightSave?'正在等待上一笔保存结果，随后重新载入…':'正在读取设置…');controls();
      try{if(state.inflightSave){try{await state.inflightSave}catch{}if(state.destroyed||request!==state.request||!admin())return}const result=await load();if(state.destroyed||request!==state.request||!admin())return;applySettings(settingsValue(result));}
      catch(reason){if(state.destroyed||request!==state.request)return;error(reason?.message||'读取设置失败，请重试。');put(n('guest-access-status'),'尚未读取到当前设置。');n('guest-access-reload').hidden=false;}
      finally{if(!state.destroyed&&request===state.request){state.loading=false;controls()}}
    }
    async function submit(event){
      event.preventDefault();if(state.destroyed||!admin()||state.loading||state.saving||state.reloadRequired||!state.settings)return;
      if(!changed())return;const request=++state.request,payload={guestAccessEnabled:n('guest-access-enabled').checked,guestManufacturingDownloadsEnabled:n('guest-access-manufacturing-downloads-enabled').checked,revision:state.settings.revision};state.saving=true;error();put(n('guest-access-status'),'正在保存设置…');controls();const write=Promise.resolve().then(()=>save(payload));state.inflightSave=write;
      try{
        const result=await write;if(state.destroyed||request!==state.request||!admin())return;const stored=settingsValue(result);applySettings(stored);n('guest-access-reload').hidden=true;
        const warning=result.backup?.status==='warning',message=`设置已保存：${summary(stored)}${warning?' '+(result.backup.message||'备份暂未完成，请稍后联系管理员。'):''}`;put(n('guest-access-status'),message);notify?.(message,warning);
        // A follow-up identity refresh must never turn a committed policy into an apparent failure.
        try{Promise.resolve(onSaved?.(stored)).catch(()=>{})}catch{}
      }catch(reason){
        if(state.destroyed||request!==state.request)return;const conflict=reason?.status===409||reason?.code==='access_settings_conflict',definiteRejection=Number.isInteger(reason?.status)&&reason.status>=400&&reason.status<500,uncertain=!conflict&&!definiteRejection;
        state.reloadRequired=conflict||uncertain;const message=conflict?'设置已被其他管理员更新，本次没有保存。请重新载入后再修改。':uncertain?'暂时无法确认是否保存，请重新载入设置核对。':reason?.message||'服务器未接受本次修改，请检查后重试。';
        error(message);put(n('guest-access-status'),conflict?'请重新载入最新设置。':uncertain?'保存结果尚未确认。':'本次修改尚未保存。');n('guest-access-reload').hidden=!state.reloadRequired;
      }finally{if(state.inflightSave===write)state.inflightSave=null;if(!state.destroyed&&request===state.request){state.saving=false;controls()}}
    }
    listen('guest-access-open','click',()=>{if(!admin())return;n('guest-access-dialog').showModal();void reload()});listen('guest-access-close','click',close);listen('guest-access-cancel','click',close);listen('guest-access-dialog','cancel',event=>{event.preventDefault();close()});listen('guest-access-form','submit',submit);listen('guest-access-reload','click',reload);for(const id of ['guest-access-enabled','guest-access-manufacturing-downloads-enabled'])listen(id,'change',()=>{error();controls();if(state.settings)put(n('guest-access-status'),changed()?'设置已调整，点击“保存设置”后生效。':'当前设置：'+summary(state.settings))});
    updateContext();return{updateContext,reload,destroy(){state.destroyed=true;state.request++;listeners.forEach(remove=>remove());if(n('guest-access-dialog').open)n('guest-access-dialog').close()}};
  }
  window.ZZLabGuestAccess={mount};
})();
