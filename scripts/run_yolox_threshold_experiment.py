#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.yolox_threshold_experiment import DEFAULT_DATASET_DIR, DEFAULT_THRESHOLDS, evaluate_yolox_thresholds, write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated YOLOX threshold sensitivity/reliability evaluation.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "ps04cctv-audit"))
    parser.add_argument("--clips", default="")
    parser.add_argument("--thresholds", default="0.10,0.20,0.30,0.40,0.45,0.50")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    clip_names = [c.strip() for c in args.clips.split(",") if c.strip()] or None
    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    report = evaluate_yolox_thresholds(Path(args.dataset_dir), clip_names=clip_names, thresholds=thresholds)
    outputs = write_report(report, Path(args.out_dir))
    if args.print_summary:
        print(json.dumps({"outputs": outputs, "thresholds": thresholds}, indent=2))
    else:
        print(outputs["json"])
        print(outputs["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
