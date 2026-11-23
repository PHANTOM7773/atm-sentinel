/* TASK 09 offline annotator. No uploads, no detector suggestions. */
const state = {
  selection: null,
  annotations: null,
  index: 0,
  selectedBox: -1,
  drawing: null,
  image: new Image(),
  scale: 1,
};

const els = Object.fromEntries([
  'selectionInput','loadInput','exportBtn','exportQaBtn','prevBtn','nextBtn','frameInfo','statusBadge','pathInfo',
  'imageCanvas','overlayCanvas','frameStatus','noFace','frameNotes','boxInfo','visibility','pose','faceSize','blur',
  'illumination','confidence','ignoreDifficult','boxNotes','deleteBoxBtn','boxList'
].map(id => [id, document.getElementById(id)]));

function nowIso() { return new Date().toISOString(); }
function uid() { return 'ann_' + Math.random().toString(36).slice(2, 10) + '_' + Date.now().toString(36); }
function clamp(n, min, max) { return Math.max(min, Math.min(max, n)); }

function emptyAnnotationDoc(selection) {
  return {
    schema_version: '1.0-pilot',
    annotation_type: 'face_bbox_ground_truth_pilot',
    dataset_id: selection.dataset_id || 'synthetic-cv',
    source_manifest: selection.source_manifest || 'data/datasets/synthetic/cv/manifest.json',
    selection_manifest: 'reports/ps04cctv-audit/annotations/selected-frames-manifest.json',
    bbox_format: 'xywh_pixels_top_left',
    coordinate_space: 'original_frame_pixels',
    created_at: nowIso(),
    updated_at: nowIso(),
    annotator: '',
    annotation_tool: 'task09-offline-annotator/1.0',
    notes: 'HUMAN ANNOTATION REQUIRED. No auto ground truth.',
    frames: selection.frames.map(f => ({
      clip_id: f.clip_id, clip_file: f.clip_file, frame_index: f.frame_index, timestamp_ms: f.timestamp_ms,
      image_width: f.image_width, image_height: f.image_height, derived_image_path: f.derived_image_path,
      derived_image_sha256: f.derived_image_sha256, source_video_path: f.source_video_path,
      annotation_status: 'not_annotated', no_face: false, needs_review: false, frame_notes: '', faces: []
    }))
  };
}

function currentFrame() { return state.annotations?.frames[state.index]; }
function currentSel() { return state.selection?.frames[state.index]; }

function setStatusBadge(status) {
  els.statusBadge.textContent = status.replace(/_/g, ' ').toUpperCase();
  els.statusBadge.className = 'badge ' + status;
}

function applyNoFaceToggle(frame, checked) {
  if (!frame) return;
  frame.no_face = !!checked;
  if (frame.no_face) {
    frame.faces = [];
    frame.annotation_status = 'annotated';
    frame.needs_review = false;
  } else {
    // Unchecking no-face must not silently claim reviewed/annotated.
    if ((frame.faces || []).length === 0) {
      frame.annotation_status = 'not_annotated';
      frame.needs_review = false;
    } else if (frame.annotation_status !== 'needs_review') {
      frame.annotation_status = 'annotated';
      frame.needs_review = false;
    }
  }
}

function applyBoxAdded(frame) {
  if (!frame) return;
  frame.no_face = false;
  if (frame.annotation_status !== 'needs_review') {
    frame.annotation_status = 'annotated';
    frame.needs_review = false;
  }
}

function applyBoxDeleted(frame, removedWasLast) {
  if (!frame) return;
  if (removedWasLast && (frame.faces || []).length === 0 && !frame.no_face) {
    if (frame.annotation_status !== 'needs_review') {
      frame.annotation_status = 'not_annotated';
      frame.needs_review = false;
    }
  }
}

function saveFrameFields() {
  const f = currentFrame(); if (!f) return;
  const prevStatus = f.annotation_status;
  f.annotation_status = els.frameStatus.value;
  f.needs_review = f.annotation_status === 'needs_review';
  f.frame_notes = els.frameNotes.value;
  const checked = els.noFace.checked;
  if (checked !== !!f.no_face) {
    applyNoFaceToggle(f, checked);
  } else {
    f.no_face = !!checked;
    if (f.no_face) { f.faces = []; state.selectedBox = -1; f.annotation_status = 'annotated'; f.needs_review = false; }
    else if (f.annotation_status === 'needs_review') { f.needs_review = true; }
    else if (prevStatus === 'needs_review' && els.frameStatus.value === 'needs_review') { f.needs_review = true; }
  }
  state.annotations.updated_at = nowIso();
}

function saveBoxFields() {
  const f = currentFrame(); if (!f) return;
  const b = f.faces[state.selectedBox]; if (!b) return;
  b.visibility = els.visibility.value;
  b.pose = els.pose.value;
  b.face_size = els.faceSize.value;
  b.blur = els.blur.value;
  b.illumination = els.illumination.value;
  b.annotation_confidence = els.confidence.value;
  b.ignore_difficult = els.ignoreDifficult.checked;
  b.notes = els.boxNotes.value;
  state.annotations.updated_at = nowIso();
}

function loadFrameFields() {
  const f = currentFrame(); if (!f) return;
  els.frameStatus.value = f.annotation_status || 'not_annotated';
  els.noFace.checked = !!f.no_face;
  els.frameNotes.value = f.frame_notes || '';
  setStatusBadge(f.annotation_status || 'not_annotated');
}

function loadBoxFields() {
  const f = currentFrame();
  const b = f?.faces[state.selectedBox];
  if (!b) {
    els.boxInfo.textContent = 'No box selected. Drag on image to draw.';
    ['visibility','pose','faceSize','blur','illumination','confidence'].forEach(()=>{});
    els.ignoreDifficult.checked = false; els.boxNotes.value = '';
    return;
  }
  els.boxInfo.textContent = `Selected ${b.annotation_id} bbox=[${b.bbox.map(n=>Math.round(n)).join(', ')}]`;
  els.visibility.value = b.visibility;
  els.pose.value = b.pose;
  els.faceSize.value = b.face_size;
  els.blur.value = b.blur;
  els.illumination.value = b.illumination;
  els.confidence.value = b.annotation_confidence;
  els.ignoreDifficult.checked = !!b.ignore_difficult;
  els.boxNotes.value = b.notes || '';
}

function renderBoxList() {
  const f = currentFrame();
  els.boxList.innerHTML = '';
  (f?.faces || []).forEach((b, i) => {
    const li = document.createElement('li');
    li.textContent = `${i+1}. ${b.annotation_id.slice(0,18)} [${b.bbox.map(n=>Math.round(n)).join(',')}] ${b.ignore_difficult ? 'IGNORE' : ''}`;
    if (i === state.selectedBox) li.classList.add('selected');
    li.onclick = () => { saveBoxFields(); state.selectedBox = i; loadBoxFields(); renderBoxList(); drawOverlay(); };
    els.boxList.appendChild(li);
  });
}

function fitCanvases() {
  const img = state.image;
  if (!img.width) return;
  const maxW = Math.max(320, document.querySelector('.canvasWrap').clientWidth - 4);
  state.scale = Math.min(1.5, maxW / img.width);
  const w = Math.round(img.width * state.scale);
  const h = Math.round(img.height * state.scale);
  for (const c of [els.imageCanvas, els.overlayCanvas]) { c.width = w; c.height = h; c.style.width = w+'px'; c.style.height = h+'px'; }
  els.imageCanvas.getContext('2d').drawImage(img, 0, 0, w, h);
  drawOverlay();
}

function drawOverlay() {
  const ctx = els.overlayCanvas.getContext('2d');
  ctx.clearRect(0,0,els.overlayCanvas.width,els.overlayCanvas.height);
  const f = currentFrame(); if (!f) return;
  f.faces.forEach((b, i) => {
    const [x,y,w,h] = b.bbox.map(v => v * state.scale);
    ctx.lineWidth = i === state.selectedBox ? 3 : 2;
    ctx.strokeStyle = b.ignore_difficult ? '#ffcc00' : (i === state.selectedBox ? '#00ff88' : '#ff4444');
    ctx.strokeRect(x,y,w,h);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillRect(x, Math.max(0,y-16), 80, 16);
    ctx.fillStyle = '#000';
    ctx.font = '12px sans-serif';
    ctx.fillText(`${i+1} ${b.face_size}`, x+2, Math.max(12,y-4));
  });
  if (state.drawing) {
    const {x,y,w,h} = state.drawing;
    ctx.strokeStyle = '#44aaff'; ctx.lineWidth = 2; ctx.strokeRect(x,y,w,h);
  }
}

function canvasToOriginal(evt) {
  const r = els.overlayCanvas.getBoundingClientRect();
  const x = clamp((evt.clientX - r.left) / state.scale, 0, state.image.width);
  const y = clamp((evt.clientY - r.top) / state.scale, 0, state.image.height);
  return {x, y};
}

function loadIndex(i) {
  if (!state.annotations) return;
  saveBoxFields(); saveFrameFields();
  state.index = clamp(i, 0, state.annotations.frames.length - 1);
  state.selectedBox = -1;
  const f = currentFrame(); const s = currentSel();
  els.frameInfo.textContent = `${state.index+1}/${state.annotations.frames.length} | ${f.clip_id} frame ${f.frame_index} | ${f.timestamp_ms} ms | ${f.image_width}x${f.image_height}`;
  els.pathInfo.textContent = `derived: ${f.derived_image_path} | source: ${f.source_video_path}`;
  loadFrameFields(); loadBoxFields(); renderBoxList();
  state.image.onload = fitCanvases;
  state.image.src = '../frames/' + f.derived_image_path.split('/').pop();
}

function ensureAnnotationFromSelection(selection) {
  state.selection = selection;
  state.annotations = emptyAnnotationDoc(selection);
  state.index = 0;
  loadIndex(0);
}

function mergeLoadedAnnotation(doc) {
  if (!state.selection) { alert('Load selection manifest first.'); return; }
  const byKey = new Map();
  for (const f of doc.frames || []) byKey.set(`${f.clip_id}::${f.frame_index}`, f);
  for (const f of state.annotations.frames) {
    const k = `${f.clip_id}::${f.frame_index}`;
    if (byKey.has(k)) {
      const src = byKey.get(k);
      f.annotation_status = src.annotation_status || f.annotation_status;
      f.no_face = !!src.no_face;
      f.needs_review = !!src.needs_review;
      f.frame_notes = src.frame_notes || '';
      f.faces = Array.isArray(src.faces) ? src.faces : [];
    }
  }
  state.annotations.annotator = doc.annotator || '';
  state.annotations.updated_at = nowIso();
  loadIndex(state.index);
}

function exportJson(doc, name) {
  const blob = new Blob([JSON.stringify(doc, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

function buildQaSummary() {
  saveBoxFields(); saveFrameFields();
  const frames = state.annotations.frames;
  const summary = {
    task: 'TASK-09', qa_status: 'NOT_REVIEWED', benchmark_ready: false,
    total_selected_frames: frames.length,
    annotated_frames: frames.filter(f=>f.annotation_status==='annotated').length,
    unannotated_frames: frames.filter(f=>f.annotation_status==='not_annotated').length,
    needs_review_frames: frames.filter(f=>f.annotation_status==='needs_review').length,
    total_face_boxes: frames.reduce((n,f)=>n+f.faces.length,0),
    no_face_frames: frames.filter(f=>f.no_face).length,
    difficult_ignored_faces: frames.reduce((n,f)=>n+f.faces.filter(b=>b.ignore_difficult).length,0),
    low_confidence_annotations: frames.reduce((n,f)=>n+f.faces.filter(b=>b.annotation_confidence==='low').length,0),
  };
  return summary;
}

els.selectionInput.onchange = async e => { const f = e.target.files[0]; if (!f) return; ensureAnnotationFromSelection(JSON.parse(await f.text())); };
els.loadInput.onchange = async e => { const f = e.target.files[0]; if (!f) return; mergeLoadedAnnotation(JSON.parse(await f.text())); };
els.prevBtn.onclick = () => loadIndex(state.index - 1);
els.nextBtn.onclick = () => loadIndex(state.index + 1);
els.exportBtn.onclick = () => { if (!state.annotations) return; saveBoxFields(); saveFrameFields(); exportJson(state.annotations, 'human-annotations.json'); };
els.exportQaBtn.onclick = () => { if (!state.annotations) return; exportJson(buildQaSummary(), 'qa-summary.json'); };
els.frameStatus.onchange = () => { saveFrameFields(); loadFrameFields(); };
els.noFace.onchange = () => { saveFrameFields(); loadFrameFields(); renderBoxList(); drawOverlay(); loadBoxFields(); };
els.frameNotes.onchange = saveFrameFields;
['visibility','pose','faceSize','blur','illumination','confidence','ignoreDifficult','boxNotes'].forEach(id => {
  els[id].onchange = () => { saveBoxFields(); renderBoxList(); drawOverlay(); };
});
els.deleteBoxBtn.onclick = () => {
  const f = currentFrame(); if (!f || state.selectedBox < 0) return;
  const removedWasLast = f.faces.length === 1;
  f.faces.splice(state.selectedBox, 1);
  state.selectedBox = -1;
  applyBoxDeleted(f, removedWasLast);
  state.annotations.updated_at = nowIso();
  loadFrameFields(); renderBoxList(); loadBoxFields(); drawOverlay();
};

els.overlayCanvas.addEventListener('mousedown', evt => {
  const f = currentFrame(); if (!f || f.no_face) return;
  const p = canvasToOriginal(evt);
  state.drawing = {startX:p.x, startY:p.y, x:p.x*state.scale, y:p.y*state.scale, w:0, h:0};
});
els.overlayCanvas.addEventListener('mousemove', evt => {
  if (!state.drawing) return;
  const p = canvasToOriginal(evt);
  const x = Math.min(state.drawing.startX, p.x), y = Math.min(state.drawing.startY, p.y);
  const w = Math.abs(p.x - state.drawing.startX), h = Math.abs(p.y - state.drawing.startY);
  state.drawing = {...state.drawing, currX:p.x, currY:p.y, x:x*state.scale, y:y*state.scale, w:w*state.scale, h:h*state.scale};
  drawOverlay();
});
window.addEventListener('mouseup', evt => {
  if (!state.drawing) return;
  const p = canvasToOriginal(evt);
  const x = Math.min(state.drawing.startX, p.x), y = Math.min(state.drawing.startY, p.y);
  const w = Math.abs(p.x - state.drawing.startX), h = Math.abs(p.y - state.drawing.startY);
  state.drawing = null;
  const f = currentFrame(); if (!f) return;
  if (w < 2 || h < 2) { drawOverlay(); return; }
  const ann = {
    annotation_id: uid(), bbox: [Number(x.toFixed(2)), Number(y.toFixed(2)), Number(w.toFixed(2)), Number(h.toFixed(2))],
    visibility: 'visible', pose: 'unknown', face_size: 'medium', blur: 'none', illumination: 'normal',
    annotation_confidence: 'medium', ignore_difficult: false, notes: ''
  };
  f.faces.push(ann); state.selectedBox = f.faces.length - 1;
  applyBoxAdded(f);
  saveFrameFields(); loadFrameFields(); renderBoxList(); loadBoxFields(); drawOverlay();
});
window.addEventListener('resize', fitCanvases);
