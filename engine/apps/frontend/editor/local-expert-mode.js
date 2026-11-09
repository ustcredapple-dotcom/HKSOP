(function (root) {
  'use strict';
  if (!root.ZZLAB_LOCAL || !root.BreadboardEditor) return;
  root.ZZLAB_LOCAL_EXPERT = true;
  const P = root.BreadboardEditor.prototype;
  const old = {};
  for (const name of ['boardErrors', 'manualMountingError', 'beginManualMounting', 'pickManualMounting', 'applyManualMounting', 'renderManualMounting', 'mountingIssues', 'validation', 'render']) old[name] = P[name];
  const copy = value => JSON.parse(JSON.stringify(value));
  const el = id => document.getElementById(id);
  const key = hole => hole.holeId !== undefined ? String(hole.holeId) : `${hole.columnIndex},${hole.rowIndex}`;
  const structuralCodes = new Set(['invalid_layout', 'invalid_elevation', 'invalid_post_selection', 'invalid_stage_motion', 'unknown_kit', 'invalid_mounting_holes']);
  const reportCache = new WeakMap();

  function holeError(editor, hole) {
    const board = editor.board;
    if (board.registeredBoardId) {
      const record = root.ZZLabRegisteredBoards?.recordFor(board, editor.catalog);
      return record?.mountingHoleIds?.includes(hole?.holeId) ? '' : '请选择源板已登记的实际固定孔。';
    }
    const columns = Math.floor((board.widthMm-2*board.edgeOffsetMm)/board.pitchMm+1e-5)+1;
    const rows = Math.floor((board.heightMm-2*board.edgeOffsetMm)/board.pitchMm+1e-5)+1;
    return Number.isInteger(hole?.columnIndex) && Number.isInteger(hole?.rowIndex) && hole.columnIndex >= 0 && hole.columnIndex < columns && hole.rowIndex >= 0 && hole.rowIndex < rows ? '' : '请选择板内实际孔阵的整数孔位。';
  }

  function relaxValidation(report) {
    if (!report || !Array.isArray(report.issues)) return report;
    if (reportCache.has(report)) return reportCache.get(report);
    const warnings = [...(report.warnings || []), ...report.issues.filter(issue => !structuralCodes.has(issue.code)).map(issue => ({...issue, severity: 'warning'}))];
    const issues = report.issues.filter(issue => structuralCodes.has(issue.code));
    const result = {...report, valid: issues.length === 0, issues, warnings: warnings.filter((v, i, all) => all.findIndex(w => JSON.stringify(w) === JSON.stringify(v)) === i)};
    reportCache.set(report, result);
    return result;
  }

  P.boardErrors = function (board) {
    if (board?.registeredBoardId) return old.boardErrors.call(this, board);
    const errors = old.boardErrors.call(this, {...board, mountingHoles: []});
    if (!Array.isArray(board?.mountingHoles)) return [...errors, '安装孔须为孔阵位置数组。'];
    const fake = Object.create(this); fake.board = board;
    for (const hole of board.mountingHoles) {const error = holeError(fake, hole); if (error && !errors.includes(error)) errors.push(error);}
    if (new Set(board.mountingHoles.map(key)).size !== board.mountingHoles.length) errors.push('安装孔不能重复。');
    return errors;
  };
  P.manualMountingError = function (hole) {return holeError(this, hole);};
  P.beginManualMounting = function () {
    if (this.selectedModuleId && !this.editModule(this.selectedModuleId)) return false;
    if (this.manualMounting) {this.cancelManualMounting(); return;}
    if (this.boardFormDirty) return this.notify('请先更新当前面包板参数。', true);
    this.pendingKitId = null;
    this.manualMounting = {holes: copy(this.board.mountingHoles || []), count: Number.MAX_SAFE_INTEGER, registered: Boolean(this.board.registeredBoardId), source: JSON.stringify(this.snapshot())};
    this.keyboardActive = true;
    if (el('mounting-settings')) el('mounting-settings').open = false;
    this.render(); this.svg?.focus?.({preventScroll: true});
    document.dispatchEvent(new CustomEvent('layout-validity-change'));
  };
  P.pickManualMounting = function (point) {
    const draft = this.manualMounting; if (!draft) return false;
    if (this.boardFormDirty || draft.source !== JSON.stringify(this.snapshot())) {this.cancelManualMounting(); this.notify('画布已改变，请重新开启手动选孔。', true); return false;}
    let hole;
    if (this.board.registeredBoardId) {
      const nearby = root.ZZLabRegisteredBoards.nearest(this.board, point, this.catalog, {mountingOnly: true});
      if (!nearby || nearby.distance > 36) {this.notify('请点击源板已登记的固定孔。', true); return false;}
      hole = {holeId: nearby.holeId};
    } else {
      const b = this.board, columnIndex = Math.round((point.xMm-b.edgeOffsetMm)/b.pitchMm), rowIndex = Math.round((point.yMm-b.edgeOffsetMm)/b.pitchMm);
      if (Math.hypot(point.xMm-b.edgeOffsetMm-columnIndex*b.pitchMm, point.yMm-b.edgeOffsetMm-rowIndex*b.pitchMm) > Math.min(b.pitchMm*.42, 6)) {this.notify('请点在实际孔位附近。', true); return false;}
      hole = {columnIndex, rowIndex};
    }
    const error = holeError(this, hole); if (error) {this.notify(error, true); return false;}
    const index = draft.holes.findIndex(h => key(h) === key(hole));
    if (index >= 0) draft.holes.splice(index, 1); else draft.holes.push(hole);
    this.render(); return true;
  };
  P.applyManualMounting = function () {
    const draft = this.manualMounting; if (!draft) return false;
    if (this.boardFormDirty || draft.source !== JSON.stringify(this.snapshot())) {this.cancelManualMounting(); this.notify('画布已改变，请重新开启手动选孔。', true); return false;}
    const error = draft.holes.map(h => holeError(this, h)).find(Boolean);
    if (error || new Set(draft.holes.map(key)).size !== draft.holes.length) {this.notify(error || '安装孔不能重复。', true); return false;}
    const holes = copy(draft.holes); if (!this.board.registeredBoardId) holes.sort((a,b) => a.rowIndex-b.rowIndex || a.columnIndex-b.columnIndex);
    this.setMountingHoles(holes);
    document.dispatchEvent(new CustomEvent('layout-validity-change'));
    this.notify(`已应用 ${holes.length} 个所选安装孔；固定方式由使用者确认。`);
    return true;
  };
  P.renderManualMounting = function (scene) {
    old.renderManualMounting.call(this, scene);
    const draft = this.manualMounting; if (!draft) return;
    const error = draft.holes.map(h => holeError(this, h)).find(Boolean) || (new Set(draft.holes.map(key)).size !== draft.holes.length ? '安装孔不能重复。' : '');
    if (el('mounting-manual-status')) el('mounting-manual-status').textContent = `专业编辑 · 已选 ${draft.holes.length} 个孔 · 数量不限${error ? ' · '+error : ''}`;
    if (el('mounting-manual-apply')) {el('mounting-manual-apply').disabled = Boolean(error); el('mounting-manual-apply').textContent = '应用所选孔位';}
  };
  P.mountingIssues = function () {
    const issues = old.mountingIssues.call(this).filter(issue => !/安装沉孔必须是 4 或 8|四个安装沉孔的横纵坐标差|八孔需由行列奇偶/.test(issue.message));
    if (this.board.registeredBoardId) for (const hole of this.board.mountingHoles || []) {
      const message = old.manualMountingError.call(this, hole, this.board.mountingHoles);
      if (message && !issues.some(issue => issue.message === message)) issues.push({code: 'mounting_hole_obstructed', instanceIds: [], holeIds: [hole.holeId], message});
    }
    return issues;
  };
  P.validation = function () {return relaxValidation(old.validation.call(this));};
  P.render = function () {
    old.render.call(this);
    const report = this.validation(), warning = el('layout-warning');
    if (!warning || report.issues?.length) return;
    if (this._localExpertShownReport !== report) {
      this._localExpertShownReport = report;
      const notes = report.warnings || [];
      warning.hidden = notes.length === 0;
      warning.classList.remove('layout-invalid');
      warning.style.color = '#795314'; warning.style.background = '#fff9ed'; warning.style.borderColor = '#ddc597';
      warning.replaceChildren();
      const summary = document.createElement('summary'); summary.textContent = `专业模式 · ${notes.length} 项安装提示`; warning.appendChild(summary);
      const list = document.createElement('ul');
      for (const note of notes.slice(0, 100)) {const row = document.createElement('li'); row.textContent = note.message; list.appendChild(row);}
      warning.appendChild(list);
      const hint = document.createElement('p'); hint.textContent = '这些提示用于人工核对，不阻止编辑、保存和导出；软件保留实际孔位和高度。'; warning.appendChild(hint);
    }
    if (el('layout-validity')) {el('layout-validity').textContent = '专业编辑 · 可保存'; el('layout-validity').classList.remove('invalid');}
    if (this.manualMounting && el('layout-hint')) el('layout-hint').textContent = '手动选孔：点击孔位选择或取消 · 数量不限（可为 0） · Enter 应用 · Esc 取消';
  };
  root.ZZLabLocalExpert = {relaxValidation, structuralCodes, holeError};
})(window);
