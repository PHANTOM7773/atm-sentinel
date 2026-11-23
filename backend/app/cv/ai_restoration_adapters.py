"""TASK 15 isolated AI restoration adapters.

No downloads/installs performed. Checks local availability only.
Pretrained weight licenses must be verified separately from code licenses.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any


@dataclass
class AdapterStatus:
    name: str
    code_package: str
    code_license: str
    weight_license_note: str
    package_installed: bool
    weights_available: bool
    ready: bool
    blockers: list[str]
    install_requirements: list[str]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _pkg(name: str) -> bool:
    return find_spec(name) is not None


def gfpgan_status(weights_dir: Path | None = None) -> AdapterStatus:
    pkg = _pkg("gfpgan")
    weights = False
    blockers = []
    if not pkg:
        blockers.append("missing_package:gfpgan")
    # common local weight names; do not download
    candidates = ["GFPGANv1.4.pth", "GFPGANv1.3.pth"]
    if weights_dir:
        weights = any((weights_dir / c).exists() for c in candidates)
    if not weights:
        blockers.append("missing_weights:gfpgan")
    return AdapterStatus(
        name="GFPGAN",
        code_package="gfpgan",
        code_license="Apache-2.0 (verify upstream repo/tag; third-party components may vary)",
        weight_license_note="Pretrained weights license/provenance must be verified separately before use; do not assume code license covers weights.",
        package_installed=pkg,
        weights_available=weights,
        ready=pkg and weights,
        blockers=blockers,
        install_requirements=[
            "pip install gfpgan basicsr facexlib torch torchvision",
            "Provide approved local GFPGAN weights (e.g. GFPGANv1.4.pth) in an approved model directory",
            "Verify weight license/provenance before production or external use",
        ],
    )


def realesrgan_status(weights_dir: Path | None = None) -> AdapterStatus:
    pkg = _pkg("realesrgan")
    weights = False
    blockers = []
    if not pkg:
        blockers.append("missing_package:realesrgan")
    candidates = ["RealESRGAN_x4plus.pth", "RealESRGAN_x2plus.pth"]
    if weights_dir:
        weights = any((weights_dir / c).exists() for c in candidates)
    if not weights:
        blockers.append("missing_weights:realesrgan")
    return AdapterStatus(
        name="Real-ESRGAN",
        code_package="realesrgan",
        code_license="BSD-3-Clause (verify upstream repo/tag)",
        weight_license_note="Pretrained weights license/provenance must be verified separately; some weights may have non-commercial/research restrictions.",
        package_installed=pkg,
        weights_available=weights,
        ready=pkg and weights,
        blockers=blockers,
        install_requirements=[
            "pip install realesrgan basicsr facexlib torch torchvision",
            "Provide approved local Real-ESRGAN weights in an approved model directory",
            "Verify weight license/provenance before use",
        ],
    )


def codeformer_status(weights_dir: Path | None = None) -> AdapterStatus:
    pkg = _pkg("codeformer") or _pkg("basicsr")  # CodeFormer often used via repo/basicsr integration
    # be conservative: require explicit codeformer package/module presence for "installed"
    pkg = _pkg("codeformer")
    weights = False
    blockers = []
    if not pkg:
        blockers.append("missing_package:codeformer")
    candidates = ["codeformer.pth"]
    if weights_dir:
        weights = any((weights_dir / c).exists() for c in candidates)
    if not weights:
        blockers.append("missing_weights:codeformer")
    return AdapterStatus(
        name="CodeFormer",
        code_package="codeformer",
        code_license="S-Lab License 1.0 / upstream terms apply (verify exact repo license; non-commercial restrictions may apply)",
        weight_license_note="Pretrained weights license/provenance must be verified separately; do not assume commercial/use rights.",
        package_installed=pkg,
        weights_available=weights,
        ready=pkg and weights,
        blockers=blockers,
        install_requirements=[
            "Install CodeFormer runtime/dependencies per approved upstream method (torch, basicsr, facexlib, etc.)",
            "Provide approved local CodeFormer weights (codeformer.pth) and required facelib weights",
            "Verify code and weight licenses/provenance before use",
        ],
    )


def all_ai_status(weights_dir: Path | None = None) -> dict[str, Any]:
    statuses = [gfpgan_status(weights_dir), realesrgan_status(weights_dir), codeformer_status(weights_dir)]
    return {
        "models": [s.to_dict() for s in statuses],
        "any_ready": any(s.ready for s in statuses),
        "notes": [
            "No AI model packages/weights were downloaded or installed by TASK 15.",
            "Code license and pretrained weight license/provenance are separate checks.",
            "Enhanced outputs are derived artifacts and must not overwrite originals or be used silently for matching.",
        ],
    }
