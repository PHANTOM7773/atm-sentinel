# CV model license notices

This directory contains the complete license texts for the third-party ONNX model files used by the local computer-vision pipeline.

| Model | File | License | Notice | Source revision |
| --- | --- | --- | --- | --- |
| YuNet | `face_detection_yunet_2026may.onnx` | MIT | `MIT-YuNet.txt` | Hugging Face `2b8e922362946a0db67e861bae0f77826980effd`; upstream OpenCV Zoo file `26cc381e4d2594bb9f47a26eb8fd96c94a13660d` |
| SFace | `face_recognition_sface_2021dec.onnx` | Apache-2.0 | `APACHE-2.0.txt` | Hugging Face `3d7082438a6e4551e840c9b2bb60b71e8da4b524` |
| YOLOX | `object_detection_yolox_2022nov.onnx` | Apache-2.0 | `APACHE-2.0.txt` | Hugging Face `78c368f74ce73ee28fc7a1be418a598c71b58b52` |

Attribution recorded from the audited upstream sources:

- YuNet: MIT, Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>.
- SFace: contributed by Yaoyao Zhong; ONNX conversion credited to Chengrui Wang in the upstream README.
- YOLOX: OpenCV Zoo model derived from the Megvii-BaseDetection/YOLOX project; Apache-2.0 applies to the OpenCV Zoo model directory and files.

These notices cover the model weights and their upstream model-directory licensing. They do not claim ownership of the models or replace review of any other third-party components. SHA256 verification in `data/models/SHA256SUMS.json` remains the authoritative integrity control; source URLs are pinned to immutable revisions where available.
