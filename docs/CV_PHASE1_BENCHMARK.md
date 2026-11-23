# ATM Sentinel CV Phase 1 Benchmark

Generated: `2026-11-22T11:04:21.414465+00:00`

Synthetic/fictional assets only. This validates pipeline mechanics, not real-world accuracy or identity claims.

## Runtime

- OpenCV: 5.1.0
- yunet: `cpu` / `cpu` (fallback: False)
- sface: `cpu` / `cpu` (fallback: False)
- yolox: `cpu` / `cpu` (fallback: False)
- Person score threshold: `0.1`
- Peak process memory: `363233280` bytes (macOS `ru_maxrss`)
- Candidate records: `180`

## Ranking methodology

- Gallery clips: `subject_a_front, subject_b_front, multi_subject, challenges`
- Query clips: `subject_a_side`
- Hard negatives: `subject_b_front, challenges`
- Gallery hard-negative samples: `80`
- Expected query samples: `30`
- Ranked query samples: `17`
- Hard-negative queries evaluated: `17`
- Query-clip embeddings are excluded; the index is isolated for each benchmark run.
- Cross-pose synthetic smoke test only; not a real-world accuracy estimate.
- Ranking evidence artifact: `data/cv/benchmark_ranking_evidence.json` (85 rows).

## Timing terminology

Frame timings are single-pass synthetic smoke timings from one run, not a repeated benchmark with variance estimates.

## Models

| Model | File | License | Verification | SHA256 |
| --- | --- | --- | --- | --- |
| yunet | `face_detection_yunet_2026may.onnx` | MIT weights; OpenCV Zoo Apache-2.0 repository | verified | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` |
| sface | `face_recognition_sface_2021dec.onnx` | Apache-2.0 | verified | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |
| yolox | `object_detection_yolox_2022nov.onnx` | Apache-2.0 | verified | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |

## Synthetic clips

| Clip | Face frames | Expected | Person detections | Single-pass avg frame ms | Single-pass est. FPS | Cross-pose Rank@1 | Hard negatives in top 5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| subject_a_front | 40 | 40 | 9 | 102.7 | 9.737 | — | — |
| subject_a_side | 17 | 30 | 0 | 95.83 | 10.435 | 17/17 (1.0) | 0 |
| subject_b_front | 40 | 40 | 0 | 104.16 | 9.6 | — | — |
| multi_subject | 35 | 35 | 0 | 118.28 | 8.455 | — | — |
| challenges | 30 | 40 | 17 | 105.41 | 9.487 | — | — |
| no_face | 0 | 0 | 0 | 100.09 | 9.991 | — | — |

## Interpretation

- Face detection, tracking, quality scoring, pose proxies and candidate embeddings ran end-to-end.
- Person detection was demonstrated only with a lower threshold; procedural silhouettes are not photorealistic.
- Ranking uses a query-clip-excluded isolated gallery; labels are applied only after ranking.
- Rank@1 is a small synthetic cross-pose smoke test result and is not real-world accuracy.
- Hard negatives returned in evaluated top-k: `0`.
- Zero returned hard negatives does not establish hard-negative discrimination.
- Synthetic hard-negative clips are procedural and cannot support a real-world discrimination claim.
- Ranking results compare synthetic labels across clips and are not identity verification.
- Challenge-clip flags are heuristic review signals, not mask/helmet/cap classifiers.

## Limitations

Face-crop quality combines Laplacian variance, mean intensity, contrast, crop size, five-landmark visibility and geometric pose proxies. Occlusion is a review flag, not a mask/helmet/cap classifier. Scores measure crop usability only and are not probabilities of identity or correctness.

Synthetic pipeline-functionality benchmark only. Candidate rankings are not identity confirmations and do not establish real-world accuracy.

Historical reproduction required the Phase 1 synthetic-asset and benchmark scripts. Those scripts were not invoked by the acceptance run; see `reports/acceptance/acceptance.md` for the current isolated synthetic scenario.
