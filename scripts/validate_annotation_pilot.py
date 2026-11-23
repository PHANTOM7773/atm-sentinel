#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.cv.annotation_pilot import load_json, summarize_pilot, validate_pilot_document  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate TASK 09 human annotation pilot JSON.")
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--manifest", default=str(ROOT / "data/datasets/synthetic/cv/manifest.json"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    doc = load_json(args.annotations)
    selection = load_json(args.selection)
    manifest = load_json(args.manifest)
    issues = validate_pilot_document(doc, manifest=manifest)
    # selection coverage checks
    sel_keys = {(f["clip_id"], int(f["frame_index"])) for f in selection.get("frames", [])}
    ann_keys = {(f.get("clip_id"), int(f.get("frame_index"))) for f in doc.get("frames", []) if isinstance(f, dict) and isinstance(f.get("frame_index"), int)}
    missing = sorted(sel_keys - ann_keys)
    extra = sorted(ann_keys - sel_keys)
    from app.cv.annotation_pilot import ValidationIssue
    for k in missing:
        issues.append(ValidationIssue("warning", "frames", f"missing selected frame {k[0]}:{k[1]}"))
    for k in extra:
        issues.append(ValidationIssue("error", "frames", f"extra/unselected frame {k[0]}:{k[1]}"))
    summary = summarize_pilot(doc, issues)
    summary["selection_total"] = len(sel_keys)
    summary["missing_selected_frames"] = [list(k) for k in missing]
    summary["extra_frames"] = [list(k) for k in extra]
    summary["qa_status"] = "NOT_REVIEWED" if summary["validator_errors"] == [] else "REVIEW_REQUIRED"
    if summary["unannotated_frames"] > 0 or summary["needs_review_frames"] > 0:
        summary["qa_status"] = "REVIEW_REQUIRED"
    summary["benchmark_ready"] = False
    out = json.dumps(summary, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    print(out)
    return 1 if summary["validator_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
