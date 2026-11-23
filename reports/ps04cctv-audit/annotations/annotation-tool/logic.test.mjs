import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const logic = require('./logic.js');

test('checking no-face sets annotated + no_face=true + empty faces', () => {
  const f = {annotation_status:'not_annotated', no_face:false, needs_review:false, faces:[{annotation_id:'a', bbox:[1,2,3,4]}]};
  logic.applyNoFaceToggle(f, true);
  assert.equal(f.no_face, true);
  assert.equal(f.annotation_status, 'annotated');
  assert.deepEqual(f.faces, []);
  assert.equal(f.needs_review, false);
});

test('unchecking no-face resets appropriately when no boxes', () => {
  const f = {annotation_status:'annotated', no_face:true, needs_review:false, faces:[]};
  logic.applyNoFaceToggle(f, false);
  assert.equal(f.no_face, false);
  assert.equal(f.annotation_status, 'not_annotated');
});

test('drawing a face box clears no_face and annotates', () => {
  const f = {annotation_status:'not_annotated', no_face:true, needs_review:false, faces:[]};
  logic.applyNoFaceToggle(f, true); // ensure no-face
  logic.applyBoxAdded(f);
  assert.equal(f.no_face, false);
  assert.equal(f.annotation_status, 'annotated');
});

test('deleting last box does not mark no-face', () => {
  const f = {annotation_status:'annotated', no_face:false, needs_review:false, faces:[]};
  logic.applyBoxDeleted(f, true);
  assert.equal(f.no_face, false);
  assert.equal(f.annotation_status, 'not_annotated');
});

test('needs_review preserved on box add/delete', () => {
  const f = {annotation_status:'needs_review', no_face:false, needs_review:true, faces:[{annotation_id:'a'}]};
  logic.applyBoxAdded(f);
  assert.equal(f.annotation_status, 'needs_review');
  logic.applyBoxDeleted(f, true);
  assert.equal(f.annotation_status, 'needs_review');
});

test('export/load round-trip shape preserved', () => {
  const doc = {frames:[{annotation_status:'annotated', no_face:true, faces:[], needs_review:false}]};
  logic.normalizeFrameForExport(doc.frames[0]);
  const json = JSON.stringify(doc);
  const loaded = JSON.parse(json);
  assert.equal(loaded.frames[0].no_face, true);
  assert.equal(loaded.frames[0].annotation_status, 'annotated');
  assert.deepEqual(loaded.frames[0].faces, []);
});
