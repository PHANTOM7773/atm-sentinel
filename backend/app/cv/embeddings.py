from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ..config import CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS, CV_OUTPUT_DIR, ensure_dirs, relative_to_data
from .errors import CVError

EMBEDDING_SCHEMA_VERSION = 4
LEGACY_EMBEDDING_SCHEMA_VERSION = 3
V4_RECORD_FORMAT = "v4"
LEGACY_RECORD_FORMAT = "legacy_v3"
SUPPORTED_MODEL_KEYS = frozenset({"sface"})
V4_ID_FIELDS = (
    "embedding_id",
    "observation_id",
    "cv_run_id",
    "analysis_run_id",
    "case_id",
    "video_id",
    "source_id",
    "sample_id",
)
V4_PROVENANCE_FIELDS = (
    "model_key",
    "provenance_status",
    "model_sha256",
    "generated_at",
)
MAX_V4_PUBLISH_BATCH = max(1, int(CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StagedEmbedding:
    record: dict[str, Any]
    vector: np.ndarray


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float32).reshape(-1)
    if values.size == 0:
        raise CVError("Embedding vector is empty")
    if not np.isfinite(values).all():
        raise CVError("Embedding vector is non-finite")
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise CVError("Embedding vector has zero magnitude")
    return values / norm


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _valid_text(value: Any, field: str, max_length: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise CVError(f"Invalid {field}")
    return value


def _valid_sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CVError("Invalid model provenance")
    return value


def _validate_v4_record(record: Mapping[str, Any], vector: np.ndarray | None = None) -> None:
    if not isinstance(record, Mapping):
        raise CVError("Invalid embedding record")
    if record.get("record_format") != V4_RECORD_FORMAT:
        raise CVError("Invalid embedding record format")
    if record.get("v4_eligible") is not True:
        raise CVError("Embedding record is not v4 eligible")
    try:
        version = int(record.get("embedding_schema_version"))
    except (TypeError, ValueError) as exc:
        raise CVError("Invalid embedding schema version") from exc
    if version != EMBEDDING_SCHEMA_VERSION:
        raise CVError("Invalid embedding schema version")
    for field in V4_ID_FIELDS:
        _valid_text(record.get(field), field)
    for field in V4_PROVENANCE_FIELDS:
        _valid_text(record.get(field), field, 80 if field == "generated_at" else 120)
    if record.get("model_key") not in SUPPORTED_MODEL_KEYS:
        raise CVError("Unsupported embedding model")
    if record.get("provenance_status") != "known":
        raise CVError("Invalid embedding provenance")
    _valid_sha256(record.get("model_sha256"))
    if record.get("verification_status") != "candidate_only":
        raise CVError("Invalid verification status")
    try:
        dimension = int(record.get("embedding_dim"))
    except (TypeError, ValueError) as exc:
        raise CVError("Invalid embedding dimension") from exc
    if dimension <= 0:
        raise CVError("Invalid embedding dimension")
    if vector is not None:
        values = np.asarray(vector, dtype=np.float32).reshape(-1)
        if not np.isfinite(values).all():
            raise CVError("Embedding vector is non-finite")
        if values.size != dimension:
            raise CVError("Embedding dimension mismatch")
        normalize_vector(values)


def build_v4_embedding_record(
    *,
    embedding_id: str,
    observation_id: str,
    cv_run_id: str,
    analysis_run_id: str,
    case_id: str,
    video_id: str,
    source_id: str,
    sample_id: str,
    vector: Sequence[float] | np.ndarray,
    model_key: str,
    provenance_status: str,
    model_sha256: str,
    generated_at: str,
    metadata: Mapping[str, Any] | None = None,
) -> StagedEmbedding:
    normalized = normalize_vector(np.asarray(vector, dtype=np.float32))
    record = dict(metadata or {})
    record.update(
        {
            "embedding_id": embedding_id,
            "observation_id": observation_id,
            "cv_run_id": cv_run_id,
            "analysis_run_id": analysis_run_id,
            "case_id": case_id,
            "video_id": video_id,
            "source_id": source_id,
            "sample_id": sample_id,
            "model_key": model_key,
            "provenance_status": provenance_status,
            "model_sha256": model_sha256,
            "generated_at": generated_at,
            "embedding_schema_version": EMBEDDING_SCHEMA_VERSION,
            "embedding_dim": int(normalized.size),
            "verification_status": "candidate_only",
            "record_format": V4_RECORD_FORMAT,
            "v4_eligible": True,
        }
    )
    _validate_v4_record(record, normalized)
    return StagedEmbedding(record=record, vector=normalized)


def _is_v4_record(record: Mapping[str, Any]) -> bool:
    if record.get("record_format") == V4_RECORD_FORMAT:
        return True
    try:
        return int(record.get("embedding_schema_version") or 0) == EMBEDDING_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def _is_v4_eligible(record: Mapping[str, Any], vector: np.ndarray | None = None) -> bool:
    try:
        _validate_v4_record(record, vector)
    except (CVError, TypeError, ValueError):
        return False
    return True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CVError("Could not read embedding manifest") from exc
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CVError("Embedding manifest is malformed") from exc
    if not isinstance(payload, dict):
        raise CVError("Embedding manifest is malformed")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_vectors_atomic(path: Path, vectors: np.ndarray) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as sink:
        np.save(sink, vectors)
    os.replace(temporary, path)


class EmbeddingStore:
    _lock = threading.RLock()

    def __init__(self, directory: Path | None = None) -> None:
        ensure_dirs()
        self.directory = directory or CV_OUTPUT_DIR
        self.directory.mkdir(parents=True, exist_ok=True)
        self.generation_dir = self.directory / "generations"
        self.manifest_path = self.directory / "manifest.json"
        self.index_path = self.directory / "embeddings.json"
        self.vectors_path = self.directory / "embeddings.npy"
        self.records: list[dict[str, Any]] = []
        self.vectors = np.empty((0, 0), dtype=np.float32)
        self.generation = 0
        self.storage = "empty"
        with self._lock:
            self._load()

    def _relative(self, path: Path) -> str:
        try:
            return relative_to_data(path)
        except ValueError:
            return path.name

    def _load(self) -> None:
        if self.manifest_path.exists():
            manifest = _read_json(self.manifest_path)
            generation = int(manifest.get("generation") or 0)
            active = self.generation_dir / f"{generation:012d}"
            if generation and self._generation_is_valid(active):
                self._load_generation(active)
                return
            for candidate in self._valid_generations():
                self._load_generation(candidate)
                self._save_manifest()
                return
            raise CVError("Embedding storage has no valid generation")
        if self.index_path.exists():
            self._load_legacy()
            return
        self.storage = "empty"

    def _generation_is_valid(self, directory: Path) -> bool:
        if not directory.is_dir():
            return False
        manifest_path = directory / "manifest.json"
        index_path = directory / "embeddings.json"
        vectors_path = directory / "embeddings.npy"
        if not manifest_path.exists() or not index_path.exists() or not vectors_path.exists():
            return False
        try:
            manifest = _read_json(manifest_path)
            index_bytes = index_path.read_bytes()
            vector_bytes = vectors_path.read_bytes()
            if manifest.get("records_sha256") != _sha256_bytes(index_bytes):
                return False
            if manifest.get("vectors_sha256") != _sha256_bytes(vector_bytes):
                return False
            payload = json.loads(index_bytes.decode("utf-8"))
            records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(records, list):
                return False
            vectors = np.asarray(np.load(vectors_path), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(records):
                return False
            if int(manifest.get("record_count") or 0) != len(records):
                return False
            if int(manifest.get("embedding_dim") or 0) != vectors.shape[1]:
                return False
        except (CVError, OSError, ValueError, json.JSONDecodeError, TypeError):
            return False
        return True

    def _valid_generations(self) -> list[Path]:
        if not self.generation_dir.exists():
            return []
        candidates = [path for path in self.generation_dir.iterdir() if path.is_dir() and path.name.isdigit()]
        candidates.sort(key=lambda path: int(path.name), reverse=True)
        return [path for path in candidates if self._generation_is_valid(path)]

    def _load_generation(self, directory: Path) -> None:
        payload = _read_json(directory / "embeddings.json")
        records = payload.get("records", [])
        self.records = [record for record in records if isinstance(record, dict)]
        self._mark_legacy_provenance()
        self.vectors = np.asarray(np.load(directory / "embeddings.npy"), dtype=np.float32)
        self.generation = int(directory.name)
        self.index_path = directory / "embeddings.json"
        self.vectors_path = directory / "embeddings.npy"
        self.storage = "generation"

    def _load_legacy(self) -> None:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CVError("Could not read embedding index") from exc
        records = payload.get("records", []) if isinstance(payload, dict) else []
        if not isinstance(records, list):
            raise CVError("Embedding index is malformed")
        self.records = [record for record in records if isinstance(record, dict)]
        self._mark_legacy_provenance()
        if self.vectors_path.exists():
            try:
                self.vectors = np.asarray(np.load(self.vectors_path), dtype=np.float32)
            except (OSError, ValueError) as exc:
                raise CVError("Could not read embedding vectors") from exc
        else:
            self.vectors = np.empty((0, 0), dtype=np.float32)
        if self.vectors.ndim != 2 or len(self.vectors) != len(self.records):
            raise CVError("Embedding vectors and records are inconsistent")
        self.generation = 0
        self.storage = "legacy"

    def _mark_legacy_provenance(self) -> None:
        for record in self.records:
            if not record.get("provenance_status"):
                record["provenance_status"] = "legacy_unknown"
            if not record.get("model_key"):
                record["model_key"] = "unknown"
            if not record.get("model_sha256"):
                record["model_sha256"] = "unknown"
            if _is_v4_record(record):
                if _is_v4_eligible(record):
                    record["v4_eligible"] = True
                    record.pop("quarantine_reason", None)
                else:
                    record["v4_eligible"] = False
                    record["quarantine_reason"] = "invalid_v4"
            else:
                record["record_format"] = LEGACY_RECORD_FORMAT
                record["v4_eligible"] = False
                record.pop("quarantine_reason", None)

    def _generation_payload(self) -> dict[str, Any]:
        return {
            "version": EMBEDDING_SCHEMA_VERSION,
            "generation": self.generation,
            "disclaimer": "Candidate retrieval only; never an identity confirmation.",
            "records": self.records,
        }

    def _save(self) -> None:
        self.generation += 1
        name = f"{self.generation:012d}"
        final = self.generation_dir / name
        staged = self.generation_dir / f".{name}.tmp"
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        index_path = staged / "embeddings.json"
        vectors_path = staged / "embeddings.npy"
        payload = self._generation_payload()
        index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with vectors_path.open("wb") as sink:
            np.save(sink, self.vectors)
        index_hash = _sha256_bytes(index_path.read_bytes())
        vector_hash = _sha256_bytes(vectors_path.read_bytes())
        generation_manifest = {
            "generation": self.generation,
            "record_count": len(self.records),
            "embedding_dim": int(self.vectors.shape[1]) if self.vectors.ndim == 2 else 0,
            "records_sha256": index_hash,
            "vectors_sha256": vector_hash,
            "disclaimer": "Candidate retrieval only; never an identity confirmation.",
        }
        _write_json_atomic(staged / "manifest.json", generation_manifest)
        if final.exists():
            shutil.rmtree(final)
        staged.replace(final)
        self.index_path = final / "embeddings.json"
        self.vectors_path = final / "embeddings.npy"
        self.storage = "generation"
        self._save_manifest()
        self._prune_generations(keep=3)

    def _save_manifest(self) -> None:
        manifest = {
            "version": EMBEDDING_SCHEMA_VERSION,
            "generation": self.generation,
            "generation_dir": f"generations/{self.generation:012d}",
            "record_count": len(self.records),
            "embedding_dim": int(self.vectors.shape[1]) if self.vectors.ndim == 2 else 0,
            "disclaimer": "Candidate retrieval only; never an identity confirmation.",
        }
        _write_json_atomic(self.manifest_path, manifest)

    def _prune_generations(self, keep: int) -> None:
        candidates = [path for path in self._valid_generations() if path.name != f"{self.generation:012d}"]
        for path in candidates[keep - 1 :]:
            shutil.rmtree(path, ignore_errors=True)

    def _snapshot(self) -> tuple[list[dict[str, Any]], np.ndarray, int, str]:
        with self._lock:
            records = [dict(record) for record in self.records]
            vectors = self.vectors.copy()
            return records, vectors, self.generation, self.storage

    @staticmethod
    def _matches_filters(
        record: Mapping[str, Any],
        case_id: str | None,
        exclude_observation_id: str | None,
        exclude_source_id: str | None,
    ) -> bool:
        if case_id and record.get("case_id") != case_id:
            return False
        source_id = record.get("source_id") or record.get("video_id")
        if exclude_observation_id and str(record.get("observation_id") or "") == exclude_observation_id:
            return False
        if exclude_source_id and source_id == exclude_source_id:
            return False
        return True

    def add(self, sample_id: str, case_id: str, vector: np.ndarray, metadata: dict[str, Any] | None = None) -> str:
        with self._lock:
            return self._add_legacy(sample_id, case_id, vector, metadata)

    def _add_legacy(self, sample_id: str, case_id: str, vector: np.ndarray, metadata: dict[str, Any] | None) -> str:
        normalized = normalize_vector(vector)
        if len(self.vectors) and self.vectors.shape[1] != normalized.size:
            raise CVError(
                f"Embedding dimension mismatch: expected {self.vectors.shape[1]}, got {normalized.size}"
            )
        record = dict(metadata or {})
        record.update(
            {
                "sample_id": str(sample_id),
                "case_id": str(case_id),
                "embedding_dim": int(normalized.size),
                "verification_status": "candidate_only",
                "provenance_status": record.get("provenance_status", "unknown"),
                "embedding_schema_version": LEGACY_EMBEDDING_SCHEMA_VERSION,
                "record_format": LEGACY_RECORD_FORMAT,
                "v4_eligible": False,
            }
        )
        record.pop("quarantine_reason", None)
        for index, existing in enumerate(self.records):
            if _is_v4_record(existing):
                continue
            if existing.get("sample_id") == sample_id:
                self.records[index] = record
                self.vectors[index] = normalized
                self._save()
                return sample_id
        self.records.append(record)
        self.vectors = (
            normalized.reshape(1, -1)
            if not len(self.vectors)
            else np.vstack([self.vectors, normalized.reshape(1, -1)])
        )
        self._save()
        return sample_id

    def search(
        self,
        vector: np.ndarray,
        case_id: str | None = None,
        top_k: int = 5,
        exclude_sample_id: str | None = None,
        exclude_source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        records, vectors, _, _ = self._snapshot()
        if not len(vectors):
            return []
        query = normalize_vector(vector)
        if query.size != vectors.shape[1]:
            raise CVError(
                f"Embedding dimension mismatch: expected {vectors.shape[1]}, got {query.size}"
            )
        scores = vectors @ query
        candidates: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            if case_id and record.get("case_id") != case_id:
                continue
            if exclude_sample_id and record.get("sample_id") == exclude_sample_id:
                continue
            if exclude_source_id and record.get("source_id") == exclude_source_id:
                continue
            candidates.append(
                {
                    "sample_id": str(record.get("sample_id", "")),
                    "case_id": str(record.get("case_id", "")),
                    "cosine_similarity": round(float(scores[index]), 6),
                    "metadata": dict(record),
                    "verification_status": "candidate_only",
                    "v4_eligible": _is_v4_eligible(record, vectors[index]),
                }
            )
        candidates.sort(key=lambda item: item["cosine_similarity"], reverse=True)
        return candidates[: max(0, int(top_k))]

    def iter_ranked_records(
        self,
        vector: np.ndarray,
        *,
        case_id: str | None = None,
        exclude_observation_id: str | None = None,
        exclude_source_id: str | None = None,
        eligible_only: bool = True,
    ) -> Iterator[dict[str, Any]]:
        records, vectors, generation, _ = self._snapshot()
        if not len(vectors):
            return iter(())
        query = normalize_vector(vector)
        if query.size != vectors.shape[1]:
            raise CVError(
                f"Embedding dimension mismatch: expected {vectors.shape[1]}, got {query.size}"
            )
        scores = vectors @ query
        order = np.argsort(-scores, kind="stable")
        ranked: list[dict[str, Any]] = []
        for raw_index in order:
            index = int(raw_index)
            record = records[index]
            eligible = _is_v4_eligible(record, vectors[index])
            if eligible_only and not eligible:
                continue
            if not self._matches_filters(record, case_id, exclude_observation_id, exclude_source_id):
                continue
            ranked.append(
                {
                    "score": float(scores[index]),
                    "cosine_similarity": round(float(scores[index]), 6),
                    "metadata": dict(record),
                    "generation": generation,
                    "v4_eligible": eligible,
                }
            )
        return iter(ranked)

    def find_by_observation_id(
        self,
        observation_id: str,
        *,
        case_id: str | None = None,
        cv_run_id: str | None = None,
        eligible_only: bool = True,
    ) -> dict[str, Any] | None:
        records, vectors, generation, _ = self._snapshot()
        for index, record in enumerate(records):
            if str(record.get("observation_id") or "") != observation_id:
                continue
            if case_id and record.get("case_id") != case_id:
                continue
            if cv_run_id and record.get("cv_run_id") != cv_run_id:
                continue
            eligible = _is_v4_eligible(record, vectors[index] if len(vectors) else None)
            if eligible_only and not eligible:
                continue
            return {
                "metadata": dict(record),
                "vector": vectors[index].copy(),
                "generation": generation,
                "v4_eligible": eligible,
            }
        return None

    def publish_staged_records(self, staged: Sequence[StagedEmbedding]) -> int:
        entries = list(staged)
        if len(entries) > MAX_V4_PUBLISH_BATCH:
            raise CVError("Embedding publish batch exceeds configured limit")
        with self._lock:
            previous = (
                list(self.records),
                self.vectors.copy(),
                self.generation,
                self.storage,
                self.index_path,
                self.vectors_path,
            )
            try:
                self._load()
                seen_embedding_ids = {
                    str(record["embedding_id"])
                    for record in self.records
                    if record.get("embedding_id")
                }
                seen_observation_ids = {
                    str(record["observation_id"])
                    for record in self.records
                    if record.get("observation_id")
                }
                prepared: list[tuple[dict[str, Any], np.ndarray]] = []
                for entry in entries:
                    if not isinstance(entry, StagedEmbedding):
                        raise CVError("Invalid staged embedding")
                    record = dict(entry.record)
                    vector = np.asarray(entry.vector, dtype=np.float32)
                    _validate_v4_record(record, vector)
                    normalized = normalize_vector(vector)
                    embedding_id = str(record["embedding_id"])
                    observation_id = str(record["observation_id"])
                    if embedding_id in seen_embedding_ids:
                        raise CVError("Duplicate embedding ID")
                    if observation_id in seen_observation_ids:
                        raise CVError("Duplicate observation ID")
                    seen_embedding_ids.add(embedding_id)
                    seen_observation_ids.add(observation_id)
                    record["record_format"] = V4_RECORD_FORMAT
                    record["v4_eligible"] = True
                    record["embedding_dim"] = int(normalized.size)
                    record.pop("quarantine_reason", None)
                    prepared.append((record, normalized))
                if not prepared:
                    return 0
                dimension = prepared[0][1].size
                if len(self.vectors) and self.vectors.ndim == 2 and self.vectors.shape[1] != dimension:
                    raise CVError("Embedding dimension mismatch")
                new_vectors = np.vstack([vector for _, vector in prepared])
                self.records = list(self.records) + [record for record, _ in prepared]
                self.vectors = (
                    new_vectors
                    if not len(self.vectors)
                    else np.vstack([self.vectors, new_vectors])
                )
                self._save()
                return len(prepared)
            except CVError:
                (
                    self.records,
                    self.vectors,
                    self.generation,
                    self.storage,
                    self.index_path,
                    self.vectors_path,
                ) = previous
                raise
            except (OSError, TypeError, ValueError) as exc:
                (
                    self.records,
                    self.vectors,
                    self.generation,
                    self.storage,
                    self.index_path,
                    self.vectors_path,
                ) = previous
                raise CVError("Could not publish embeddings") from exc

    def status(self) -> dict[str, Any]:
        records, vectors, generation, storage = self._snapshot()
        known = sum(1 for record in records if record.get("provenance_status") == "known")
        v4_eligible = sum(1 for record in records if _is_v4_eligible(record))
        legacy_v3 = sum(
            1
            for record in records
            if not _is_v4_record(record) or record.get("record_format") == LEGACY_RECORD_FORMAT
        )
        invalid_v4 = sum(
            1
            for record in records
            if _is_v4_record(record) and not _is_v4_eligible(record)
        )
        return {
            "record_count": len(records),
            "embedding_dim": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
            "generation": generation,
            "storage": storage,
            "schema_version": EMBEDDING_SCHEMA_VERSION,
            "consistency": "verified" if storage == "generation" else "legacy_unknown",
            "provenance": {
                "known": known,
                "legacy_unknown": len(records) - known,
            },
            "record_formats": {
                "v4_eligible": v4_eligible,
                "legacy_v3": legacy_v3,
                "invalid_v4": invalid_v4,
            },
            "quarantine": {
                "legacy_v3": legacy_v3,
                "invalid_v4": invalid_v4,
                "total": len(records) - v4_eligible,
            },
            "v4": {
                "eligible": v4_eligible,
                "searchable": v4_eligible,
            },
            "index_path": self._relative(self.index_path),
            "vectors_path": self._relative(self.vectors_path),
            "disclaimer": "Candidate retrieval only; never an identity confirmation.",
        }


__all__ = [
    "EMBEDDING_SCHEMA_VERSION",
    "LEGACY_EMBEDDING_SCHEMA_VERSION",
    "StagedEmbedding",
    "V4_RECORD_FORMAT",
    "build_v4_embedding_record",
    "normalize_vector",
    "EmbeddingStore",
]
