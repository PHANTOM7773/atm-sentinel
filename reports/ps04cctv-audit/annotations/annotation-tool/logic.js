/* Pure logic for TASK 09 annotator state transitions. Used by app.js and Node tests. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AnnotationPilotLogic = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function applyNoFaceToggle(frame, checked) {
    if (!frame) return frame;
    frame.no_face = !!checked;
    if (frame.no_face) {
      frame.faces = [];
      frame.annotation_status = 'annotated';
      frame.needs_review = false;
    } else {
      if ((frame.faces || []).length === 0) {
        frame.annotation_status = 'not_annotated';
        frame.needs_review = false;
      } else if (frame.annotation_status !== 'needs_review') {
        frame.annotation_status = 'annotated';
        frame.needs_review = false;
      }
    }
    return frame;
  }

  function applyBoxAdded(frame) {
    if (!frame) return frame;
    frame.no_face = false;
    if (frame.annotation_status !== 'needs_review') {
      frame.annotation_status = 'annotated';
      frame.needs_review = false;
    }
    return frame;
  }

  function applyBoxDeleted(frame, removedWasLast) {
    if (!frame) return frame;
    if (removedWasLast && (frame.faces || []).length === 0 && !frame.no_face) {
      if (frame.annotation_status !== 'needs_review') {
        frame.annotation_status = 'not_annotated';
        frame.needs_review = false;
      }
    }
    return frame;
  }

  function normalizeFrameForExport(frame) {
    // Preserve explicit needs_review; no-face reviewed frames should be annotated.
    if (frame.no_face) {
      frame.faces = [];
      if (frame.annotation_status !== 'needs_review') frame.annotation_status = 'annotated';
    }
    frame.needs_review = frame.annotation_status === 'needs_review';
    return frame;
  }

  return { applyNoFaceToggle, applyBoxAdded, applyBoxDeleted, normalizeFrameForExport };
});
