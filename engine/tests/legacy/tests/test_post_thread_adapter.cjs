const assert=require('node:assert/strict'),G=require('../static/global-height.js'),c=require('../catalog.json');
c.components.find(c=>c.id==='custom-post-metric-12p5mm-m1').postTopThread='M6'; // Explicit legacy fixture.
const board={widthMm:500,heightMm:300,pitchMm:25,edgeOffsetMm:12.5,thicknessMm:12.5,holeType:'M6_through',mountingHoles:[]};
const l={board,instances:[{id:'h2',kitId:'motor-2-90-h2-coplanar-r1',xMm:200,yMm:150,rotationDeg:0}]},before=structuredClone(l);
const approved=G.plan(l,c,75);assert.equal(approved.valid,true);assert.equal(approved.layout.instances[0].universalPostSelection['custom-post-metric-12p5mm-m1'],'custom-post-metric-25mm-m1');assert(approved.notes.some(n=>n.code==='post_thread_adapter_required'));assert.deepEqual(l,before);
const unapproved=structuredClone(c);delete unapproved.kits.find(k=>k.id===l.instances[0].kitId).layout.postThreadAdapterAccepted;
assert.equal(G.plan(l,unapproved,75).issues[0].code,'post_thread_conflict');
assert.equal(G.plan(approved.layout,c,62.5).notes.length,0);assert.deepEqual(G.plan(approved.layout,c,62.5).layout,l);
console.log('PASS explicit approval allows pending-spec adapter; unapproved change still blocked; restore removes requirement.');
