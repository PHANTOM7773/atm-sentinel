from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any

import cv2

from .errors import CVError

_CPU_PROFILE_NAME = "cpu"


def _backend_choices() -> dict[str, int]:
    choices = {"cpu": cv2.dnn.DNN_BACKEND_OPENCV, "opencv": cv2.dnn.DNN_BACKEND_OPENCV}
    if hasattr(cv2.dnn, "DNN_BACKEND_CUDA"):
        choices["cuda"] = cv2.dnn.DNN_BACKEND_CUDA
    if hasattr(cv2.dnn, "DNN_BACKEND_TIMVX"):
        choices["timvx"] = cv2.dnn.DNN_BACKEND_TIMVX
    if hasattr(cv2.dnn, "DNN_BACKEND_CANN"):
        choices["cann"] = cv2.dnn.DNN_BACKEND_CANN
    return choices


def _target_choices() -> dict[str, int]:
    choices = {"cpu": cv2.dnn.DNN_TARGET_CPU}
    if hasattr(cv2.dnn, "DNN_TARGET_CUDA"):
        choices["cuda"] = cv2.dnn.DNN_TARGET_CUDA
    if hasattr(cv2.dnn, "DNN_TARGET_CUDA_FP16"):
        choices["cuda_fp16"] = cv2.dnn.DNN_TARGET_CUDA_FP16
    if hasattr(cv2.dnn, "DNN_TARGET_NPU"):
        choices["npu"] = cv2.dnn.DNN_TARGET_NPU
    return choices


def _label(choices: dict[str, int], value: int) -> str:
    for name, candidate in choices.items():
        if candidate == value:
            return name
    return str(value)


@dataclass(frozen=True)
class RuntimeProfile:
    requested_backend: str
    requested_target: str
    backend_id: int
    target_id: int
    fallback: bool = False
    fallback_reason: str = ""

    @classmethod
    def from_names(cls, backend: str, target: str) -> "RuntimeProfile":
        backends = _backend_choices()
        targets = _target_choices()
        backend_name = backend.strip().lower() or _CPU_PROFILE_NAME
        target_name = target.strip().lower() or _CPU_PROFILE_NAME
        backend_id = backends.get(backend_name)
        target_id = targets.get(target_name)
        if backend_id is None or target_id is None:
            return cls(
                requested_backend=backend,
                requested_target=target,
                backend_id=backends[_CPU_PROFILE_NAME],
                target_id=targets[_CPU_PROFILE_NAME],
                fallback=True,
                fallback_reason="Unknown backend or target; using OpenCV CPU",
            )
        return cls(backend_name, target_name, backend_id, target_id)

    @classmethod
    def from_env(cls) -> "RuntimeProfile":
        return cls.from_names(
            os.getenv("ATM_SENTINEL_CV_BACKEND", _CPU_PROFILE_NAME),
            os.getenv("ATM_SENTINEL_CV_TARGET", _CPU_PROFILE_NAME),
        )

    def to_dict(self) -> dict[str, Any]:
        backends = _backend_choices()
        targets = _target_choices()
        return {
            "requested_backend": self.requested_backend,
            "requested_target": self.requested_target,
            "effective_backend": _label(backends, self.backend_id),
            "effective_target": _label(targets, self.target_id),
            "backend_id": self.backend_id,
            "target_id": self.target_id,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
        }


def cpu_profile() -> RuntimeProfile:
    return RuntimeProfile.from_names(_CPU_PROFILE_NAME, _CPU_PROFILE_NAME)


def facade_profile(profile: RuntimeProfile) -> RuntimeProfile:
    if profile.backend_id == cv2.dnn.DNN_BACKEND_OPENCV and profile.target_id != cv2.dnn.DNN_TARGET_CPU:
        return replace(
            profile,
            target_id=cv2.dnn.DNN_TARGET_CPU,
            fallback=True,
            fallback_reason="OpenCV backend does not support non-CPU targets; using CPU target",
        )
    return profile


def create_with_fallback(factory: Any, profile: RuntimeProfile) -> tuple[Any, RuntimeProfile]:
    selected = facade_profile(profile)
    try:
        return factory(selected), selected
    except cv2.error as exc:
        if selected.backend_id == cpu_profile().backend_id and selected.target_id == cpu_profile().target_id:
            raise CVError(f"OpenCV CPU backend could not initialize model: {exc}") from exc
        fallback = cpu_profile()
        fallback = replace(
            fallback,
            requested_backend=profile.requested_backend,
            requested_target=profile.requested_target,
            fallback=True,
            fallback_reason=f"Requested backend failed; using OpenCV CPU: {exc}"[:300],
        )
        return factory(fallback), fallback


def _configured_state(profile: RuntimeProfile) -> dict[str, Any]:
    return {
        **profile.to_dict(),
        "observed": False,
        "verification_state": "configured_not_yet_verified",
        "fallback_observed": False,
        "fallback_predicted": bool(profile.fallback),
        "note": "Configured profile only; no model instance was created to verify actual runtime state.",
    }


def configured_runtime_summary(backend: str, target: str) -> dict[str, Any]:
    return _configured_state(facade_profile(RuntimeProfile.from_names(backend, target)))


def configured_model_runtime(backend: str, target: str) -> dict[str, dict[str, Any]]:
    requested = RuntimeProfile.from_names(backend, target)
    return {
        key: _configured_state(facade_profile(requested))
        for key in ("yunet", "sface", "yolox")
    }


def configure_net(net: Any, profile: RuntimeProfile) -> RuntimeProfile:
    selected = facade_profile(profile)
    try:
        net.setPreferableBackend(selected.backend_id)
        if selected.backend_id != cv2.dnn.DNN_BACKEND_OPENCV:
            net.setPreferableTarget(selected.target_id)
        return selected
    except cv2.error as exc:
        if selected == cpu_profile():
            raise CVError(f"OpenCV CPU backend could not be configured: {exc}") from exc
        fallback = cpu_profile()
        net.setPreferableBackend(fallback.backend_id)
        return replace(
            fallback,
            requested_backend=profile.requested_backend,
            requested_target=profile.requested_target,
            fallback=True,
            fallback_reason=f"{type(exc).__name__}: {exc}"[:300],
        )


__all__ = [
    "RuntimeProfile",
    "configure_net",
    "configured_model_runtime",
    "configured_runtime_summary",
    "cpu_profile",
    "create_with_fallback",
    "facade_profile",
]
