'use strict';
window.ZZLAB_LOCAL=true;
const localFetch=window.fetch.bind(window);
let localSnapshot=null;
const localCatalogs=new Map();
window.fetch=(input,options={})=>{
  const url=new URL(typeof input==='string'?input:input.url,location.href);
  if(url.origin!==location.origin)return Promise.reject(new Error('本地编辑器不连接外部服务。'));
  const headers=new Headers(options.headers||{});headers.set('X-ZZLab-Local','1');
  if(localSnapshot)headers.set('X-ZZLab-Library',localSnapshot);
  return localFetch(input,{...options,headers});
};
window.ZZLabLocalLibrary={
  pin(snapshot){localSnapshot=snapshot;},
  get snapshot(){return localSnapshot;},
  catalog(snapshot){return localCatalogs.get(snapshot);},
  async resolve(project){
    const response=await fetch('/optics-kits/api/local/project-library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(project)});
    const catalog=await response.json();
    if(!response.ok)throw new Error(catalog.error?.message||catalog.message||'无法读取工程对应的元件库。');
    const snapshot=response.headers.get('X-ZZLab-Library');
    return{catalog:this.prepare(catalog,snapshot),snapshot};
  },
  imageUrl(path){const url=new URL(path,location.href);if(localSnapshot&&url.origin===location.origin)url.searchParams.set('library',localSnapshot);return url.pathname+url.search;},
  prepare(catalog,snapshot){
    // Pin images as well as compute requests: a waiting/old tab stays coherent.
    const visit=value=>{
      if(!value||typeof value!=='object')return;
      for(const [key,item] of Object.entries(value)){
        if(key==='topViewUrl'&&typeof item==='string'&&item){
          const url=new URL(item,location.href);
          if(url.origin===location.origin){url.searchParams.set('library',snapshot);value[key]=url.pathname+url.search;}
        }else visit(item);
      }
    };
    visit(catalog);localCatalogs.set(snapshot,catalog);return catalog;
  }
};
document.addEventListener('DOMContentLoaded',()=>{
  const button=document.getElementById('local-sync'),label=document.getElementById('local-sync-status');
  let polling=false,timer,pending=null,pointerDown=false;
  document.addEventListener('pointerdown',()=>{pointerDown=true;},true);
  document.addEventListener('pointerup',()=>{pointerDown=false;},true);
  document.addEventListener('pointercancel',()=>{pointerDown=false;},true);
  window.addEventListener('blur',()=>{pointerDown=false;});
  const status=async()=>{
    if(polling)return;polling=true;clearTimeout(timer);
    try{
      const response=await fetch('/optics-kits/api/local/status');if(!response.ok)throw new Error();
      const data=await response.json();button.disabled=data.sync.running;
      label.title=data.sync.detail||('与网页版共用正式发布库；每 '+data.autoSyncSeconds+' 秒自动检查');
      if(data.snapshot!==localSnapshot&&localSnapshot&&window.ZZLabLocalEditor){
        if(!pending||pending.snapshot!==data.snapshot){
          const result=await fetch('/optics-kits/api/catalog?snapshot='+encodeURIComponent(data.snapshot));
          if(!result.ok)throw new Error();
          pending={snapshot:result.headers.get('X-ZZLab-Library'),catalog:await result.json()};
        }
        if(pointerDown){label.textContent='新元件库已就绪，操作结束后自动载入';return;}
        const result=window.ZZLabLocalEditor.updateCatalog(pending.catalog,pending.snapshot);
        if(!result.ok){label.textContent=result.message;return;}
        pending=null;
      }
      label.textContent=data.sync.running?'正在同步网页版元件库…':data.sync.ok===false?
        data.sync.message:'与网页版同步 · '+data.catalogVersion;
    }catch{button.disabled=false;label.textContent='本地服务连接中断，现有画布保留；正在重连…';}
    finally{polling=false;timer=setTimeout(status,2000);}
  };
  button.addEventListener('click',async()=>{
    button.disabled=true;label.textContent='正在检查网页版元件库…';
    try{const response=await fetch('/optics-kits/api/local/sync',{method:'POST'});if(!response.ok)throw new Error();await status();}
    catch{button.disabled=false;label.textContent='更新未完成，现有缓存和工程保留。';}
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)status();});
  window.addEventListener('focus',status);
  status();
});
