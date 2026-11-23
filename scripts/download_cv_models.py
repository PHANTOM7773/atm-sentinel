from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ensure_dirs  # noqa: E402
from app.cv.models import MODEL_SPECS, model_path, sha256_file  # noqa: E402


def download_model(key: str, force: bool = False) -> dict[str, object]:
    spec = MODEL_SPECS[key]
    destination = model_path(key)
    if destination.exists() and not force:
        actual = sha256_file(destination)
        if spec.sha256 and actual != spec.sha256:
            raise RuntimeError(f"{key}: existing file has SHA256 {actual}, expected {spec.sha256}")
        return {
            "key": key,
            "filename": spec.filename,
            "size_bytes": destination.stat().st_size,
            "sha256": actual,
            "status": "already_present",
        }

    temporary = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(spec.source_url, headers={"User-Agent": "atm-sentinel-local-cv/1"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as sink:
        shutil.copyfileobj(response, sink)

    actual = sha256_file(temporary)
    if spec.sha256 and actual != spec.sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{key}: downloaded SHA256 {actual}, expected {spec.sha256}")
    temporary.replace(destination)
    return {
        "key": key,
        "filename": spec.filename,
        "size_bytes": destination.stat().st_size,
        "sha256": actual,
        "status": "downloaded",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download approved local CV model weights")
    parser.add_argument("--force", action="store_true", help="Replace existing model files")
    parser.add_argument("--only", choices=sorted(MODEL_SPECS), help="Download one model")
    args = parser.parse_args()

    ensure_dirs()
    keys = [args.only] if args.only else sorted(MODEL_SPECS)
    results = [download_model(key, args.force) for key in keys]
    manifest_path = model_path("yunet").parent / "SHA256SUMS.json"
    manifest = {
        "generated_by": "scripts/download_cv_models.py",
        "models": {str(result["key"]): result for result in results},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(f"{result['key']}: {result['status']} {result['filename']} {result['sha256']}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
