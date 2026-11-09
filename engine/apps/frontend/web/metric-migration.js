/* Explicit, versioned replacement of the retired support-height series.
 * Positions, optical settings and commercial optic diameters are never scaled. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ZZLabMetricMigration=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const CAPABILITY='zzlab-metric-supports-v1',REVISION='metric-62p5-20261006',own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
  function migrate(source,catalog){
    const rule=catalog?.universalPostSeries?.metricMigration;
    if(rule?.revision!==REVISION||!source||typeof source!=='object'||Array.isArray(source))return{project:source,changed:false,changes:[]};
    if(own(source,'requires')&&(!Array.isArray(source.requires)||source.requires.some(x=>typeof x!=='string')))return{project:source,changed:false,changes:[]};
    const project=JSON.parse(JSON.stringify(source)),changes=[],layout=project.layout;
    if(!layout||typeof layout!=='object')return{project:source,changed:false,changes};
    const legacy=!Array.isArray(project.requires)||!project.requires.includes(CAPABILITY);
    const map=rule.componentMap||{},kits=new Map((catalog.kits||[]).map(k=>[k.id,k]));
    for(const item of Array.isArray(layout.instances)?layout.instances:[]){
      if(!item||typeof item!=='object')continue;
      const refs=new Set((kits.get(item.kitId)?.components||[]).map(r=>r.componentId)),selection=item.universalPostSelection;
      let oldSeries=rule.legacyKitIds?.includes(item.kitId)&&legacy;
      if(selection&&typeof selection==='object'&&!Array.isArray(selection)){
        const next=Object.create(null);for(const [key,value]of Object.entries(selection)){
          const targetKey=own(map,key)&&refs.has(map[key])?map[key]:key,targetValue=typeof value==='string'&&own(map,value)?map[value]:value;
          // Keep malformed or conflicting input intact so the normal validator rejects it.
          if(own(next,targetKey))return{project:source,changed:false,changes:[]};
          next[targetKey]=targetValue;
          if(key!==targetKey||value!==targetValue){oldSeries=true;changes.push({instanceId:item.id,field:'universalPostSelection',from:[key,value],to:[targetKey,targetValue]});}
        }item.universalPostSelection=next;
      }
      if(oldSeries&&!item.boardId&&typeof item.elevationMm==='number'&&item.elevationMm>0){
        const steps=item.elevationMm/12.7;
        if(Math.abs(steps-Math.round(steps))<1e-7){const before=item.elevationMm;item.elevationMm=Math.round(steps)*12.5;changes.push({instanceId:item.id,field:'elevationMm',from:before,to:item.elevationMm});}
      }
    }
    // Only legacy default parameter plates; registered source plates retain their CAD thickness.
    if(legacy)for(const entry of [{id:'base',board:layout.board},...(Array.isArray(layout.subBoards)?layout.subBoards:[])]){
      const b=entry?.board;if(b&&!b.registeredBoardId&&b.thicknessMm===12.7){b.thicknessMm=12.5;changes.push({boardId:entry.id,field:'thicknessMm',from:12.7,to:12.5});}
    }
    if(legacy){project.requires=[...(Array.isArray(project.requires)?project.requires:[]),CAPABILITY];project.catalogVersion=catalog.version;changes.push({field:'catalogVersion',from:source.catalogVersion??null,to:catalog.version});}
    return{project,changed:changes.length>0,changes};
  }
  return{REVISION,CAPABILITY,migrate};
});
