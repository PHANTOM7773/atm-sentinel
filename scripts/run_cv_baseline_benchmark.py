#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.baseline_benchmark import DEFAULT_DATASET_DIR, evaluate_dataset, write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ATM Sentinel CV baseline benchmark (local, synthetic/sample only).")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "ps04cctv-audit"))
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--warmup-runs", type=int, default=0)
    parser.add_argument("--measurement-runs", type=int, default=1)
    parser.add_argument("--skip-load-timing", action="store_true")
    parser.add_argument("--load-timing-repeats", type=int, default=1)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    report = evaluate_dataset(
        Path(args.dataset_dir),
        max_frames=args.max_frames,
        frame_stride=args.frame_stride,
        top_k=args.top_k,
        warmup_runs=args.warmup_runs,
        measurement_runs=args.measurement_runs,
        include_load_timing=not args.skip_load_timing,
        load_timing_repeats=args.load_timing_repeats,
    )
    outputs = write_report(report, Path(args.out_dir))
    if args.print_summary:
        print(json.dumps({"outputs": outputs, "generated_at": report["meta"]["generated_at"], "clips": list(report["dataset"]["videos"].keys())}, indent=2))
    else:
        print(outputs["json"])
        print(outputs["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
