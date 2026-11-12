/* Catalog-backed physical boards. Project files contain references, never CAD geometry. */
(function(root){
  'use strict';
  const EPS=1e-5,copy=x=>JSON.parse(JSON.stringify(x)),key=h=>h.holeId||h.id||`${h.columnIndex},${h.rowIndex}`;
  let activeCatalog={registeredBoards:[]};
  const holeIndexes=new WeakMap();
  function holeIndex(record){if(!holeIndexes.has(record)){const cells=new Map();for(const h of record.holesMm){const k=`${Math.round(h.xMm*1e5)},${Math.round(h.yMm*1e5)}`;if(!cells.has(k))cells.set(k,[]);cells.get(k).push(h)}holeIndexes.set(record,cells)}return holeIndexes.get(record)}
  const configure=catalog=>{activeCatalog=catalog||{registeredBoards:[]}};
  function recordFor(board,catalog=activeCatalog){if(!board?.registeredBoardId)return null;return(catalog?.registeredBoards||[]).find(r=>r.id===board.registeredBoardId&&String(r.revision)===String(board.registeredBoardRevision))||null}
  // Stage top screws may be fastened before installing the optical components.
  const allowsCoveredMounting=(board,catalog=activeCatalog)=>recordFor(board,catalog)?.stageOnly===true;

  const customMounting=r=>r?.customMountingHoles===true;
  const mountingCandidates=r=>customMounting(r)?r.holesMm.filter(h=>h.type==='thread'&&h.thread==='M6x1.0').map(h=>h.id):(r.mountingHoleIds||[]);
  function customMountingError(r,id,chosen=[]){
    if(!customMounting(r))return '';
    const h=r.holesMm.find(h=>h.id===id);if(!h||!mountingCandidates(r).includes(id))return '请选择已登记的M6螺纹孔。';
    const radius=5.5,web=2,selected=new Set(chosen.map(v=>typeof v==='string'?v:v.holeId));
    if(r.thicknessMm<8.5)return '板厚不足以加工该沉孔。';
    const distance=(p,a,b)=>{const dx=b.xMm-a.xMm,dy=b.yMm-a.yMm,t=Math.max(0,Math.min(1,((p.xMm-a.xMm)*dx+(p.yMm-a.yMm)*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p.xMm-a.xMm-t*dx,p.yMm-a.yMm-t*dy)};
    for(const ring of [r.outlineMm,...(r.cutoutsMm||[])])for(let i=0;i<ring.length;i++)if(distance(h,ring[i],ring[(i+1)%ring.length])<radius+web-EPS)return '沉孔距真实板边不足，需保留2 mm边壁。';
    for(const p of r.holesMm){if(p.id===id)continue;const isSelected=selected.has(p.id);if(Math.hypot(h.xMm-p.xMm,h.yMm-p.yMm)<radius+(isSelected?radius:p.diameterMm/2)+(isSelected?0:web)-EPS)return '沉孔与邻孔间距不足。';}
    return '';
  }
  function normalizeBoard(source,catalog=activeCatalog){
    const r=recordFor(source,catalog);if(!r)throw new Error('登记面包板或其版本不在当前目录中，请更新目录后重试。');
    for(const field of ['widthMm','heightMm','thicknessMm','pitchMm','edgeOffsetMm'])if(source[field]!==undefined&&(!Number.isFinite(Number(source[field]))||Math.abs(Number(source[field])-r[field])>EPS))throw new Error('登记面包板的尺寸和原孔位固定，不能改为参数板。');
    const mounting=source.mountingHoles===undefined?(r.mountingHoleIds||[]).map(holeId=>({holeId})):source.mountingHoles;
    if(!Array.isArray(mounting)||mounting.length>128||mounting.some(h=>!h||Object.keys(h).some(k=>k!=='holeId')||!mountingCandidates(r).includes(h.holeId))||new Set(mounting.map(key)).size!==mounting.length)throw new Error('固定孔必须选择源板已登记的孔位，不能添加新的孔。');
    for(const h of mounting){const error=customMountingError(r,h.holeId,mounting);if(error)throw new Error(error);}
    return{...(root.ZZLabFixedBoardOptics?.normalizeState(source,catalog)||{}),registeredBoardId:r.id,registeredBoardRevision:r.revision,widthMm:r.widthMm,heightMm:r.heightMm,thicknessMm:r.thicknessMm,pitchMm:r.pitchMm,edgeOffsetMm:r.edgeOffsetMm,holeType:'M6_through',mountingHoles:mounting.map(h=>({holeId:h.holeId}))};
  }
  // Trusted catalog presets materialize only on insertion, never on save/open.
  function defaultContents(record,catalog,boardId=null){
    const rows=record.defaultContents||[],kits=new Map((catalog.kits||[]).map(k=>[k.id,k]));
    if(rows.some(v=>kits.get(v.kitId)?.lifecycle?.state==='historical'||kits.get(v.kitId)?.lifecycle?.canCreate===false))throw new Error('预装器件含历史版本，不能用于新增。');
    if(!Array.isArray(rows)||rows.length>64)throw new Error('板上预装器件数量无效。');
    return rows.map(v=>{
      if(!v||Object.keys(v).some(k=>!['kitId','xMm','yMm','rotationDeg','optics'].includes(k))||!kits.has(v.kitId)||kits.get(v.kitId).layout?.placementAllowed!==true||!Number.isFinite(v.xMm)||!Number.isFinite(v.yMm)||Math.abs(v.xMm)>6000||Math.abs(v.yMm)>6000||![0,90,180,270].includes(v.rotationDeg))throw new Error('板上预装器件的型号或位置无效。');
      return{...copy(v),id:'instance-'+root.crypto.randomUUID(),...(boardId?{boardId}:{})};
    });
  }
  const rect=b=>[{xMm:0,yMm:0},{xMm:b.widthMm,yMm:0},{xMm:b.widthMm,yMm:b.heightMm},{xMm:0,yMm:b.heightMm}];
  const outline=(board,catalog)=>{const r=recordFor(board,catalog);if(board?.registeredBoardId&&!r)throw new Error('登记面包板版本不存在。');return r?.outlineMm||rect(board)};
  const cutouts=(board,catalog)=>recordFor(board,catalog)?.cutoutsMm||[];
  function segmentDistance(p,a,b){const x=b.xMm-a.xMm,y=b.yMm-a.yMm,l=x*x+y*y,t=l?Math.max(0,Math.min(1,((p.xMm-a.xMm)*x+(p.yMm-a.yMm)*y)/l)):0;return Math.hypot(p.xMm-a.xMm-t*x,p.yMm-a.yMm-t*y)}
  function inPolygon(p,poly,boundary=true){let inside=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[j],b=poly[i];if(segmentDistance(p,a,b)<=EPS)return boundary;if((a.yMm>p.yMm)!==(b.yMm>p.yMm)&&p.xMm<(b.xMm-a.xMm)*(p.yMm-a.yMm)/(b.yMm-a.yMm)+a.xMm)inside=!inside}return inside}
  function contains(board,p,catalog){return inPolygon(p,outline(board,catalog))&&!cutouts(board,catalog).some(poly=>inPolygon(p,poly,false))}
  const cross=(a,b)=>a.xMm*b.yMm-a.yMm*b.xMm,minus=(a,b)=>({xMm:a.xMm-b.xMm,yMm:a.yMm-b.yMm});
  function intersections(a,b,c,d){const v=minus(b,a),w=minus(d,c),den=cross(v,w),q=minus(c,a);if(Math.abs(den)<EPS)return[];const t=cross(q,w)/den,u=cross(q,v)/den;return t>=-EPS&&t<=1+EPS&&u>=-EPS&&u<=1+EPS?[Math.max(0,Math.min(1,t))]:[]}
  const edges=polys=>polys.flatMap(poly=>poly.map((p,i)=>[p,poly[(i+1)%poly.length]]));
  function containsPolygon(board,poly,catalog){
    if(!poly.every(p=>contains(board,p,catalog)))return false;const boundaries=edges([outline(board,catalog),...cutouts(board,catalog)]);
    for(const[a,b]of edges([poly])){const ts=[0,1,...boundaries.flatMap(([c,d])=>intersections(a,b,c,d))].sort((x,y)=>x-y);for(let j=1;j<ts.length;j++){const t=(ts[j-1]+ts[j])/2;if(!contains(board,{xMm:a.xMm+(b.xMm-a.xMm)*t,yMm:a.yMm+(b.yMm-a.yMm)*t},catalog))return false;}}
    return!cutouts(board,catalog).some(hole=>hole.some(p=>inPolygon(p,poly,false)));
  }
  function region(board,pose={xMm:0,yMm:0,rotationDeg:0},catalog){const a=(pose.rotationDeg||0)*Math.PI/180,c=Math.round(Math.cos(a)),s=Math.round(Math.sin(a)),transform=p=>({xMm:pose.xMm+c*p.xMm-s*p.yMm,yMm:pose.yMm+s*p.xMm+c*p.yMm});return{outer:outline(board,catalog).map(transform),cuts:cutouts(board,catalog).map(poly=>poly.map(transform))}}
  function overlaps(a,b){
    const bounds=poly=>({xMin:Math.min(...poly.map(p=>p.xMm)),xMax:Math.max(...poly.map(p=>p.xMm)),yMin:Math.min(...poly.map(p=>p.yMm)),yMax:Math.max(...poly.map(p=>p.yMm))}),A=bounds(a.outer),B=bounds(b.outer);if(Math.min(A.xMax,B.xMax)-Math.max(A.xMin,B.xMin)<=EPS||Math.min(A.yMax,B.yMax)-Math.max(A.yMin,B.yMin)<=EPS)return false;
    const inside=(r,p)=>inPolygon(p,r.outer,false)&&!r.cuts.some(c=>inPolygon(p,c,true)),boundariesA=edges([a.outer,...a.cuts]),boundariesB=edges([b.outer,...b.cuts]);
    // Subdivide every boundary at crossings. Test both sides of each resulting
    // segment to distinguish shared edges, open notches, and real overlap area.
    for(const [first,other]of [[boundariesA,boundariesB],[boundariesB,boundariesA]])for(const[p,q]of first){const ts=[0,1,...other.flatMap(([r,s])=>intersections(p,q,r,s))].sort((x,y)=>x-y),dx=q.xMm-p.xMm,dy=q.yMm-p.yMm,len=Math.hypot(dx,dy);if(!len)continue;for(let j=1;j<ts.length;j++){if(ts[j]-ts[j-1]<EPS)continue;const t=(ts[j-1]+ts[j])/2,mid={xMm:p.xMm+dx*t,yMm:p.yMm+dy*t};for(const sign of [-1,1]){const test={xMm:mid.xMm-sign*dy/len*EPS*4,yMm:mid.yMm+sign*dx/len*EPS*4};if(inside(a,test)&&inside(b,test))return true}}}return false;
  }
  function holes(board,catalog){const r=recordFor(board,catalog);if(board?.registeredBoardId&&!r)throw new Error('登记面包板版本不存在。');if(r)return r.holesMm.map(h=>({...h,holeId:h.id}));const out=[],p=board.pitchMm,o=board.edgeOffsetMm;for(let row=0;row<=Math.floor((board.heightMm-2*o)/p+EPS);row++)for(let column=0;column<=Math.floor((board.widthMm-2*o)/p+EPS);column++)out.push({columnIndex:column,rowIndex:row,xMm:o+column*p,yMm:o+row*p,type:board.holeType==='M6_through'?'thread':'clearance',thread:board.holeType==='M6_through'?'M6x1.0':null,diameterMm:board.holeType==='M6_through'?6:board.holeDiameterMm||6});return out}
  function mountingPositions(board,catalog){const r=recordFor(board,catalog);if(board?.registeredBoardId&&!r)throw new Error('登记面包板版本不存在。');return(board.mountingHoles||[]).map((h,i)=>{const p=r?r.holesMm.find(p=>p.id===h.holeId):{xMm:board.edgeOffsetMm+h.columnIndex*board.pitchMm,yMm:board.edgeOffsetMm+h.rowIndex*board.pitchMm};return{...h,...p,...(customMounting(r)?{type:'counterbore',thread:undefined,tapDrillDiameterMm:undefined,diameterMm:6.6,counterboreDiameterMm:11,counterboreDepthMm:6.5}:{}),id:'H'+(i+1),...(r?{holeId:h.holeId}:{}),xMm:p?.xMm??NaN,yMm:p?.yMm??NaN}})}
  function isHole(board,p,catalog,{threadOnly=false,excludeMounting=false}={}){const r=recordFor(board,catalog);if(board?.registeredBoardId&&!r)throw new Error('登记面包板版本不存在。');if(!r){const ok=[[p.xMm,board.widthMm],[p.yMm,board.heightMm]].every(([v,size])=>v>=board.edgeOffsetMm-EPS&&v<=size-board.edgeOffsetMm+EPS&&Math.abs((v-board.edgeOffsetMm)/board.pitchMm-Math.round((v-board.edgeOffsetMm)/board.pitchMm))<=EPS);return ok&&(!threadOnly||board.holeType==='M6_through')&&(!excludeMounting||!mountingPositions(board,catalog).some(h=>Math.hypot(h.xMm-p.xMm,h.yMm-p.yMm)<EPS))}const index=holeIndex(r),x=Math.round(p.xMm*1e5),y=Math.round(p.yMm*1e5);for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)if((index.get(`${x+dx},${y+dy}`)||[]).some(h=>(!threadOnly||h.type==='thread')&&Math.hypot(h.xMm-p.xMm,h.yMm-p.yMm)<EPS&&(!excludeMounting||!(board.mountingHoles||[]).some(v=>v.holeId===h.id))))return true;return false}
  function nearest(board,p,catalog,{mountingOnly=false,threadOnly=false}={}){const r=recordFor(board,catalog);return holes(board,catalog).filter(h=>(!threadOnly||h.type==='thread')&&(!mountingOnly||!r||mountingCandidates(r).includes(h.holeId))).reduce((best,h)=>{const d=(h.xMm-p.xMm)**2+(h.yMm-p.yMm)**2;return!best||d<best.distance?{...h,distance:d}:best},null)}
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function path(board,catalog){return[outline(board,catalog),...cutouts(board,catalog)].map(poly=>'M '+poly.map(p=>`${p.xMm} ${board.heightMm-p.yMm}`).join(' L ')+' Z').join(' ')}
  // Reference overlays are paint only: never added to board regions, holes or hit tests.
  function referenceMarkup(board,catalog){
    const refs=recordFor(board,catalog)?.referenceAnnotations;
    if(refs?.displayOnly!==true)return'';
    const y=v=>board.heightMm-v,point=p=>`${p.xMm},${y(p.yMm)}`;
    const colors={leg:'#8b5b35',glass:'#128795',iontrap:'#934d9e',center:'#506d61',coil:'#b78042','coil-section':'#c36d22','obstruction-section':'#b65b24'};
    const label=(p,text,color,size=22,anchor='start')=>`<text x="${p.xMm}" y="${y(p.yMm)}" fill="${color}" stroke="#fbfcf9" stroke-width="4" paint-order="stroke" font-family="Arial, sans-serif" font-size="${size}" font-weight="600" text-anchor="${anchor}">${escape(text)}</text>`;
    const projections=(refs.projections||[]).map(p=>{
      const color=colors[p.kind]||colors.center,ring=p.outlineMm||[];
      if(ring.length<3)return'';
      const coil=p.kind==='coil'||p.kind==='coil-section'||p.kind==='obstruction-section';
      if(coil){
        const section=p.kind==='coil-section'||p.kind==='obstruction-section',d=[ring,...(p.cutoutsMm||[])].map(r=>'M '+r.map(point).join(' L ')+' Z').join(' ');
        return`<g data-reference-kind="${escape(p.kind)}" data-reference-id="${escape(p.id)}"><title>${escape(p.description||p.label)} · 仅位置参考，不参与干涉检测</title><path d="${d}" fill="${section?color:'none'}" fill-opacity=".30" fill-rule="evenodd" stroke="${color}" stroke-width="${section?'2.2':'1.3'}" stroke-dasharray="${section?'none':'8 6'}"/>${p.labelPointMm?label(p.labelPointMm,p.label,color,p.kind==='obstruction-section'?16:20,p.kind==='obstruction-section'?'middle':'start'):''}</g>`;
      }
      return`<g data-reference-kind="${escape(p.kind)}" data-reference-id="${escape(p.id)}"><title>${escape(p.description||p.label)} · 仅位置参考，不参与干涉检测</title><polygon points="${ring.map(point).join(' ')}" fill="${color}" fill-opacity="${p.kind==='leg'?'.12':'.08'}" stroke="${color}" stroke-width="${p.kind==='leg'?'1.6':'2.2'}" stroke-dasharray="${p.kind==='leg'?'5 4':'9 5'}"/>${p.labelPointMm?label(p.labelPointMm,p.label,color,p.kind==='leg'?18:22,p.kind==='leg'?'middle':'start'):''}</g>`;
    }).join('');
    const centers=(refs.centers||[]).map(p=>{
      const color=colors[p.kind]||colors.center,cy=y(p.yMm),leader=p.labelPointMm?`<path d="M ${p.xMm+8} ${cy+5} L ${p.labelPointMm.xMm-8} ${y(p.labelPointMm.yMm)-6}" fill="none" stroke="${color}" stroke-width="1"/>`:'';
      return`<g data-reference-center="${escape(p.id)}"><title>${escape(p.description||p.label)} (${p.xMm}, ${p.yMm}) mm · 仅位置参考</title><path d="M ${p.xMm-16} ${cy} H ${p.xMm+16} M ${p.xMm} ${cy-16} V ${cy+16}" fill="none" stroke="${color}" stroke-width="1.7"/><circle cx="${p.xMm}" cy="${cy}" r="7" fill="#fbfcf9" fill-opacity=".85" stroke="${color}" stroke-width="1.7"/>${leader}${label(p.labelPointMm||{xMm:p.xMm+23,yMm:p.yMm+18},p.label,color)}</g>`;
    }).join('');
    return`<g class="board-reference-annotations" pointer-events="none" aria-label="位置参考标注，不参与干涉检测">${projections}${centers}${refs.sectionReferenceNote?label({xMm:board.widthMm/2,yMm:54},refs.sectionReferenceNote,colors.coil,16,'middle'):''}${label({xMm:board.widthMm/2,yMm:28},'位置参考 · 不参与干涉检测',colors.center,18,'middle')}</g>`;
  }

  function markup(board,catalog,{outlineOnly=false}={}){const r=recordFor(board,catalog);if(!r)return'';const edge=`<path class="${outlineOnly?'stack-outline':'breadboard registered-board-surface'}" d="${path(board,catalog)}" fill-rule="evenodd"${outlineOnly?' fill="none"':''}/>`;if(outlineOnly)return edge;return edge+`<g class="registered-board-holes" pointer-events="none">${r.holesMm.map(h=>`<circle data-registered-hole="${escape(h.id)}" cx="${h.xMm}" cy="${board.heightMm-h.yMm}" r="${Math.min(2.2,h.diameterMm/2)}" class="registered-hole-${escape(h.type)}"><title>${escape(h.id)} · ${escape(h.thread||h.type)}</title></circle>${h.type==='counterbore'?`<circle cx="${h.xMm}" cy="${board.heightMm-h.yMm}" r="${(h.counterboreDiameterMm||h.diameterMm)/2}" fill="none" stroke="#807596" stroke-width=".5"/>`:''}`).join('')}</g>`+referenceMarkup(board,catalog)+(root.ZZLabBoardAccessories?.markup(board,catalog)||'')}
  function snapDelta(board,instances,offsetsFor,desired,catalog,accept=null){
    const selected=new Set((board.mountingHoles||[]).map(key)),targets=holes(board,catalog).filter(h=>h.type==='thread'&&!selected.has(key(h))),rows=instances.map(i=>({i,offsets:offsetsFor(i)}));let best=null,candidates=[];
    for(const row of rows.slice(0,1))for(const offset of row.offsets)for(const h of targets){const dx=h.xMm-row.i.xMm-offset.xMm,dy=h.yMm-row.i.yMm-offset.yMm,d=(dx-desired.xMm)**2+(dy-desired.yMm)**2;candidates.push({xMm:dx,yMm:dy,d})}
    candidates.sort((a,b)=>a.d-b.d);const seen=new Set();for(const delta of candidates){const k=`${Math.round(delta.xMm*1e5)},${Math.round(delta.yMm*1e5)}`;if(seen.has(k))continue;seen.add(k);if(accept&&!accept(delta))continue;let count=0;for(const row of rows)count+=row.offsets.filter(o=>isHole(board,{xMm:row.i.xMm+delta.xMm+o.xMm,yMm:row.i.yMm+delta.yMm+o.yMm},catalog,{threadOnly:true,excludeMounting:true})).length;if(!best||count>best.count||count===best.count&&delta.d<best.d)best={...delta,count};if(count===rows.reduce((sum,row)=>sum+row.offsets.length,0))break;}
    return best?{xMm:best.xMm,yMm:best.yMm}:{...desired};
  }
  function snapUnfastenedPlate(parent,offsets,desired,catalog){
    // With no chosen fasteners the full hole array is a positioning reference,
    // not a screw pattern that must all align. Follow the nearest real hole
    // translation instead of searching the whole carrier for maximum overlap.
    const selected=new Set((parent.mountingHoles||[]).map(key));
    const targets=holes(parent,catalog).filter(h=>h.type==='thread'&&!selected.has(key(h)));
    let bestDistance=Infinity,bestX=desired.xMm,bestY=desired.yMm;
    for(const offset of offsets)for(const target of targets){
      const xMm=target.xMm-offset.xMm,yMm=target.yMm-offset.yMm;
      const dx=xMm-desired.xMm,dy=yMm-desired.yMm,distance=dx*dx+dy*dy;
      if(distance<bestDistance){
        bestDistance=distance;bestX=xMm;bestY=yMm;
        if(distance<EPS*EPS)return{xMm:bestX,yMm:bestY};
      }
    }
    return{xMm:bestX,yMm:bestY};
  }
  function partialMountingMinimum(layout){const n=layout?.minimumAlignedMountingHoles;return layout?.baseOverhangAllowedWithPartialMounting===true&&Number.isInteger(n)&&n>=2&&n<=128?n:0}
  function isMountingHole(board,point,catalog){const record=recordFor(board,catalog);if(!contains(board,point,catalog)||!isHole(board,point,catalog,{threadOnly:true,excludeMounting:true}))return false;if(!record)return board.holeType==='M6_through';const index=holeIndex(record),x=Math.round(point.xMm*1e5),y=Math.round(point.yMm*1e5);for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)if((index.get(`${x+dx},${y+dy}`)||[]).some(h=>h.type==='thread'&&h.thread==='M6x1.0'&&Math.hypot(h.xMm-point.xMm,h.yMm-point.yMm)<EPS&&!(board.mountingHoles||[]).some(v=>v.holeId===h.id)))return true;return false}
  function mountingMatches(board,instance,offsets,catalog){const seen=new Set(),result=[];for(const h of offsets){const point={xMm:instance.xMm+h.xMm,yMm:instance.yMm+h.yMm},k=`${Math.round(point.xMm*1e5)},${Math.round(point.yMm*1e5)}`;if(!seen.has(k)&&isMountingHole(board,point,catalog)){seen.add(k);result.push(point)}}return result}
  // Explicit edge-mount policy: nearest pose satisfying each actual screw pattern,
  // rather than preferring a farther pose with more screws than required.
  function snapMountedDelta(board,instances,offsetsFor,minimumFor,desired,catalog,accept=null){
    if(!instances.length)return null;const selected=new Set((board.mountingHoles||[]).map(key)),targets=holes(board,catalog).filter(h=>h.type==='thread'&&(!recordFor(board,catalog)||h.thread==='M6x1.0')&&!selected.has(key(h))&&contains(board,h,catalog)),rows=instances.map(i=>({i,offsets:offsetsFor(i),minimum:minimumFor(i)}));
    if(rows.some(row=>!row.offsets.length||!Number.isInteger(row.minimum)||row.minimum<1||row.minimum>row.offsets.length))return null;
    const first=rows[0],candidates=[],seen=new Set();for(const offset of first.offsets)for(const h of targets){const xMm=h.xMm-first.i.xMm-offset.xMm,yMm=h.yMm-first.i.yMm-offset.yMm,k=`${Math.round(xMm*1e5)},${Math.round(yMm*1e5)}`;if(seen.has(k))continue;seen.add(k);candidates.push({xMm,yMm,d:(xMm-desired.xMm)**2+(yMm-desired.yMm)**2})}
    candidates.sort((a,b)=>a.d-b.d||a.xMm-b.xMm||a.yMm-b.yMm);for(const delta of candidates){if(!rows.every(row=>mountingMatches(board,{xMm:row.i.xMm+delta.xMm,yMm:row.i.yMm+delta.yMm},row.offsets,catalog).length>=row.minimum))continue;if(accept&&!accept(delta))continue;return{xMm:delta.xMm,yMm:delta.yMm}}return null;
  }
  const api={configure,recordFor,customMounting,mountingCandidates,customMountingError,allowsCoveredMounting,normalizeBoard,outline,cutouts,contains,containsPolygon,region,overlaps,holes,mountingPositions,isHole,nearest,path,markup,referenceMarkup,snapDelta,snapMountedDelta,partialMountingMinimum,isMountingHole,mountingMatches,key};
  root.ZZLabRegisteredBoards=api;if(typeof module==='object'&&module.exports)module.exports=api;
  api.installBase=function(Editor){
    const P=Editor.prototype,old={};for(const name of ['normalizeBoard','boardErrors','syncFields','isBoardHole','snap','freeSpot','commonDelta','outOfBounds','mountingPositions','mountingIssues','manualMountingError','setMountingHoles','beginManualMounting','pickManualMounting','applyManualMounting','renderManualMounting','renderBoard','bind'])old[name]=P[name];
    const reg=e=>recordFor(e.board,e.catalog),$=id=>root.document.getElementById(id),svg=(tag,attrs,parent)=>{const n=root.document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.appendChild(n);return n};
    P.normalizeBoard=function(b){if(this.catalog)configure(this.catalog);return b?.registeredBoardId?normalizeBoard(b,this.catalog):old.normalizeBoard.call(this,b)};
    P.boardErrors=function(b){if(!b?.registeredBoardId)return old.boardErrors.call(this,b);try{normalizeBoard(b,this.catalog);return[]}catch(error){return[error.message]}};
    P.syncFields=function(){old.syncFields.call(this);const fixed=Boolean(reg(this));for(const id of ['board-width','board-height','board-pitch','board-offset','board-thickness','board-hole-type','board-hole-diameter'])if($(id))$(id).disabled=fixed;const note=$('registered-board-note');if(note){note.hidden=!fixed;note.textContent=fixed?`${reg(this).name} · 原板尺寸和孔位固定。可编辑板上布局、安装孔选择与垫高。`:''}const explanation=$('mounting-settings')?.querySelector?.('.mounting-explanation'),indexNote=$('mounting-settings')?.querySelector?.('.mounting-index-note');if(explanation){explanation.dataset.originalText??=explanation.textContent;explanation.textContent=fixed?(customMounting(reg(this))?'默认全为M6螺纹孔；用自选沉孔标记待加工孔位，保存工程后生成对应加工资料。':allowsCoveredMounting(this.board,this.catalog)?'位移台上板固定孔允许被器件覆盖；先固定上板，再安装上方器件。原孔位和孔尺寸保持不变。':'只选择原板已经存在的固定孔。不会在此板上新钻孔，也不改变原孔尺寸。'):explanation.dataset.originalText}if(indexNote)indexNote.hidden=fixed};
    P.isBoardHole=function(x,y){return reg(this)?isHole(this.board,{xMm:x,yMm:y},this.catalog,{threadOnly:true}):old.isBoardHole.call(this,x,y)};
    P.snap=function(x,y,i=null){if(this.partialMountingMinimum?.(i))return old.snap.call(this,x,y,i);if(!reg(this))return old.snap.call(this,x,y,i);const origin={...(i||{}),xMm:0,yMm:0},delta=snapDelta(this.board,[origin],v=>this.anchorGrid(v).offsets,{xMm:x,yMm:y},this.catalog);return delta};
    P.freeSpot=function(i=null){if(!reg(this))return old.freeSpot.call(this,i);const targets=holes(this.board,this.catalog).filter(h=>h.type==='thread');for(const h of targets){const p=this.snap(h.xMm,h.yMm,i),placed={...i,...p};if(!this.outOfBounds(placed)&&!this.instances.some(v=>Math.hypot(v.xMm-p.xMm,v.yMm-p.yMm)<EPS))return p;}return this.snap(this.board.widthMm/2,this.board.heightMm/2,i)};
    P.commonDelta=function(instances,dx,dy,options={}){if(instances.some(i=>this.partialMountingMinimum?.(i)))return old.commonDelta.call(this,instances,dx,dy,options);if(!reg(this)||options.snapToGrid===false)return old.commonDelta.call(this,instances,dx,dy,options);return snapDelta(this.board,instances,i=>this.anchorGrid(i).offsets,{xMm:dx,yMm:dy},this.catalog)};
    P.outOfBounds=function(i){if(this.allowsPartialBaseOverhang?.(i))return false;if(!reg(this))return old.outOfBounds.call(this,i);const b=this.localBounds(i,'base'),poly=[{xMm:b.xMin,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMin},{xMm:b.xMax,yMm:b.yMax},{xMm:b.xMin,yMm:b.yMax}].map(p=>this.worldPoint(i,p));return!containsPolygon(this.board,poly,this.catalog)};
    P.mountingPositions=function(){return reg(this)?mountingPositions(this.board,this.catalog):old.mountingPositions.call(this)};
    P.mountingIssues=function(){if(!reg(this))return old.mountingIssues.call(this);const issues=[],seen=new Set();for(const h of this.board.mountingHoles||[]){const error=this.manualMountingError(h,this.board.mountingHoles);if(error||seen.has(h.holeId))issues.push({code:'board_mounting_invalid',instanceIds:[],holeIds:[h.holeId],message:error||'固定孔重复。'});seen.add(h.holeId)}return issues};
    P.manualMountingError=function(h,chosen=[]){const r=reg(this);if(!r)return old.manualMountingError.call(this,h,chosen);const source=r.holesMm.find(v=>v.id===h.holeId);if(!source||!mountingCandidates(r).includes(h.holeId))return'请选择此板允许的固定孔位置。';const error=customMountingError(r,h.holeId,chosen);if(error)return error;if(allowsCoveredMounting(this.board,this.catalog))return'';const obstruction=this.mountingObstructions(source);return obstruction.length?'这个固定孔被器件遮挡，请移动器件或另选源板固定孔。':''};
    P.setMountingHoles=function(h){if(!reg(this))return old.setMountingHoles.call(this,h);const normalized=normalizeBoard({...this.board,mountingHoles:h},this.catalog);this.cancelManualMounting(false);const before=this.historySnapshot();this.board=normalized;this.commit(before);this.render()};
    P.beginManualMounting=function(){const r=reg(this);if(!r)return old.beginManualMounting.call(this);if(this.manualMounting){this.cancelManualMounting();return}if(!mountingCandidates(r).length)return this.notify('源板固定孔尚未登记，不能在画布中添加孔。',true);if(this.boardFormDirty)return this.notify('请先完成当前板的编辑。',true);this.manualMounting={holes:copy(this.board.mountingHoles||[]),count:mountingCandidates(r).length,registered:true,source:JSON.stringify(this.snapshot())};this.pendingKitId=null;this.keyboardActive=true;$('mounting-settings').open=false;this.render();};
    P.pickManualMounting=function(point){if(!reg(this))return old.pickManualMounting.call(this,point);const draft=this.manualMounting;if(!draft)return false;const h=nearest(this.board,point,this.catalog,{mountingOnly:true});if(!h||h.distance>36)return this.notify(customMounting(reg(this))?'请点击板上的M6螺纹孔。':'请点击源板已有的固定孔。',true),false;const index=draft.holes.findIndex(v=>v.holeId===h.holeId);if(index>=0)draft.holes.splice(index,1);else{const hole={holeId:h.holeId},error=this.manualMountingError(hole,draft.holes);if(error)return this.notify(error,true),false;draft.holes.push(hole);}this.render();return true};
    P.applyManualMounting=function(){if(!reg(this))return old.applyManualMounting.call(this);const draft=this.manualMounting;if(!draft)return false;if(draft.source!==JSON.stringify(this.snapshot()))return this.notify('布局已经改变，请重新选孔。',true),false;const required=customMounting(reg(this))?0:reg(this).minimumAlignedMountingHoles||Math.min(4,reg(this).mountingHoleIds.length);if(draft.holes.length<required)return this.notify(`请至少选 ${required} 个原板固定孔。`,true),false;for(const h of draft.holes){const error=this.manualMountingError(h,draft.holes);if(error)return this.notify(error,true),false}this.setMountingHoles(draft.holes);this.notify(customMounting(reg(this))?'已保存自选沉孔位置；后续按此工程生成加工模型。':'已选择源板固定孔；没有新增加工孔。');return true};
    P.renderManualMounting=function(scene){if(!reg(this))return old.renderManualMounting.call(this,scene);const draft=this.manualMounting,bar=$('mounting-manual-bar');if(bar)bar.hidden=!draft;const button=$('mounting-manual');if(button){button.textContent=draft?'退出手动选孔':customMounting(reg(this))?'自选沉孔':'选择源板固定孔';button.setAttribute('aria-pressed',String(Boolean(draft)))}scene.mountings.setAttribute('display',draft?'none':'inline');if(!scene.manualMountingLayer&&draft)scene.manualMountingLayer=svg('g',{class:'manual-mounting-layer','pointer-events':'none'},scene.sceneRoot||this.svg);if(!scene.manualMountingLayer)return;scene.manualMountingLayer.setAttribute('display',draft?'inline':'none');if(!draft)return;const error=draft.holes.map(h=>this.manualMountingError(h,draft.holes)).find(Boolean),required=customMounting(reg(this))?0:reg(this).minimumAlignedMountingHoles||Math.min(4,reg(this).mountingHoleIds.length);$('mounting-manual-status').textContent=`${customMounting(reg(this))?'自选沉孔 · Ø6.6通 / Ø11深6.5':'选择原板固定孔'} · 已选 ${draft.holes.length}${required?' · 至少 '+required+' 个':''}${error?' · '+error:''}`;$('mounting-manual-apply').disabled=Boolean(error)||draft.holes.length<required;scene.manualMountingLayer.innerHTML=mountingPositions({...this.board,mountingHoles:draft.holes},this.catalog).map(h=>`<g transform="translate(${h.xMm} ${this.board.heightMm-h.yMm})"><circle r="5.5"/><text x="7" y="-6">${escape(h.holeId)}</text></g>`).join('');};
    P.renderBoard=function(scene){old.renderBoard.call(this,scene);const fixed=Boolean(reg(this));scene.board.setAttribute('display',fixed?'none':'inline');scene.holes.setAttribute('display',fixed?'none':'inline');if(fixed&&!scene.registeredShape){scene.registeredShape=svg('g',{class:'registered-board-shape'},scene.sceneRoot);scene.sceneRoot.insertBefore(scene.registeredShape,scene.rulers)}if(scene.registeredShape){scene.registeredShape.setAttribute('display',fixed?'inline':'none');if(fixed){const signature=JSON.stringify([this.board.registeredBoardId,this.board.registeredBoardRevision,reg(this)?.referenceAnnotations?.revision,this.board.mountingHoles]);if(scene.registeredKey!==signature){scene.registeredKey=signature;scene.registeredShape.innerHTML=markup(this.board,this.catalog)}}}};
    P.bind=function(){old.bind.call(this);$('board-form')?.addEventListener('submit',e=>{if(reg(this)){e.preventDefault();e.stopImmediatePropagation();this.syncFields();this.notify('原板尺寸和孔位固定；请在板上编辑器件布局。');}},true)};
  };
  api.installStack=function(Editor){const P=Editor.prototype;
    // Replace only the root support. Existing instances and small boards retain
    // their coordinates and identities; the ordinary layout check reports any
    // holes or boundaries that no longer match the selected physical board.
    P.setMainBoard=function(source,mode='breadboard'){
      if(this.manualMounting||this.boardFormDirty)throw new Error('请先完成当前板的参数或选孔编辑。');
      if(!['breadboard','table'].includes(mode))throw new Error('底板模式无效。');
      const board=this.validBoard(source);if(!board)throw new Error('主面包板参数无效。');
      const record=recordFor(board,this.catalog);
      if(record&&(record.stageOnly||(this.catalog.stageModules||[]).some(m=>m.runtime?.topBoardId===record.id)))throw new Error('位移台专用顶板须保留完整位移模块，不能单独作为主面包板。');
      this.onBeforeContextChange?.();const before=this.historySnapshot(),layout=this.snapshot();
      const changedBoard=layout.board.registeredBoardId!==board.registeredBoardId||layout.board.registeredBoardRevision!==board.registeredBoardRevision;if(changedBoard&&(record?.lifecycle?.state==='historical'||record?.lifecycle?.canCreate===false))throw new Error('历史板件不能新增。');const contents=record&&changedBoard?defaultContents(record,this.catalog):[];if(layout.instances.length+contents.length>500)throw new Error('最多放置 500 个套件。');layout.instances.push(...contents);layout.board=board;if(mode==='table')layout.baseMode='table';else delete layout.baseMode;
      this.loadLayout(layout);const changed=this.commit(before);if(!changed)this.render();this.fit();return changed;
    };
    P.setRegisteredMainBoard=function(id){
      const record=(this.catalog.registeredBoards||[]).find(r=>r.id===id);if(!record)throw new Error('目录里没有这块面包板。');if(record.lifecycle?.state==='historical'||record.lifecycle?.canCreate===false)throw new Error('历史板件只能用于已有工程，不能新增。');
      const current=this.snapshot().board,source=current.registeredBoardId===id&&current.registeredBoardRevision===record.revision?current:{registeredBoardId:id,registeredBoardRevision:record.revision};
      const changed=this.setMainBoard(source);this.notify(`已将 ${record.name} 设为主面包板；不再另垫底板。原有布局保留，可撤销。`);return changed;
    };
    P.addRegisteredBoard=function(id,position){const record=(this.catalog.registeredBoards||[]).find(r=>r.id===id);if(!record)throw new Error('目录里没有这块面包板。');if(record.lifecycle?.state==='historical'||record.lifecycle?.canCreate===false)throw new Error('历史板件只能用于已有工程，不能新增。');if(this.manualMounting||this.boardFormDirty)throw new Error('请先完成当前板的参数或选孔编辑。');this.onBeforeContextChange?.();const before=this.historySnapshot(),layout=this.snapshot();layout.subBoards??=[];if(layout.subBoards.length>=24)throw new Error('最多支持 24 块小面包板。');const board=normalizeBoard({registeredBoardId:record.id,registeredBoardRevision:record.revision},this.catalog),pid='plate-'+root.crypto.randomUUID(),desired=position||{xMm:layout.board.widthMm/2,yMm:layout.board.heightMm/2},pose={xMm:desired.xMm-board.widthMm/2,yMm:desired.yMm-board.heightMm/2,rotationDeg:0},snapped=api.snapPlate(layout.board,board,pose,this.catalog,layout.baseMode==='table');const contents=defaultContents(record,this.catalog,pid);if(layout.instances.length+contents.length>500)throw new Error('最多放置 500 个套件。');layout.subBoards.push({id:pid,name:record.name,board,...snapped,rotationDeg:0});layout.instances.push(...contents);this.loadLayout(layout);this.selectedModuleId=pid;this.commit(before);this.notify(`已加入 ${record.name}。可直接拖动整板，右键编辑板上器件。`);return pid;};
  };
  api.snapPlate=function(parent,board,pose,catalog=activeCatalog,onTable=false){if(onTable)return{xMm:pose.xMm,yMm:pose.yMm};const source=mountingPositions(board,catalog),points=source.length?source:holes(board,catalog),a=(pose.rotationDeg||0)*Math.PI/180,c=Math.round(Math.cos(a)),s=Math.round(Math.sin(a)),offsets=points.map(p=>({xMm:c*p.xMm-s*p.yMm,yMm:s*p.xMm+c*p.yMm}));return source.length?snapDelta(parent,[{xMm:0,yMm:0}],()=>offsets,pose,catalog):snapUnfastenedPlate(parent,offsets,pose,catalog)};
})(typeof globalThis!=='undefined'?globalThis:this);
