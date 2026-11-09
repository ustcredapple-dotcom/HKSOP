'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),R=require('../static/registered-boards.js');
const catalog=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../catalog.json'))),copy=x=>JSON.parse(JSON.stringify(x));
let count=0;
for(const row of catalog.registeredBoards.filter(r=>r.referenceAnnotations)){
  const stripped=copy(catalog);for(const r of stripped.registeredBoards)delete r.referenceAnnotations;
  const ref={registeredBoardId:row.id,registeredBoardRevision:row.revision},b=R.normalizeBoard(ref,catalog);
  assert.deepEqual(b,R.normalizeBoard(ref,stripped));
  for(const fn of ['holes','outline','cutouts'])assert.deepEqual(R[fn](b,catalog),R[fn](b,stripped));
  assert.deepEqual(R.region(b,{xMm:135,yMm:87,rotationDeg:90},catalog),R.region(b,{xMm:135,yMm:87,rotationDeg:90},stripped));
  const svg=R.markup(b,catalog),refs=row.referenceAnnotations;
  assert.match(svg,/pointer-events="none" aria-label="位置参考标注/);
  assert.equal((svg.match(/data-registered-hole=/g)||[]).length,row.holesMm.length);
  assert.doesNotMatch(svg,/玻璃腔中心|data-reference-center="glass-center"/);
  if(row.id==='optical-frame-for1'){
    assert.equal(refs.sectionHeightAboveBoardTopMm,113.06370626);
    assert.ok(refs.projections.length>=10);
    assert.ok(refs.projections.every(p=>p.kind==='obstruction-section'));
    assert.equal((svg.match(/data-reference-kind="obstruction-section"/g)||[]).length,refs.projections.length);
    assert.doesNotMatch(svg,/data-reference-kind="(?:leg|glass|coil|coil-section|iontrap)"|离子阱中心/);
    assert.match(svg,/113.064 mm/);
    for(const segment of svg.matchAll(/<g data-reference-kind="obstruction-section"[^]*?<\/g>/g)){
      assert.match(segment[0],/fill-rule="evenodd"/);assert.match(segment[0],/stroke-dasharray="none"/);
    }
  }else{
    assert.equal((svg.match(/data-reference-kind="leg"/g)||[]).length,13);
    assert.equal((svg.match(/data-reference-kind="iontrap"/g)||[]).length,12);
    const center=refs.centers.find(p=>p.id==='iontrap-center');assert.match(svg,new RegExp(`cy="${b.heightMm-center.yMm}"`));
    assert.match(svg,/离子阱中心/);
    const coils=refs.projections.filter(p=>p.kind==='coil');
    assert.equal(coils.length,1);assert.equal(coils[0].cutoutsMm.length,135);
    assert.equal((svg.match(/data-reference-kind="coil-section"/g)||[]).length,8);
    const coilMarkup=svg.match(/<g data-reference-kind="coil"[^]*?<\/g>/)[0];
    assert.match(coilMarkup,/fill="none"/);assert.match(coilMarkup,/fill-rule="evenodd"/);
    assert.equal((coilMarkup.match(/M /g)||[]).length,136);
  }
  assert.match(svg,/未计光束直径/);

  assert.doesNotMatch(R.markup(b,catalog,{outlineOnly:true}),/reference|玻璃腔/);
  assert.equal(R.referenceMarkup(b,stripped),'');
  const unsafe=copy(catalog);unsafe.registeredBoards.find(r=>r.id===row.id).referenceAnnotations.centers[0].label='<script>bad</script>';
  assert.doesNotMatch(R.referenceMarkup(b,unsafe),/<script>/);
  count++;
}
assert.equal(count,3);console.log('PASS: all 3 FOR overlays are display-only; native regions, holes, references and rotated board geometry unchanged; labels escaped.');
