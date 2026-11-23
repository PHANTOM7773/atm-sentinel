from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from ..config import (
    CV_BACKEND,
    CV_CROP_DIR,
    CV_MAX_CLIP_DURATION_SECONDS,
    CV_MAX_CROP_FILES,
    CV_MAX_CROPS_PER_ANALYSIS,
    CV_MAX_DECODED_FRAMES,
    CV_MAX_FACE_DETECTIONS_PER_ANALYSIS,
    CV_MAX_FACE_DETECTIONS_PER_FRAME,
    CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS,
    CV_MAX_FACE_OBSERVATIONS_PER_FRAME,
    CV_MAX_FRAME_STRIDE,
    CV_MAX_FRAMES,
    CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS,
    CV_MAX_PERSON_DETECTIONS_PER_FRAME,
    CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS,
    CV_MAX_PERSON_OBSERVATIONS_PER_FRAME,
    CV_MIN_EMBED_QUALITY,
    CV_OUTPUT_DIR,
    CV_TARGET,
    relative_to_data,
)
from .crop import crop_face, crop_signature, face_sample_id, prune_crops, safe_segment, save_crop
from .detection import YOLOXPersonDetector, YuNetFaceDetector
from .embeddings import (
    EMBEDDING_SCHEMA_VERSION,
    EmbeddingStore,
    StagedEmbedding,
    build_v4_embedding_record,
)
from .errors import CVError
from .models import MODEL_SPECS
from .runtime import RuntimeProfile, configured_model_runtime, create_with_fallback, facade_profile
from .tracking import SimpleTracker
from .types import FaceDetection, FrameAnalysis, ProgressCallback, VideoAnalysis

NEAR_DUPLICATE_HAMMING_DISTANCE = 5
NEAR_DUPLICATE_MAX_FRAME_GAP = 15


def _hamming_distance(first: str, second: str) -> int:
    if len(first) != len(second):
        return max(len(first), len(second))
    return sum(left != right for left, right in zip(first, second))


class CVPipeline:
    def __init__(
        self,
        load_face: bool = True,
        load_person: bool = True,
        load_embedder: bool = True,
        output_dir: Path = CV_OUTPUT_DIR,
        crop_dir: Path = CV_CROP_DIR,
        profile: RuntimeProfile | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.crop_dir = crop_dir
        selected_profile = facade_profile(profile or RuntimeProfile.from_names(CV_BACKEND, CV_TARGET))
        self.face_detector = YuNetFaceDetector(profile=selected_profile) if load_face else None
        self.person_detector = YOLOXPersonDetector(profile=selected_profile) if load_person else None
        self.embedder = None
        self.embedder_profile = None
        if load_embedder:
            from .models import require_model

            model_path = require_model("sface")

            def factory(chosen: RuntimeProfile) -> Any:
                return cv2.FaceRecognizerSF.create(
                    str(model_path),
                    "",
                    chosen.backend_id,
                    chosen.target_id,
                )

            self.embedder, self.embedder_profile = create_with_fallback(factory, selected_profile)
        self.face_tracker = SimpleTracker()
        self.person_tracker = SimpleTracker()
        self.store = EmbeddingStore(self.output_dir)
        self.analysis_run_id = ""
        self._crops_saved_this_analysis = 0
        self._observation_sequence = 0
        self._staged_embeddings: list[StagedEmbedding] = []
        self._staging_diagnostics: list[dict[str, Any]] = []

    def reset_trackers(self) -> None:
        self.face_tracker = SimpleTracker()
        self.person_tracker = SimpleTracker()

    def begin_analysis(self, analysis_run_id: str) -> str:
        if not analysis_run_id:
            raise CVError("Analysis run ID is required")
        self.analysis_run_id = analysis_run_id
        self._observation_sequence = 0
        self._staged_embeddings = []
        self._staging_diagnostics = []
        return analysis_run_id

    def staged_embeddings(self) -> list[StagedEmbedding]:
        return list(self._staged_embeddings)

    def staging_summary(self) -> dict[str, Any]:
        return {
            "staged_count": len(self._staged_embeddings),
            "diagnostics": [dict(item) for item in self._staging_diagnostics],
        }

    def finalize_staged_embeddings(self, frames: Sequence[Any]) -> list[StagedEmbedding]:
        retained: set[str] = set()
        for frame in frames:
            faces = frame.get("faces", []) if isinstance(frame, dict) else getattr(frame, "faces", [])
            for face in faces or []:
                observation_id = (
                    face.get("observation_id")
                    if isinstance(face, dict)
                    else getattr(face, "observation_id", None)
                )
                if observation_id:
                    retained.add(str(observation_id))
        before = len(self._staged_embeddings)
        self._staged_embeddings = [
            entry
            for entry in self._staged_embeddings
            if str(entry.record.get("observation_id") or "") in retained
        ]
        dropped = before - len(self._staged_embeddings)
        if dropped:
            self._staging_diagnostics.append(
                {
                    "stage": "retained_observations",
                    "reason": "dropped_observations_excluded",
                    "count": dropped,
                }
            )
        return list(self._staged_embeddings)

    def _stage_embedding(
        self,
        *,
        vector: Sequence[float] | np.ndarray,
        observation_id: str,
        cv_run_id: str,
        analysis_run_id: str,
        case_id: str,
        video_id: str,
        sample_id: str,
        frame_number: int,
        timestamp: float,
        track_id: int | None,
        crop_path: str,
        quality_score: float,
        synthetic_label: str,
        detector_confidence: float,
        provenance: dict[str, Any],
    ) -> str:
        if not cv_run_id:
            self._staging_diagnostics.append(
                {
                    "stage": "v4_staging",
                    "reason": "missing_cv_run_id",
                    "observation_id": observation_id,
                }
            )
            return "stage_rejected_missing_cv_run_id"
        if any(
            str(entry.record.get("observation_id") or "") == observation_id
            for entry in self._staged_embeddings
        ):
            self._staging_diagnostics.append(
                {
                    "stage": "v4_staging",
                    "reason": "duplicate_observation_id",
                    "observation_id": observation_id,
                }
            )
            return "stage_rejected_duplicate_observation"
        try:
            staged = build_v4_embedding_record(
                embedding_id=uuid.uuid4().hex,
                observation_id=observation_id,
                cv_run_id=cv_run_id,
                analysis_run_id=analysis_run_id,
                case_id=case_id,
                video_id=video_id,
                source_id=video_id,
                sample_id=sample_id,
                vector=vector,
                model_key=str(provenance["model_key"]),
                provenance_status=str(provenance["provenance_status"]),
                model_sha256=str(provenance["model_sha256"]),
                generated_at=str(provenance["generated_at"]),
                metadata={
                    "frame_number": int(frame_number),
                    "timestamp": round(float(timestamp), 4),
                    "track_id": track_id,
                    "crop_path": crop_path,
                    "quality_score": quality_score,
                    "synthetic_label": synthetic_label,
                    "detector_confidence": detector_confidence,
                    "pipeline_version": provenance.get("pipeline_version"),
                    "model_filename": provenance.get("model_filename"),
                    "model_source_url": provenance.get("model_source_url"),
                    "runtime": provenance.get("runtime"),
                    "opencv_version": provenance.get("opencv_version"),
                },
            )
        except (CVError, TypeError, ValueError) as exc:
            self._staging_diagnostics.append(
                {
                    "stage": "v4_staging",
                    "reason": "invalid_record",
                    "observation_id": observation_id,
                    "detail": str(exc),
                }
            )
            return "stage_rejected_invalid_v4"
        self._staged_embeddings.append(staged)
        return "staged_v4_candidate"

    def _new_observation_id(
        self,
        analysis_run_id: str,
        case_id: str,
        source_id: str,
        frame_number: int,
        face: FaceDetection,
    ) -> str:
        self._observation_sequence += 1
        material = (
            f"{analysis_run_id}:{case_id}:{source_id}:{int(frame_number)}:"
            f"{int(face.track_id or 0)}:{self._observation_sequence}"
        )
        return uuid.uuid5(uuid.NAMESPACE_URL, material).hex

    @property
    def runtime(self) -> dict[str, Any]:
        models: dict[str, Any] = {}
        face_profile = getattr(self.face_detector, "profile", None)
        person_profile = getattr(self.person_detector, "profile", None)
        if face_profile is not None:
            models["yunet"] = self._observed_runtime(face_profile)
        if self.embedder_profile:
            models["sface"] = self._observed_runtime(self.embedder_profile)
        if person_profile is not None:
            models["yolox"] = self._observed_runtime(person_profile)
        return {
            "models": models,
            "configured": configured_model_runtime(CV_BACKEND, CV_TARGET),
        }

    @staticmethod
    def _observed_runtime(profile: RuntimeProfile) -> dict[str, Any]:
        return {
            **profile.to_dict(),
            "observed": True,
            "verification_state": "observed_from_instantiated_model",
            "fallback_observed": bool(profile.fallback),
        }

    def analyze_frame(
        self,
        frame: np.ndarray,
        frame_number: int = 0,
        timestamp: float = 0.0,
        case_id: str = "default",
        source_id: str = "clip",
        save_crops: bool = False,
        add_to_index: bool = False,
        label: str = "unlabelled",
        run_id: str = "",
        cv_run_id: str = "",
        video_id: str = "",
        retain_observations: bool = True,
    ) -> FrameAnalysis:
        started = time.perf_counter()
        if frame is None or frame.size == 0:
            raise CVError("Cannot analyze an empty frame")

        analysis_run_id = run_id or self.analysis_run_id or uuid.uuid4().hex
        if analysis_run_id != self.analysis_run_id:
            self.begin_analysis(analysis_run_id)

        face_detections = self.face_detector.detect(frame) if self.face_detector else []
        person_detections = self.person_detector.detect(frame) if self.person_detector else []
        if len(face_detections) > CV_MAX_FACE_DETECTIONS_PER_FRAME:
            raise CVError(
                f"Frame face detection budget exceeded: configured maximum of {CV_MAX_FACE_DETECTIONS_PER_FRAME}"
            )
        if len(person_detections) > CV_MAX_PERSON_DETECTIONS_PER_FRAME:
            raise CVError(
                f"Frame person detection budget exceeded: configured maximum of {CV_MAX_PERSON_DETECTIONS_PER_FRAME}"
            )
        faces = self.face_tracker.update(face_detections, frame_number, timestamp)
        persons = self.person_tracker.update(person_detections, frame_number, timestamp)

        face_candidates: list[tuple[dict[str, Any], FaceDetection]] = []
        crop_failures = 0
        compute_embeddings = bool(self.embedder) and (retain_observations or add_to_index)
        for face in faces:
            record = self._build_face_record(
                frame=frame,
                face=face,
                frame_number=frame_number,
                timestamp=timestamp,
                case_id=case_id,
                source_id=source_id,
                add_to_index=add_to_index,
                label=label,
                run_id=analysis_run_id,
                cv_run_id=cv_run_id,
                video_id=video_id,
                compute_embedding=compute_embeddings,
            )
            if record and record.get("crop_failure"):
                crop_failures += 1
                continue
            if record:
                face_candidates.append((record, face))

        quality_total = 0.0
        quality_count = 0
        flag_counts: dict[str, int] = {}
        for record, _ in face_candidates:
            quality = record.get("quality") or {}
            score = quality.get("quality_score")
            if score is not None:
                quality_total += float(score)
                quality_count += 1
            for name, enabled in (record.get("flags") or {}).items():
                if enabled is True:
                    flag_counts[name] = flag_counts.get(name, 0) + 1

        person_records: list[dict[str, Any]] = [
            {
                "track_id": person.track_id,
                "bbox": [round(float(value), 2) for value in person.bbox],
                "confidence": round(person.confidence, 4),
                "class_id": person.class_id,
                "class_label": "person",
            }
            for person in persons
        ]

        retained_faces: list[dict[str, Any]] = []
        retained_persons: list[dict[str, Any]] = []
        face_dropped = 0
        person_dropped = 0
        if retain_observations:
            face_candidates.sort(key=lambda item: self._face_priority(item[0]))
            for record, face in face_candidates[:CV_MAX_FACE_OBSERVATIONS_PER_FRAME]:
                self._save_crop_for_record(
                    record,
                    face,
                    frame,
                    case_id=case_id,
                    source_id=source_id,
                    frame_number=frame_number,
                    save_crops=save_crops,
                )
                retained_faces.append(record)
            face_dropped = len(face_candidates) - len(retained_faces)
            person_records.sort(key=self._person_priority)
            retained_persons = person_records[:CV_MAX_PERSON_OBSERVATIONS_PER_FRAME]
            person_dropped = len(person_records) - len(retained_persons)

        crop_unavailable = 0
        if save_crops:
            crop_unavailable = sum(
                1
                for record in retained_faces
                if record.get("crop_state") in {"failed", "limit_reached"}
            )
        truncation = {
            "face_observations_dropped_by_frame": face_dropped,
            "person_observations_dropped_by_frame": person_dropped,
            "face_observations_dropped_by_crop_failure": crop_failures,
            "face_observations_with_unavailable_crops": crop_unavailable,
        }
        if not retain_observations:
            truncation["details_omitted_by_summary_only"] = 1
        return FrameAnalysis(
            frame_number=int(frame_number),
            timestamp=round(float(timestamp), 4),
            faces=retained_faces,
            persons=retained_persons,
            counts={"faces": len(retained_faces), "persons": len(retained_persons)},
            total_counts={"faces": len(faces), "persons": len(persons)},
            truncated=bool(face_dropped or person_dropped or crop_failures or crop_unavailable or not retain_observations),
            truncation=truncation,
            quality_total=round(quality_total, 2),
            quality_count=quality_count,
            flag_counts=flag_counts,
            face_track_ids=[int(face.track_id) for face in faces if face.track_id is not None],
            person_track_ids=[int(person.track_id) for person in persons if person.track_id is not None],
            duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )

    @staticmethod
    def _face_priority(record: dict[str, Any]) -> tuple[float, str]:
        quality = (record.get("quality") or {}).get("quality_score", 0.0)
        return (-float(quality or 0.0), str(record.get("sample_id", "")))

    @staticmethod
    def _person_priority(record: dict[str, Any]) -> tuple[float, int, tuple[float, ...]]:
        bbox = tuple(float(value) for value in record.get("bbox", ()))
        return (-float(record.get("confidence", 0.0)), int(record.get("track_id") or 0), bbox)

    def _save_crop_for_record(
        self,
        record: dict[str, Any],
        face: FaceDetection,
        frame: np.ndarray,
        *,
        case_id: str,
        source_id: str,
        frame_number: int,
        save_crops: bool,
    ) -> None:
        if not save_crops:
            return
        if self._crops_saved_this_analysis >= CV_MAX_CROPS_PER_ANALYSIS:
            record["crop_state"] = "limit_reached"
            return
        try:
            crop, _, _ = crop_face(frame, face)
        except CVError:
            record["crop_state"] = "failed"
            return
        destination = (
            self.crop_dir
            / safe_segment(case_id)
            / safe_segment(source_id)
            / f"frame_{frame_number:06d}"
            / f"{record['sample_id']}.jpg"
        )
        try:
            save_crop(crop, destination)
        except (CVError, OSError):
            record["crop_state"] = "failed"
            return
        self._crops_saved_this_analysis += 1
        record["crop_path"] = relative_to_data(destination)
        record["crop_state"] = "saved"
        prune_crops(self.crop_dir, CV_MAX_CROP_FILES)

    def _embedding_provenance(self, run_id: str) -> dict[str, Any]:
        spec = MODEL_SPECS["sface"]
        profile = self.embedder_profile or RuntimeProfile.from_names(CV_BACKEND, CV_TARGET)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": "cv-phase1-remediated",
            "analysis_run_id": run_id,
            "model_key": "sface",
            "model_filename": spec.filename,
            "model_sha256": spec.sha256,
            "model_source_url": spec.source_url,
            "runtime": profile.to_dict(),
            "opencv_version": cv2.__version__,
            "embedding_schema_version": EMBEDDING_SCHEMA_VERSION,
            "provenance_status": "known",
        }

    def _build_face_record(
        self,
        frame: np.ndarray,
        face: FaceDetection,
        frame_number: int,
        timestamp: float,
        case_id: str,
        source_id: str,
        add_to_index: bool,
        label: str,
        run_id: str,
        cv_run_id: str = "",
        video_id: str = "",
        compute_embedding: bool = True,
    ) -> dict[str, Any] | None:
        from .quality import analyze_face_quality

        try:
            crop, local_landmarks, crop_box = crop_face(frame, face)
        except CVError as exc:
            return {"crop_state": "failed", "crop_failure": str(exc)}

        quality = analyze_face_quality(crop, local_landmarks, face.bbox)
        sample_id = face_sample_id(source_id, frame_number, int(face.track_id or 0))
        observation_id = self._new_observation_id(
            run_id,
            case_id,
            source_id,
            frame_number,
            face,
        )
        crop_path = ""
        crop_state = "disabled"

        embedding: list[float] | None = None
        embedding_state = "disabled"
        if self.embedder and compute_embedding and quality["quality_score"] >= CV_MIN_EMBED_QUALITY:
            try:
                aligned = self.embedder.alignCrop(frame, np.asarray(face.landmarks, dtype=np.float32))
                feature = self.embedder.feature(aligned)
                vector = np.asarray(feature, dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(vector))
                if np.isfinite(norm) and norm > 1e-12:
                    vector = vector / norm
                    embedding = [round(float(value), 6) for value in vector]
                    embedding_state = "computed"
                else:
                    embedding_state = "failed"
            except cv2.error:
                embedding_state = "failed"

        record = {
            "sample_id": sample_id,
            "observation_id": observation_id,
            "analysis_run_id": run_id,
            "track_id": face.track_id,
            "frame_number": int(frame_number),
            "timestamp": round(float(timestamp), 4),
            "bbox": [round(float(value), 2) for value in face.bbox],
            "detector_confidence": round(face.confidence, 4),
            "landmarks": [[round(float(x), 2), round(float(y), 2)] for x, y in face.landmarks],
            "crop_box": [round(float(value), 2) for value in crop_box],
            "crop_signature": crop_signature(crop),
            "crop_path": crop_path,
            "crop_state": crop_state,
            "quality": quality,
            "pose": quality["pose"],
            "flags": quality["flags"],
            "embedding_dim": len(embedding) if embedding else 0,
            "embedding_state": embedding_state,
            "synthetic_label": safe_segment(label),
            "verification_status": "candidate_only",
        }
        if embedding is not None:
            record["embedding"] = embedding
            if add_to_index:
                embedding_state = self._stage_embedding(
                    vector=np.asarray(embedding, dtype=np.float32),
                    observation_id=observation_id,
                    cv_run_id=cv_run_id,
                    analysis_run_id=run_id,
                    case_id=case_id,
                    video_id=video_id or source_id,
                    sample_id=sample_id,
                    frame_number=frame_number,
                    timestamp=timestamp,
                    track_id=face.track_id,
                    crop_path=crop_path,
                    quality_score=quality["quality_score"],
                    synthetic_label=safe_segment(label),
                    detector_confidence=round(face.confidence, 4),
                    provenance=self._embedding_provenance(run_id),
                )
                record["embedding_state"] = embedding_state
        return record

    def _apply_analysis_caps(
        self, frames: list[FrameAnalysis]
    ) -> tuple[list[FrameAnalysis], dict[str, int]]:
        face_entries: list[tuple[int, int, tuple[float, str]]] = []
        person_entries: list[tuple[int, int, tuple[float, int, tuple[float, ...]]]] = []
        for frame_index, frame in enumerate(frames):
            for record_index, record in enumerate(frame.faces):
                face_entries.append((frame_index, record_index, self._face_priority(record)))
            for record_index, record in enumerate(frame.persons):
                person_entries.append((frame_index, record_index, self._person_priority(record)))
        face_entries.sort(key=lambda entry: entry[2])
        person_entries.sort(key=lambda entry: entry[2])
        allowed_faces: set[tuple[int, int]] = set()
        kept_face_records: list[dict[str, Any]] = []
        near_duplicate_faces = 0
        for frame_index, record_index, _ in face_entries[:CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS]:
            record = frames[frame_index].faces[record_index]
            signature = str(record.get("crop_signature") or "")
            duplicate = False
            if signature and record.get("track_id") is not None:
                for kept in kept_face_records:
                    if kept.get("track_id") != record.get("track_id"):
                        continue
                    frame_gap = abs(int(record.get("frame_number", 0)) - int(kept.get("frame_number", 0)))
                    if frame_gap > NEAR_DUPLICATE_MAX_FRAME_GAP:
                        continue
                    kept_signature = str(kept.get("crop_signature") or "")
                    if _hamming_distance(signature, kept_signature) <= NEAR_DUPLICATE_HAMMING_DISTANCE:
                        duplicate = True
                        break
            if duplicate:
                near_duplicate_faces += 1
                record["duplicate_state"] = "suppressed"
                continue
            allowed_faces.add((frame_index, record_index))
            kept_face_records.append(record)
        allowed_persons = {
            (frame_index, record_index)
            for frame_index, record_index, _ in person_entries[:CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS]
        }
        dropped_faces = 0
        dropped_persons = 0
        for frame_index, frame in enumerate(frames):
            before_faces = len(frame.faces)
            before_persons = len(frame.persons)
            frame.faces = [
                record
                for record_index, record in enumerate(frame.faces)
                if (frame_index, record_index) in allowed_faces
            ]
            frame.persons = [
                record
                for record_index, record in enumerate(frame.persons)
                if (frame_index, record_index) in allowed_persons
            ]
            frame_dropped_faces = before_faces - len(frame.faces)
            frame_dropped_persons = before_persons - len(frame.persons)
            dropped_faces += frame_dropped_faces
            dropped_persons += frame_dropped_persons
            frame.truncation["face_observations_dropped_by_analysis"] = frame_dropped_faces
            frame.truncation["person_observations_dropped_by_analysis"] = frame_dropped_persons
            frame.counts = {"faces": len(frame.faces), "persons": len(frame.persons)}
            frame.truncated = frame.truncated or bool(frame_dropped_faces or frame_dropped_persons)
        return frames, {
            "face_observations_dropped_by_analysis": dropped_faces,
            "person_observations_dropped_by_analysis": dropped_persons,
            "near_duplicate_faces_suppressed": near_duplicate_faces,
        }

    def analyze_video(
        self,
        video_path: str | Path,
        case_id: str = "default",
        source_id: str | None = None,
        max_frames: int | None = None,
        frame_stride: int = 1,
        save_crops: bool = False,
        add_to_index: bool = False,
        labels: Sequence[str] | dict[int, str] | None = None,
        progress_callback: ProgressCallback | None = None,
        run_id: str | None = None,
        cv_run_id: str = "",
        video_id: str = "",
        retain_observations: bool = True,
    ) -> VideoAnalysis:
        path = Path(video_path)
        if not path.exists() or not path.is_file():
            raise CVError("Video source is unavailable")
        source = safe_segment(source_id or path.stem)
        selected_max = int(max_frames or CV_MAX_FRAMES)
        if selected_max > CV_MAX_FRAMES:
            raise CVError(f"Frame limit exceeds configured maximum of {CV_MAX_FRAMES}")
        stride = max(1, int(frame_stride))
        if stride > CV_MAX_FRAME_STRIDE:
            raise CVError(f"Frame stride exceeds configured maximum of {CV_MAX_FRAME_STRIDE}")
        if selected_max * stride > CV_MAX_DECODED_FRAMES:
            raise CVError(f"Requested frame budget exceeds configured maximum of {CV_MAX_DECODED_FRAMES}")
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise CVError("Could not open video source")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            fps = 1.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        planned_frames = min(selected_max, frame_count or selected_max)
        planned_duration = planned_frames / fps
        if planned_duration > CV_MAX_CLIP_DURATION_SECONDS:
            capture.release()
            raise CVError(
                f"Requested clip duration exceeds configured maximum of {CV_MAX_CLIP_DURATION_SECONDS} seconds"
            )
        analysis_run_id = self.begin_analysis(run_id or uuid.uuid4().hex)
        self._crops_saved_this_analysis = 0
        try:
            source_label = relative_to_data(path)
        except ValueError:
            source_label = path.name
        frames: list[FrameAnalysis] = []
        face_tracks: set[int] = set()
        person_tracks: set[int] = set()
        quality_total = 0.0
        quality_count = 0
        flag_counts: dict[str, int] = {}
        analyzed = 0
        frame_index = 0
        processed_faces = 0
        processed_persons = 0
        processing_ms_total = 0.0

        try:
            while analyzed < selected_max:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % stride == 0:
                    if isinstance(labels, dict):
                        label = labels.get(frame_index, "unlabelled")
                    elif labels is not None and frame_index < len(labels):
                        label = labels[frame_index]
                    else:
                        label = "unlabelled"
                    analysis = self.analyze_frame(
                        frame=frame,
                        frame_number=frame_index,
                        timestamp=frame_index / fps,
                        case_id=case_id,
                        source_id=source,
                        save_crops=save_crops,
                        add_to_index=add_to_index,
                        label=str(label),
                        run_id=analysis_run_id,
                        cv_run_id=cv_run_id,
                        video_id=video_id or source,
                        retain_observations=retain_observations,
                    )
                    processed_faces += int(analysis.total_counts.get("faces", 0))
                    processed_persons += int(analysis.total_counts.get("persons", 0))
                    if processed_faces > CV_MAX_FACE_DETECTIONS_PER_ANALYSIS:
                        raise CVError(
                            "Analysis face detection budget exceeded: configured maximum of "
                            f"{CV_MAX_FACE_DETECTIONS_PER_ANALYSIS}"
                        )
                    if processed_persons > CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS:
                        raise CVError(
                            "Analysis person detection budget exceeded: configured maximum of "
                            f"{CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS}"
                        )
                    analyzed += 1
                    processing_ms_total += float(analysis.duration_ms)
                    face_tracks.update(analysis.face_track_ids)
                    person_tracks.update(analysis.person_track_ids)
                    quality_total += float(analysis.quality_total)
                    quality_count += int(analysis.quality_count)
                    for name, count in analysis.flag_counts.items():
                        flag_counts[name] = flag_counts.get(name, 0) + int(count)
                    if retain_observations:
                        frames.append(analysis)
                    if progress_callback:
                        progress_callback(analyzed, selected_max)
                frame_index += 1
        finally:
            capture.release()

        global_truncation = {
            "face_observations_dropped_by_analysis": 0,
            "person_observations_dropped_by_analysis": 0,
        }
        if retain_observations:
            frames, global_truncation = self._apply_analysis_caps(frames)
        self.finalize_staged_embeddings(frames)
        retained_faces = sum(frame.counts.get("faces", 0) for frame in frames)
        retained_persons = sum(frame.counts.get("persons", 0) for frame in frames)
        frame_dropped_faces = sum(frame.truncation.get("face_observations_dropped_by_frame", 0) for frame in frames)
        frame_dropped_persons = sum(frame.truncation.get("person_observations_dropped_by_frame", 0) for frame in frames)
        crop_failures = sum(frame.truncation.get("face_observations_dropped_by_crop_failure", 0) for frame in frames)
        crop_unavailable = sum(frame.truncation.get("face_observations_with_unavailable_crops", 0) for frame in frames)
        near_duplicate_faces = int(global_truncation.get("near_duplicate_faces_suppressed", 0))
        summary = {
            "face_detections": processed_faces,
            "person_detections": processed_persons,
            "retained_face_observations": retained_faces,
            "retained_person_observations": retained_persons,
            "truncated_observations": (processed_faces - retained_faces) + (processed_persons - retained_persons),
            "near_duplicate_faces_suppressed": near_duplicate_faces,
            "crops_unavailable": crop_unavailable,
            "unique_face_tracks": len(face_tracks),
            "unique_person_tracks": len(person_tracks),
            "average_face_quality": round(quality_total / quality_count, 2) if quality_count else 0.0,
            "flag_counts": flag_counts,
            "total_processing_ms": round(processing_ms_total, 2),
            "average_frame_ms": round(processing_ms_total / analyzed, 2) if analyzed else 0.0,
            "estimated_fps": round(1000.0 * analyzed / processing_ms_total, 3) if processing_ms_total > 0 else 0.0,
        }
        truncation = {
            **global_truncation,
            "face_observations_dropped_by_frame": frame_dropped_faces,
            "person_observations_dropped_by_frame": frame_dropped_persons,
            "face_observations_dropped_by_crop_failure": crop_failures,
            "face_observations_with_unavailable_crops": crop_unavailable,
            "details_omitted_by_summary_only": not retain_observations,
        }
        return VideoAnalysis(
            source=source_label,
            source_id=source,
            fps=fps,
            frame_count=frame_count,
            analyzed_frame_count=analyzed,
            analysis_run_id=analysis_run_id,
            frames=frames,
            summary=summary,
            truncation=truncation,
            runtime={**self.runtime, "embedding_staging": self.staging_summary()},
        )

    def rank_faces(self, analysis: VideoAnalysis, case_id: str, top_k: int = 5) -> dict[str, Any]:
        candidates: dict[str, Any] = {}
        query_source_id = analysis.source_id
        for frame in analysis.frames:
            for face in frame.faces:
                vector = face.get("embedding")
                if not vector:
                    continue
                candidates[face["sample_id"]] = self.store.search(
                    np.asarray(vector, dtype=np.float32),
                    case_id=case_id,
                    top_k=top_k,
                    exclude_sample_id=face["sample_id"],
                    exclude_source_id=query_source_id,
                )
        return {
            "candidates": candidates,
            "disclaimer": "Ranked candidate retrieval only; no identity confirmation is made.",
        }


__all__ = ["CVPipeline"]
