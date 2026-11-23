from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.face_retrieval_experiment import run_benchmark


def main() -> int:
    ap = argparse.ArgumentParser(description="TASK 18 face retrieval benchmark")
    ap.add_argument("--dataset", default="data/datasets/synthetic/cv")
    ap.add_argument("--output", default="reports/ps04cctv-audit/TASK-18-FACE-RETRIEVAL-BENCHMARK.json")
    args = ap.parse_args()

    report = run_benchmark(ROOT / args.dataset)
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")
    da = report["dataset_audit"]
    print(f"samples={da['total_samples']} subjects={da['unique_subjects']} clips={da['clips_with_samples']}")
    p = report["pairs"]["cross_clip"]
    print(f"cross_clip pairs={p['count']} pos={p['positive']} neg={p['negative']}")
    r = report["retrieval"]["source_clip_excluded"]
    print(f"cross_clip retrieval={r.get('status')} rank1={r.get('rank1')} rank5={r.get('rank5')} mrr={r.get('mrr')} assessed={r.get('assessed_queries')}")
    roc = report["roc_auc"]["cross_clip_pairs"]
    print(f"roc_cross_clip={roc.get('status')} auc={roc.get('auc')} eer={roc.get('eer_proxy')}")
    ta = report["threshold_analysis"]
    b = ta.get("best_balanced_offline")
    if b:
        print(f"best_offline_thr={b['threshold']} far={b['far']} missed={b['missed_match_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
