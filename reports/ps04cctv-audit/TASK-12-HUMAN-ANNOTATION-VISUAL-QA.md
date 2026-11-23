# TASK 12 — Human Annotation Visual QA Audit (READ-ONLY)

Generated: 2026-11-23 (local). **READ-ONLY audit; no annotation/production/git changes made.**

## Scope / Inputs (read-only)
- `reports/ps04cctv-audit/annotations/human-annotations.status-fixed.json`
- `reports/ps04cctv-audit/annotations/selected-frames-manifest.json`
- `reports/ps04cctv-audit/annotations/frames/` (48 PNGs)
- `reports/ps04cctv-audit/annotations/qa-report.json`

## Critical limitation (must read)
**A complete visual audit of every frame/box could NOT be performed by this agent in the current environment.** The available image-reading tool returned: `Cannot read image (this model does not support image input)`. I therefore **did not visually inspect** pixel content, face visibility, occlusion, pose, blur, illumination, or bbox tightness/face coverage. 

This report contains:
- **Programmatically verified** checks (JSON/manifest coverage, uniqueness, file existence/readability, dimensions, bbox numeric/in-bounds, counts, label-value distributions).
- **NOT_ASSESSABLE (visual)** for all criteria requiring human/vision inspection.
- **Questionable** flags where metadata patterns warrant manual review (especially uniform default-like labels), without claiming they are incorrect.

No annotation JSON was edited/overwritten. No boxes/labels changed. No production code/DB changed. No deps/models/downloads/prohibited scripts/services/Git operations.

## 1) Coverage & programmatic integrity (verified)

| Check | Result | Status |
|---|---|---|
| Selected frames in manifest | 48 | VERIFIED |
| Frames represented in annotation | 48 unique `(clip_id, frame_index)`; 0 missing; 0 extra; 0 duplicates | VERIFIED |
| Derived frame files present/readable | 48/48 present; OpenCV readable | VERIFIED |
| Frame dimensions vs manifest | 640x480 matches for all audited frames | VERIFIED |
| Total face boxes | 46 | VERIFIED |
| No-face frames | 9 | VERIFIED |
| Annotation status counts | annotated=48, not_annotated=0, needs_review=0 | VERIFIED |
| Bbox numeric validity | all 46 have w>0,h>0 | VERIFIED |
| Bbox within image bounds | 0 out-of-bounds | VERIFIED |
| Validator report | 0 errors, 0 warnings, benchmark_ready=false, qa_status=NOT_REVIEWED | VERIFIED |

## 2) Frame-by-frame QA table (all 48 frames)

Visual columns are NOT_ASSESSABLE due image-input limitation.

| # | clip_id | frame | ts_ms (sel) | img exists | faces | no_face | status | bbox in-bounds | Visual: bbox placement/tightness/covers face | Visual: no-face justified | Visual: condition labels | Overall |
|---:|---|---:|---:|---:|---:|---:|---|---:|---|---|---|---|
|1|subject_a_front|0|0.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|2|subject_a_front|5|500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|3|subject_a_front|10|1000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|4|subject_a_front|15|1500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|5|subject_a_front|20|2000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|6|subject_a_front|25|2500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|7|subject_a_front|30|3000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|8|subject_a_front|39|3900.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|9|subject_a_side|0|0.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|10|subject_a_side|5|500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|11|subject_a_side|10|1000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|12|subject_a_side|15|1500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|13|subject_a_side|20|2000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|14|subject_a_side|29|2900.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|15|subject_b_front|0|0.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|16|subject_b_front|5|500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|17|subject_b_front|10|1000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|18|subject_b_front|15|1500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|19|subject_b_front|20|2000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|20|subject_b_front|25|2500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|21|subject_b_front|30|3000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|22|subject_b_front|39|3900.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|23|multi_subject|0|0.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|24|multi_subject|5|500.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|25|multi_subject|10|1000.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|26|multi_subject|15|1500.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|27|multi_subject|20|2000.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|28|multi_subject|25|2500.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|29|multi_subject|34|3400.0|Y|2|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|30|challenges|0|0.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|31|challenges|5|500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|32|challenges|10|1000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|33|challenges|15|1500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|34|challenges|20|2000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|35|challenges|25|2500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|36|challenges|29|2900.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|37|challenges|30|3000.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|38|challenges|35|3500.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|39|challenges|39|3900.0|Y|1|F|annotated|Y|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE|NOT_ASSESSABLE_VISUAL |
|40|challenges|40|4000.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|41|challenges|45|4500.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|42|challenges|50|5000.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|43|challenges|54|5400.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|44|no_face|0|0.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|45|no_face|5|500.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|46|no_face|10|1000.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|47|no_face|15|1500.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |
|48|no_face|19|1900.0|Y|0|T|annotated|N/A|N/A|NOT_ASSESSABLE|N/A|NOT_ASSESSABLE_VISUAL |

## 3) Bounding-box QA (all 46 faces)

Programmatic checks: all boxes have positive size and are within 640x480. Visual criteria not assessable.

| clip | frame | idx | annotation_id | bbox xywh | area | aspect(w/h) | in-bounds | Visual: encloses visible face | Visual: tightness/clipping/coverage | Condition labels (as recorded) | Overall |
|---|---:|---:|---|---|---:|---:|---:|---|---|---|---|
|subject_a_front|0|0|ann_ccpcviaj_mwt9prwf|[254.48,131.57,123.16,123.89]|15258.3|0.994|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|vis=visible,pose=unknown,size=medium,blur=none,illum=normal,conf=medium,ignore=F|NOT_ASSESSABLE_VISUAL |
|subject_a_front|5|0|ann_9sf7ehsz_mwt9pyqa|[259.62,128.32,118.03,129.76]|15315.6|0.910|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|10|0|ann_m9f40h3i_mwt9q2yp|[250.82,129.05,138.56,126.09]|17471.0|1.099|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|15|0|ann_jsant3kl_mwt9q7i0|[250.09,130.52,137.82,131.23]|18086.1|1.050|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|20|0|ann_5z6wqn73_mwt9qbzj|[247.89,130.52,142.96,128.29]|18340.3|1.114|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|25|0|ann_8dqaxuwt_mwt9qhbp|[251.55,130.52,138.56,129.76]|17979.5|1.068|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|30|0|ann_4csiwwv2_mwt9qlst|[251.55,127.59,136.36,130.49]|17793.6|1.045|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_front|39|0|ann_flma6js1_mwt9qpys|[250.82,130.52,138.56,128.29]|17775.9|1.080|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|0|0|ann_fgia8q2k_mwt9qur0|[255.95,134.92,129.03,118.76]|15323.6|1.086|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|5|0|ann_rlwpgolu_mwt9qyfv|[253.02,134.92,134.16,118.03]|15834.9|1.137|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|10|0|ann_z7q3ddgc_mwt9r1zg|[253.75,136.39,131.96,115.83]|15284.9|1.139|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|15|0|ann_587vyhcp_mwt9r5jg|[255.22,133.45,131.96,124.63]|16446.2|1.059|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|20|0|ann_mhff6d57_mwt9r92r|[252.29,135.65,133.42,117.30]|15650.2|1.137|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_a_side|29|0|ann_k0n2fiw0_mwt9rf7l|[253.02,137.02,138.56,121.70]|16862.8|1.139|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|0|0|ann_02lvmq4e_mwt9rih7|[252.29,131.89,137.09,126.09]|17285.7|1.087|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|5|0|ann_6ywi6k9s_mwt9rl4k|[252.29,129.69,135.62,123.16]|16703.0|1.101|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|10|0|ann_pws4h1jo_mwt9rnvn|[247.15,126.76,143.69,131.23]|18856.4|1.095|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|15|0|ann_wb1fhk6a_mwt9rrgt|[252.29,128.96,136.36,127.56]|17394.1|1.069|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|20|0|ann_6i8vay5b_mwt9rv5r|[250.09,132.62,137.82,128.29]|17680.9|1.074|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|25|0|ann_fj84xe7i_mwt9rzat|[251.55,133.36,135.62,120.96]|16404.6|1.121|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|30|0|ann_qymodeex_mwt9s2u2|[250.82,134.09,139.29,121.70]|16951.6|1.145|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|subject_b_front|39|0|ann_dcldgwvv_mwt9s6m6|[253.02,132.62,134.89,123.89]|16711.5|1.089|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|0|0|ann_ztsq0vj0_mwt9scb9|[142.32,131.89,126.83,117.30]|14877.2|1.081|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|0|1|ann_r7g12lbw_mwt9sfdj|[387.18,134.82,126.83,118.03]|14969.7|1.075|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|5|0|ann_rs8frk13_mwt9sjlq|[142.32,136.29,127.56,115.10]|14682.2|1.108|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|5|1|ann_hkvxiib1_mwt9smrn|[387.18,133.36,126.83,122.43]|15527.8|1.036|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|10|0|ann_91te684v_mwt9sr5y|[140.12,134.82,129.76,118.76]|15410.3|1.093|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|10|1|ann_qmjjzuv8_mwt9stgp|[387.91,133.36,126.09,117.30]|14790.4|1.075|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|15|0|ann_ftnmq9q7_mwt9sym0|[143.79,132.91,129.03,119.50]|15419.1|1.080|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|15|1|ann_zu17ifo5_mwt9t2a8|[387.18,135.84,128.29,115.83]|14859.8|1.108|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|20|0|ann_bng87um6_mwt9t6cv|[136.46,133.64,134.89,120.23]|16217.8|1.122|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|20|1|ann_hzscthne_mwt9t8ga|[384.98,137.31,130.49,115.10]|15019.4|1.134|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|25|0|ann_osnhf7mc_mwt9usl1|[140.12,131.44,128.29,122.43]|15706.5|1.048|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|25|1|ann_eifdmmhr_mwt9uuoy|[387.18,136.58,126.09,118.03]|14882.4|1.068|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|34|0|ann_wqrlw85n_mwt9uy30|[142.32,132.91,128.29,118.76]|15235.7|1.080|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|multi_subject|34|1|ann_jv7fkth4_mwt9uzt1|[386.44,135.84,122.43,109.97]|13463.6|1.113|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|challenges|0|0|ann_7wi8y88o_mwt9v2q4|[250.82,130.71,137.09,128.29]|17587.3|1.069|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|challenges|5|0|ann_iuio76lh_mwt9v5w0|[250.82,132.91,137.82,123.89]|17074.5|1.112|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|NOT_ASSESSABLE_VISUAL |
|challenges|10|0|ann_vmy9yev7_mwt9vae2|[270.61,145.37,98.97,85.04]|8416.4|1.164|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|15|0|ann_o4tbl48z_mwt9vdyt|[271.35,147.57,94.57,86.51]|8181.3|1.093|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|20|0|ann_dcwl2cj6_mwt9vgr8|[250.09,134.38,142.22,120.23]|17099.1|1.183|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|25|0|ann_mhly6psm_mwt9vlcy|[253.75,134.38,132.69,123.89]|16439.0|1.071|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|29|0|ann_orshfb92_mwt9vood|[257.42,133.64,127.56,120.23]|15336.5|1.061|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|30|0|ann_s0ocizmp_mwt9vv20|[252.29,129.25,134.16,58.65]|7868.5|2.287|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|35|0|ann_xbowp7fk_mwt9vya8|[254.48,129.98,131.23,60.85]|7985.3|2.157|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |
|challenges|39|0|ann_ff4v99en_mwt9w1l7|[250.82,130.71,137.09,57.92]|7940.3|2.367|Y|NOT_ASSESSABLE|NOT_ASSESSABLE|same|QUESTIONABLE_LABEL_REVIEW |

**Questionable (metadata-driven, not visual proof):** `challenges` 10/15 have much smaller bbox area (~8.2-8.4k px²) vs most others (~15-18k), yet `face_size=medium`; `challenges` 30/35/39 have ~half height and aspect ~2.16-2.37, yet `visibility=visible` and `illumination=normal`; `challenges` 20/25/29 selected for dark/small-face-candidate conditions but labels are `blur=none, illumination=normal, size=medium`. These require human visual review; I cannot confirm correctness/incorrectness.

## 4) No-face QA (all 9 frames)

| clip | frame | ts_ms | no_face | faces | img exists | Visual: no-face justified | Notes | Overall |
|---|---:|---:|---:|---:|---:|---|---|---|
|challenges|40|4000.0|true|0|Y|NOT_ASSESSABLE|Selection target includes no-face boundary; verify no visible face/partial face present|NOT_ASSESSABLE_VISUAL |
|challenges|45|4500.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|challenges|50|5000.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|challenges|54|5400.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|no_face|0|0.0|true|0|Y|NOT_ASSESSABLE|Clip intended no-face; still needs visual confirmation|NOT_ASSESSABLE_VISUAL |
|no_face|5|500.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|no_face|10|1000.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|no_face|15|1500.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |
|no_face|19|1900.0|true|0|Y|NOT_ASSESSABLE|Verify visually|NOT_ASSESSABLE_VISUAL |

## 5) Condition-label QA

### Distribution (programmatic)
- visibility: `visible=46` (100%)
- pose: `unknown=46` (100%) — **questionable for manual review**, especially `subject_a_front`, `subject_b_front`, `subject_a_side` where pose is expected to vary; cannot visually confirm.
- face_size: `medium=46` (100%) — **questionable** given bbox area/aspect outliers in challenges.
- blur: `none=46` (100%) — **questionable** for challenges blur-selected frames 10/15.
- illumination: `normal=46` (100%) — **questionable** for challenges dark-selected frames 20/25/29.
- annotation_confidence: `medium=46`
- ignore_difficult: `false=46`

### Assessment
All condition labels are **NOT_VISUALLY_VERIFIED**. The uniform defaults are a high-priority manual QA signal, not automatic evidence of error. Do not bulk-edit without visual review.

## 6) Errors / questionable / recommended manual corrections

| Severity | Item | Evidence | Recommendation |
|---|---|---|---|
|LIMITATION|All 48 frames visual inspection|Image input unsupported in agent environment|Human reviewer must visually inspect every frame/box before benchmark use|
|QUESTIONABLE|All 46 faces `pose=unknown`|Uniform 100%; conflicts with intended clip conditions (front/side)|Manually review pose per face; set front/slight_profile/profile/unknown based on visible face|
|QUESTIONABLE|All 46 `face_size=medium`|Uniform; bbox areas vary 7868-18856; challenges 10/15 much smaller|Define size rule (px area/face height ratio) and review visually|
|QUESTIONABLE|All 46 `blur=none`|Challenges 10/15 selected as blur targets|Visually review blur labels|
|QUESTIONABLE|All 46 `illumination=normal`|Challenges 20/25/29 selected as dark/low illumination targets|Visually review illumination labels|
|QUESTIONABLE|Challenges 30/35/39 occlusion labels/box shape|Bbox height ~58-61px, aspect >2.15 while visibility=visible|Visually confirm if partial/heavy occlusion and bbox covers visible face only as intended|
|QUESTIONABLE|No-face frames 40/45/50/54, no_face 0/5/10/15/19|No visual confirmation possible|Visually confirm absence of any visible/partial face; if ambiguous, mark needs_review/ignore_difficult per schema|

## 7) Summary counts

| Category | Count | Basis |
|---|---:|---|
| Verified (programmatic) | 48 frames / 46 boxes | Coverage, uniqueness, file/dims, bbox bounds, schema values present |
| Questionable | 46 boxes (condition labels uniform/default-like) + 8 specific challenge boxes flagged; 9 no-face frames need visual confirmation | Metadata pattern/selection intent mismatch; not visual proof |
| Incorrect | 0 confirmed | No visual evidence available |
| Not assessable (visual) | 48/48 frames, 46/46 boxes for visual criteria, 9/9 no-face justifications | Image input unsupported |

## 8) Benchmark suitability

**Not suitable to declare benchmark-ready yet.** Reasons: no complete human/visual QA completed by this agent; all visual criteria NOT_ASSESSABLE; condition labels are uniformly default-like and require manual review; `qa-report.json` already states `benchmark_ready=false`, `qa_status=NOT_REVIEWED`. The dataset may become suitable for a *limited pilot benchmark* only after human visual QA confirms/corrects boxes, no-face frames, and condition labels.

## 9) Remaining limitations
- No visual inspection possible in current agent environment; this is a blocking limitation for Task 12's visual objective.
- Synthetic dataset only; not representative of real CCTV/R4C domain.
- Small sample (48 frames, 46 boxes) and correlated adjacent frames; not independent samples.
- No bbox GT external gold standard; human QA is required.

## Files created
- `reports/ps04cctv-audit/TASK-12-HUMAN-ANNOTATION-VISUAL-QA.md` (this report only)

## Confirmations
- Annotation data files were **not modified** (`human-annotations.status-fixed.json`, `human-annotations.json`, selection manifest, derived frames untouched).
- Production code and DB were **not modified**.
- **Git state untouched**: no add/commit/push/pull/fetch/sync/branch/tag/reset/rebase/cherry-pick/remote operations performed.
