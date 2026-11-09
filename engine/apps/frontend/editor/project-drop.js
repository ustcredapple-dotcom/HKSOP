/* File drops share the same transactional importer as the file picker. */
(function(root){
  'use strict';
  function bind({document,window,overlay,openFile,notify}){
    let depth=0;
    const hasFiles=e=>Array.from(e.dataTransfer?.types||[]).includes('Files')||Array.from(e.dataTransfer?.items||[]).some(item=>item.kind==='file');
    const reset=()=>{depth=0;overlay.hidden=true;};
    const consume=e=>{e.preventDefault();e.stopPropagation();};
    document.addEventListener('dragenter',e=>{
      if(!hasFiles(e))return;
      consume(e);depth++;overlay.hidden=false;
    },true);
    document.addEventListener('dragover',e=>{
      if(!hasFiles(e))return;
      consume(e);e.dataTransfer.dropEffect='copy';overlay.hidden=false;
    },true);
    document.addEventListener('dragleave',e=>{
      if(!depth)return;
      depth=Math.max(0,depth-1);if(!depth||!e.relatedTarget)reset();
    },true);
    document.addEventListener('drop',e=>{
      reset();if(!hasFiles(e)&&!e.dataTransfer?.files?.length)return;
      // Prevent the browser from navigating to the dropped file, including
      // invalid files, before the canvas's ordinary kit-drop handlers run.
      consume(e);
      const files=Array.from(e.dataTransfer.files||[]);
      if(files.length!==1)return notify('请每次拖入一个 JSON 工程文件；当前工程未改变。',true);
      if(!/\.json$/i.test(files[0].name))return notify('请拖入 .json 或 .zzoptics.json 工程文件；当前工程未改变。',true);
      void openFile(files[0]);
    },true);
    window.addEventListener('dragend',reset);
    window.addEventListener('blur',reset);
    window.addEventListener('pagehide',reset);
    document.addEventListener('keydown',e=>{if(e.key==='Escape')reset();});
  }
  root.ZZLabProjectDrop={bind};
  if(typeof module==='object'&&module.exports)module.exports={bind};
})(typeof globalThis!=='undefined'?globalThis:this);
