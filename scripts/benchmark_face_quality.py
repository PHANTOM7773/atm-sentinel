from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cv.face_quality_experiment import evaluate_face_quality
from app.cv.quality import analyze_face_quality


def degrade(img: np.ndarray) -> dict[str, np.ndarray]:
    h, w = img.shape[:2]
    blur = cv2.GaussianBlur(img, (21, 21), 8)
    down = cv2.resize(cv2.resize(img, (max(8, w // 4), max(8, h // 4)), interpolation=cv2.INTER_AREA), (w, h), interpolation=cv2.INTER_LINEAR)
    low_light = cv2.convertScaleAbs(img, alpha=0.35, beta=-20)
    low_contrast = cv2.convertScaleAbs(img, alpha=0.45, beta=60)
    rng = np.random.default_rng(3)
    noise = np.clip(img.astype(np.int16) + rng.integers(-45, 46, size=img.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    return {
        "original": img,
        "blur": blur,
        "downscale": down,
        "low_light": low_light,
        "low_contrast": low_contrast,
        "noise": noise,
    }


def score(img: np.ndarray) -> dict[str, object]:
    old = analyze_face_quality(img)
    new = evaluate_face_quality(img)
    return {
        "old_quality_score": old.get("quality_score"),
        "new_overall_score": new.get("overall_score"),
        "old_components": old.get("components"),
        "new_dimensions": {d["name"]: d["score"] for d in new["dimensions"]},
        "new_reason_codes": new.get("reason_codes"),
        "new_missing_dimensions": new.get("missing_dimensions"),
    }


def main() -> int:
    crops = sorted((ROOT / "data/cv/crops").rglob("*.jpg"))
    # pick a small deterministic set
    picks = []
    for p in crops:
        img = cv2.imread(str(p))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        picks.append((p, float(cv2.Laplacian(gray, cv2.CV_64F).var()), float(gray.mean()), img))
    if not picks:
        raise SystemExit("no crops found")
    picks.sort(key=lambda x: x[2])
    dark = picks[0]
    picks.sort(key=lambda x: x[1])
    blurry = picks[0]
    picks.sort(key=lambda x: abs(x[2] - 120) + abs(x[1] - 120))
    normal = picks[0]

    samples = {"dark_sample": dark, "blurred_sample": blurry, "normal_sample": normal}
    # include task15 demo inputs if present
    demo = ROOT / "reports/ps04cctv-audit/task15-enhancements/demo-summary.json"
    if demo.exists():
        for row in json.loads(demo.read_text()):
            ip = ROOT / row["input"]
            if ip.exists():
                img = cv2.imread(str(ip))
                if img is not None:
                    samples.setdefault(f"task15_{row['sample']}", (ip, 0.0, 0.0, img))

    report = {"samples": {}, "inconsistencies": []}
    for name, (p, _, _, img) in samples.items():
        variants = degrade(img)
        scored = {k: score(v) for k, v in variants.items()}
        report["samples"][name] = {
            "input": str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p),
            "variants": scored,
        }
        # expectations: degraded should not score higher than original on relevant dimension
        orig = scored["original"]
        checks = [
            ("blur", "sharpness"),
            ("downscale", "resolution"),
            ("low_light", "exposure"),
            ("low_contrast", "contrast"),
            ("noise", "noise"),
        ]
        for variant, dim in checks:
            o = orig["new_dimensions"].get(dim)
            v = scored[variant]["new_dimensions"].get(dim)
            if o is not None and v is not None and v > o + 1.0:
                report["inconsistencies"].append({
                    "sample": name, "variant": variant, "dimension": dim,
                    "original": o, "variant_score": v,
                    "note": "degraded variant scored higher than original; heuristic limitation/inconsistency"
                })

    out = ROOT / "reports/ps04cctv-audit/TASK-16-FACE-QUALITY-BENCHMARK.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")
    print(f"samples={len(report['samples'])} inconsistencies={len(report['inconsistencies'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
