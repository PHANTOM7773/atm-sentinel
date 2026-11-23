from __future__ import annotations

from dataclasses import replace
from typing import Any

import cv2
import numpy as np

from ..config import CV_BACKEND, CV_FACE_SCORE_THRESHOLD, CV_PERSON_SCORE_THRESHOLD, CV_TARGET
from .errors import CVError
from .models import require_model
from .runtime import RuntimeProfile, configure_net, cpu_profile, create_with_fallback, facade_profile
from .types import BoundingBox, FaceDetection, PersonDetection, Point


class YuNetFaceDetector:
    def __init__(
        self,
        score_threshold: float = CV_FACE_SCORE_THRESHOLD,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        model_key: str = "yunet",
        profile: RuntimeProfile | None = None,
    ) -> None:
        self.model_key = model_key
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self.profile = profile or RuntimeProfile.from_names(CV_BACKEND, CV_TARGET)
        path = require_model(model_key)

        def factory(selected: RuntimeProfile) -> Any:
            return cv2.FaceDetectorYN.create(
                str(path),
                "",
                (320, 320),
                self.score_threshold,
                self.nms_threshold,
                self.top_k,
                selected.backend_id,
                selected.target_id,
            )

        self.detector, self.profile = create_with_fallback(factory, self.profile)

    def detect(self, image: np.ndarray) -> list[FaceDetection]:
        if image is None or image.size == 0:
            return []
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) == 0:
            return []
        results: list[FaceDetection] = []
        for row in faces:
            values = [float(item) for item in row]
            if len(values) < 15 or not np.isfinite(values).all():
                continue
            new_layout = values[14] <= 1.0 and values[4] > 1.0
            confidence = values[14] if new_layout else values[4]
            if confidence < self.score_threshold:
                continue
            bbox: BoundingBox = (values[0], values[1], values[2], values[3])
            landmark_start = 4 if new_layout else 5
            landmarks: tuple[Point, Point, Point, Point, Point] = tuple(
                (values[landmark_start + index * 2], values[landmark_start + index * 2 + 1])
                for index in range(5)
            )
            results.append(FaceDetection(bbox=bbox, confidence=confidence, landmarks=landmarks))
        return results


class YOLOXPersonDetector:
    PERSON_CLASS_ID = 0

    def __init__(
        self,
        score_threshold: float = CV_PERSON_SCORE_THRESHOLD,
        nms_threshold: float = 0.45,
        input_size: int = 640,
        model_key: str = "yolox",
        profile: RuntimeProfile | None = None,
    ) -> None:
        self.model_key = model_key
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.input_size = int(input_size)
        self.profile = profile or RuntimeProfile.from_names(CV_BACKEND, CV_TARGET)
        path = require_model(model_key)
        try:
            self.net = cv2.dnn.readNetFromONNX(str(path))
        except cv2.error as exc:
            raise CVError(f"Could not load YOLOX ONNX model: {exc}") from exc
        self.profile = configure_net(self.net, self.profile)
        self.output_names = self.net.getUnconnectedOutLayersNames()
        self.strides = [8, 16, 32]
        self.grids, self.expanded_strides = self._generate_anchors()

    def _generate_anchors(self) -> tuple[np.ndarray, np.ndarray]:
        grids: list[np.ndarray] = []
        strides: list[np.ndarray] = []
        for stride in self.strides:
            hsize = self.input_size // stride
            wsize = self.input_size // stride
            xv, yv = np.meshgrid(np.arange(hsize), np.arange(wsize))
            grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(grid)
            strides.append(np.full((1, grid.shape[1], 1), stride, dtype=np.float32))
        return np.concatenate(grids, 1), np.concatenate(strides, 1)

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        target_h, target_w = self.input_size, self.input_size
        padded = np.full((target_h, target_w, 3), 114.0, dtype=np.float32)
        ratio = min(target_h / image.shape[0], target_w / image.shape[1])
        resized_w = max(1, int(image.shape[1] * ratio))
        resized_h = max(1, int(image.shape[0] * ratio))
        resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        padded[:resized_h, :resized_w] = resized
        return padded, ratio

    def _forward(self) -> Any:
        try:
            return self.net.forward(self.output_names)
        except cv2.error as exc:
            if self.profile.backend_id == cpu_profile().backend_id and self.profile.target_id == cpu_profile().target_id:
                raise CVError(f"YOLOX inference failed on CPU: {exc}") from exc
            fallback = cpu_profile()
            self.net.setPreferableBackend(fallback.backend_id)
            self.profile = replace(
                self.profile,
                backend_id=fallback.backend_id,
                target_id=fallback.target_id,
                fallback=True,
                fallback_reason=f"Inference error on requested backend: {exc}"[:300],
            )
            return self.net.forward(self.output_names)

    def _postprocess(self, outputs: list[np.ndarray], ratio: float, image_shape: tuple[int, ...]) -> list[PersonDetection]:
        if not outputs:
            return []
        dets = np.asarray(outputs[0], dtype=np.float32)
        if dets.ndim == 3:
            dets = dets[0]
        if dets.ndim != 2 or dets.shape[1] < 85:
            return []

        dets = dets.copy()
        dets[:, :2] = (dets[:, :2] + self.grids) * self.expanded_strides
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.expanded_strides

        boxes = dets[:, :4]
        boxes_xywh = np.ones_like(boxes)
        boxes_xywh[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
        boxes_xywh[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
        boxes_xywh[:, 2] = boxes[:, 2]
        boxes_xywh[:, 3] = boxes[:, 3]

        scores = dets[:, 4:5] * dets[:, 5:85]
        max_scores = np.amax(scores, axis=1)
        max_scores_idx = np.argmax(scores, axis=1)

        keep = cv2.dnn.NMSBoxesBatched(
            boxes_xywh.tolist(),
            max_scores.tolist(),
            max_scores_idx.tolist(),
            self.score_threshold,
            self.nms_threshold,
        )
        if keep is None or len(keep) == 0:
            return []
        if isinstance(keep, tuple):
            keep = keep[0]
        indices = np.asarray(keep).reshape(-1).astype(int)

        height, width = image_shape[:2]
        results: list[PersonDetection] = []
        for index in indices:
            if index < 0 or index >= len(dets) or int(max_scores_idx[index]) != self.PERSON_CLASS_ID:
                continue
            confidence = float(max_scores[index])
            if confidence < self.score_threshold:
                continue
            x, y, box_w, box_h = (float(value) / ratio for value in boxes_xywh[index])
            x1 = max(0.0, min(x, float(width - 1)))
            y1 = max(0.0, min(y, float(height - 1)))
            x2 = max(0.0, min(x + box_w, float(width)))
            y2 = max(0.0, min(y + box_h, float(height)))
            if x2 <= x1 or y2 <= y1:
                continue
            results.append(
                PersonDetection(
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    confidence=confidence,
                    class_id=self.PERSON_CLASS_ID,
                )
            )
        return results

    def detect(self, image: np.ndarray) -> list[PersonDetection]:
        if image is None or image.size == 0:
            return []
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        padded, ratio = self._letterbox(rgb)
        blob = np.expand_dims(np.transpose(padded, (2, 0, 1)), 0).astype(np.float32)
        self.net.setInput(blob)
        outputs = self._forward()
        return self._postprocess(outputs, ratio, image.shape)


__all__ = ["FaceDetection", "PersonDetection", "YuNetFaceDetector", "YOLOXPersonDetector"]
