# TASK 18 — Face Embedding & Cross-Clip Retrieval Benchmark

## Scope / boundaries
- Existing local **SFace** model only (`face_recognition_sface_2021dec.onnx`, verified local). No new models/downloads/installs.
- Authorized synthetic clips only (`data/datasets/synthetic/cv` manifest labels: SYN-A/B/C). No real CCTV, no real people, no identity inferred from visual similarity.
- Isolated experiment/benchmark; **no production matching/threshold/model/DB/schema changes**. No protected data modifications.

## 1) Dataset audit
Source: `data/datasets/synthetic/cv/manifest.json` + YuNet face detection on labeled frames; SFace `alignCrop+feature` embeddings.

| Metric | Value |
|---|---:|
| Samples (usable, labeled, single-detection, embedded) | 127 |
| Unique subjects | 3 (`SYN-A`, `SYN-B`, `SYN-C`) |
| Clips with samples | 4 (`subject_a_front`, `subject_a_side`, `subject_b_front`, `challenges`) |
| Ambiguous/no-label frames excluded | 15 / 36 (per audit) |
| Multi-detection single-label frames excluded | recorded in audit exclusions |

Pair support:
- **All pairs**: 8001 (genuine 2811, impostor 5190).
- **Cross-clip pairs**: 5870 (genuine 680, impostor 5190). Genuine cross-clip pairs are only SYN-A (`subject_a_front` ↔ `subject_a_side`) — limited subject diversity.

**Limitation**: small subject count and synthetic-only labels limit generality; ROC/AUC/thresholds are exploratory, not production/real-CCTV evidence.

## 2) Existing SFace benchmark (original, unenhanced crops/frames)
Cosine similarity (normalized SFace vectors, -1..1; higher = more similar, **not identity**):

| Set | Genuine mean±std (n) | Impostor mean±std (n) |
|---|---:|---:|
| All pairs | 0.9403±0.0387 (2811) | 0.8373±0.0429 (5190) |
| Cross-clip | 0.9296±0.0190 (680) | 0.8373±0.0429 (5190) |

Retrieval (excludes query self; relevant = same manifest subject label):

| Mode | Status | Assessed queries | Rank-1 | Rank-5 | MRR |
|---|---|---:|---:|---:|---:|
| Including same clip | MEASURED | 127 | 1.000 | 1.000 | 1.000 |
| Source clip excluded (cross-clip) | MEASURED | 57 | 1.000 | 1.000 | 1.000 |

ROC/AUC (meaningful-report caveat: only 3 subjects; exploratory):

| Set | Status | AUC | EER proxy (thr/TAR/FAR/gap) | TAR@FAR 0.01 | TAR@FAR 0.05 | TAR@FAR 0.1 |
|---|---|---:|---|---:|---:|---:|
| All pairs | MEASURED | 0.9548 | 0.8896 / 0.8993 / 0.1008 / 0.000095 | 0.8175 @FAR0.0098 (thr0.9127) | 0.8726 @FAR0.0499 (thr0.8984) | 0.8983 @FAR0.0971 (thr0.8902) |
| Cross-clip | MEASURED | 0.9891 | 0.8964 / 0.9426 / 0.0580 / 0.000643 | 0.8426 @FAR0.0098 (thr0.9127) | 0.9294 @FAR0.0497 (thr0.8984) | 0.9838 @FAR0.0971 (thr0.8902) |

Condition breakdown (where labels support): by face size/blur/illumination computed in JSON; pose **NOT_ASSESSABLE** (no reliable per-sample pose labels in manifest; not inferred visually).

## 3) Robustness (controlled in-memory degradations)
Method caveat: degraded variants embedded via `SFace.feature` on resized 112x112 crop **proxy** (not full-frame `alignCrop` production path). Original retrieval uses `alignCrop` on original frames. Absolute proxy rank-1 is low due method mismatch; **interpret as sensitivity signal only**, not production retrieval accuracy.

| Variant | n | Proxy rank-1 cross-clip | Assessed | Mean cosine to original | Min cosine to original |
|---|---:|---:|---:|---:|---:|
| original (proxy) | 80 | 0.175 | 80 | 1.0000 | 1.0000 |
| blur | 80 | 0.213 | 80 | 0.6206 | 0.6028 |
| downscale | 80 | 0.213 | 80 | 0.7392 | 0.6976 |
| low_light | 80 | 0.213 | 80 | 0.9011 | 0.8828 |
| low_contrast | 80 | 0.213 | 80 | 0.8968 | 0.8074 |
| moderate_noise | 80 | 0.200 | 80 | 0.6103 | 0.5924 |

Observation: cosine-to-original drops most for blur/noise/downscale; proxy rank-1 is unstable/unreliable for comparison because original proxy baseline is 0.175. **No claim that enhancement/restoration reveals genuine identity detail.** TASK 15 enhanced outputs were not used as matching inputs.

## 4) Threshold analysis (offline only)
- Production behavior observed: **no explicit cosine acceptance threshold** in candidate search; it ranks by cosine and returns top_k (`backend/app/services/cv_integration.py` search path). Reporting baseline 0.0 used only for analysis table.
- Offline best-balanced (all pairs, min FAR+missed-match): threshold **0.90**, TAR 0.8684, FAR 0.0441, missed-match 0.1316, TP 2441, FP 229, TN 4961, FN 370.
- **No production threshold/model change recommended.** Evidence is synthetic-only, 3 subjects, limited genuine cross-clip diversity; offline threshold would risk overfitting and false confidence.

## 5) Conclusion
- Existing SFace cross-clip retrieval on this controlled synthetic labeled set is strong (Rank-1/MRR 1.0 for assessed queries; AUC 0.989 cross-clip) but **not generalizable** to real CCTV.
- Main limitation is dataset/labels, not measured SFace failure: only 3 synthetic subjects, genuine cross-clip limited to SYN-A.
- Robustness proxy indicates similarity degrades under blur/noise/downscale; method mismatch prevents strong rank conclusions.
- **Recommended next step**: expand labeled cross-clip GT (more subjects, real CCTV only if authorized), keep production unchanged; do not change threshold/model.

## Artifacts
- `backend/app/cv/face_retrieval_experiment.py`
- `backend/tests/test_face_retrieval_experiment.py`
- `scripts/benchmark_face_retrieval.py`
- `reports/ps04cctv-audit/TASK-18-FACE-RETRIEVAL-BENCHMARK.json`
- `reports/ps04cctv-audit/TASK-18-FACE-RETRIEVAL-BENCHMARK.md`
