from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.face_detector_gt_benchmark import DEFAULT_STRATEGIES, evaluate_strategy_on_annotations


def main() -> int:
    ap = argparse.ArgumentParser(description="TASK 17 face detector GT benchmark")
    ap.add_argument("--annotations", default="reports/ps04cctv-audit/annotations/human-annotations.status-fixed.json")
    ap.add_argument("--output", default="reports/ps04cctv-audit/TASK-17-FACE-DETECTOR-GT-BENCHMARK.json")
    ap.add_argument("--iou", type=float, nargs="*", default=[0.5])
    ap.add_argument("--conf", type=float, nargs="*", default=[0.0, 0.5, 0.7])
    args = ap.parse_args()

    report = evaluate_strategy_on_annotations(
        annotations_path=Path(args.annotations),
        base_dir=ROOT,
        strategies=DEFAULT_STRATEGIES,
        iou_thresholds=args.iou,
        conf_thresholds=args.conf,
    )
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")
    for row in report.get("comparison", {}).get("rows", []):
        print(row["strategy"], "P", row["precision"], "R", row["recall"], "F1", row["f1"], "AP50", row["ap50"], "noFaceFP", row["no_face_fp_frame_rate"], "ms", row["mean_latency_ms"], "fallback", row["fallback_rate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
