from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.bytetrack_benchmark import run_task14_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="TASK 14 isolated person tracker benchmark")
    parser.add_argument("--output", default="reports/ps04cctv-audit/TASK-14-PERSON-TRACKING-BENCHMARK.json")
    args = parser.parse_args()
    result = run_task14_benchmark()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
