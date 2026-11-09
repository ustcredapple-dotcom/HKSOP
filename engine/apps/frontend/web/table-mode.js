/* The table is a working area, not a manufactured root breadboard. */
(function(root){
  'use strict';
  if(!root.BreadboardEditor)return;
  const P=root.BreadboardEditor.prototype,$=id=>root.document.getElementById(id),escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  P.setBaseMode=function(mode){
    if(typeof mode==='string'&&mode.startsWith('registered:'))return this.setRegisteredMainBoard(mode.slice('registered:'.length));
    if(!['breadboard','table'].includes(mode))throw new Error('请选择大面包板或桌子模式。');
    if(this.boardFormDirty||this.manualMounting){this.syncBaseMode();this.notify('请先完成当前参数或选孔修改。',true);return false}
    const main=this.snapshot().board;
    if(main.registeredBoardId){
      // Choosing a custom board or table explicitly leaves the fixed source
      // shape. Keep the workspace size, but do not copy source fixing-hole IDs
      // into the new rectangular board's grid.
      const board={widthMm:main.widthMm,heightMm:main.heightMm,thicknessMm:12.5,pitchMm:25,edgeOffsetMm:12.5,holeType:'M6_through',mountingHoles:[]};
      const changed=this.setMainBoard(board,mode);this.notify(mode==='table'?'已改为桌面参考区域，不生成底板加工资料。':'已改为自定义矩形面包板，可在参数中调整尺寸和孔距。');return changed;
    }
    if((this.baseMode||'breadboard')===mode)return false;
    const before=this.historySnapshot();this.baseMode=mode;this.commit(before);
    this.notify(mode==='table'?'已切换到桌子／无大板：底层只作摆放参考，小板和器件仍计入清单。':'已切换到大面包板：底板将计入生产清单。');
    return true;
  };
  P.syncBaseMode=function(){
    const table=this.baseMode==='table',input=$('base-mode'),note=$('base-mode-note'),main=this.snapshot().board,record=root.ZZLabRegisteredBoards?.recordFor(main,this.catalog);
    if(input){
      const boards=(this.catalog.registeredBoards||[]).filter(b=>!b.stageOnly&&(b.libraryVisibility!=='compatibility-only'||this.snapshot().board.registeredBoardId===b.id)&&!(this.catalog.stageModules||[]).some(m=>m.runtime?.topBoardId===b.id)),key=JSON.stringify(boards.map(b=>[b.id,b.name]));
      if(input.dataset.boardChoices!==key){input.dataset.boardChoices=key;input.innerHTML='<option value="breadboard">自定义面包板</option><option value="table">桌子／无大板（仅作参考）</option>'+(boards.length?'<optgroup label="库内面包板">'+boards.map(b=>`<option value="registered:${escape(b.id)}">${escape(b.name)}</option>`).join('')+'</optgroup>':'');}
      input.value=table?'table':record?'registered:'+record.id:'breadboard';
    }
    if(note)note.textContent=table?'没有实体大板。网格仅作摆放参考；桌面不生成 STEP、图纸或生产项，小板与器件照常计入。':record?`${record.name} 直接作为主面包板；采用原板外形、孔位和加工资料，下面不再增加底板。`:'主面包板参与安装孔对齐，并在加入购物车时计入生产清单和加工资料。';
    if($('base-size-settings'))$('base-size-settings').textContent=table?'设置桌面尺寸':record?'查看主板参数':'设置主板尺寸';
    this.svg?.classList.toggle('table-reference',table);
    const reference=table&&!this.activeBoardId;
    $('board-form')?.classList.toggle('table-root-settings',reference);
    if($('mounting-settings'))$('mounting-settings').hidden=reference;
    if($('stack-create'))$('stack-create').hidden=table||Boolean(this.stacked);
    if(reference){
      const label=`${this.board.widthMm} × ${this.board.heightMm} mm · 桌面参考区域 · 网格 ${this.board.pitchMm} mm`;
      if($('board-settings-summary'))$('board-settings-summary').textContent=label;
      if($('layout-board-label'))$('layout-board-label').textContent=label;
    }
  };
  const oldValidation=P.validation;
  P.validation=function(){
    const result=oldValidation.call(this);if(this.baseMode!=='table')return result;
    if(this._tableValidation?.source===result)return this._tableValidation.value;
    const rootOnly=new Set(['mounting_mismatch','mounting_unconfirmed','off_grid','board_mounting_invalid','mounting_hole_obstructed']);
    const issues=result.issues.filter(issue=>!(!issue.boardId&&rootOnly.has(issue.code)));
    const value={...result,issues,valid:issues.length===0};this._tableValidation={source:result,value};return value;
  };
  const oldRender=P.render;P.render=function(...args){const result=oldRender.apply(this,args);this.syncBaseMode();return result};
  const oldBind=P.bind;P.bind=function(...args){oldBind.apply(this,args);
    $('base-mode')?.addEventListener('change',e=>{try{this.setBaseMode(e.target.value)}catch(error){this.syncBaseMode();this.notify(error.message,true)}});
    $('base-size-settings')?.addEventListener('click',()=>{
      if(this.switchBoard&&!this.switchBoard(null))return;
      const settings=$('board-settings');if(settings)settings.open=true;
      $('board-width')?.focus({preventScroll:true});
    });
  };
})(typeof window!=='undefined'?window:globalThis);
