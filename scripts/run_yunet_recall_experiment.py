#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.face_detection_experiments import DEFAULT_VARIANTS, ExperimentalVariant  # noqa: E402
from app.cv.yunet_recall_experiment import DEFAULT_DATASET_DIR, evaluate_yunet_variants, write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated YuNet recall/shadow detection experiments on synthetic clips.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "ps04cctv-audit"))
    parser.add_argument("--clips", default="", help="Comma-separated clip names; default all")
    parser.add_argument("--dedupe-iou", type=float, default=0.5)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    clip_names = [c.strip() for c in args.clips.split(",") if c.strip()] or None
    report = evaluate_yunet_variants(
        Path(args.dataset_dir),
        clip_names=clip_names,
        variants=list(DEFAULT_VARIANTS),
        dedupe_iou=args.dedupe_iou,
    )
    outputs = write_report(report, Path(args.out_dir))
    if args.print_summary:
        summary = {
            "outputs": outputs,
            "clips": list(report["comparison"]["clips"]),
        }
        print(json.dumps(summary, indent=2))
    else:
        print(outputs["json"])
        print(outputs["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
