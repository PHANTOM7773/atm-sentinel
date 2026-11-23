flowchart LR
  classDef production fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
  classDef experiment fill:#fff8e1,stroke:#f9a825,color:#6d4c00
  classDef unavailable fill:#fdecea,stroke:#c62828,color:#7f0000,stroke-dasharray: 5 3
  classDef data fill:#e3f2fd,stroke:#1565c0,color:#0d47a1

  subgraph FE["Frontend - production React 19 SPA"]
    APP["AppShell / BrowserRouter<br/>case-preserving ?case= navigation"]
    DASH["/ Dashboard"]
    CASES["/cases Case management"]
    INV["/investigation Guided 7-step workflow"]
    WORK["/workspace Video timeline and manual capture"]
    EVID["/evidence Evidence gallery"]
    COMPARE["/compare Manual comparison and metadata search"]
    CVUI["/cv CV runs, observations, associations,<br/>best-face, candidate search, review"]
    EXPORTUI["/export PDF/JSON/ZIP export"]
    API["lib/api.ts fetch client<br/>credentials: include"]
  end

  subgraph APILAYER["Backend - production FastAPI"]
    MAIN["backend/app/main.py<br/>lifespan init_db, CORS, session guard"]
    SESSION["POST /api/session"]
    SYSTEM["GET /api/system/status"]
    CASEAPI["/api/cases, /api/search"]
    VIDEOAPI["/api/videos, /api/alignment/preview"]
    JOBAPI["/api/jobs"]
    FRAMEAPI["/api/frames"]
    EXPORTAPI["/api/exports"]
    CVAPI["/api/cv/runs, observations, reviews,<br/>associations, candidates"]
    ENHAPI["/api/cv/enhancement/*"]
  end

  subgraph SERVICES["Backend services - production"]
    SEC["security.py / video.py / timestamp.py<br/>upload validation, ffprobe, SHA-256,<br/>normalization, alignment"]
    STORE["db.py SQLite schema v5<br/>WAL, foreign keys, audit_events"]
    JOBS["jobs.py frame extraction jobs"]
    FRAMES["extraction.py / quality.py<br/>frames, quality, manual capture"]
    CVINT["cv_integration.py<br/>run lifecycle, provenance, budgets,<br/>public DTO sanitization"]
    ASSOC["atm_association.py<br/>zone overlap, timing, continuity, review"]
    BEST["best_face.py + face_reliability.py<br/>deterministic ranking and reliability"]
    ENH["image_enhancement.py<br/>derived-only OpenCV preview"]
    EXPORTSVC["export.py<br/>PDF, manifest, ZIP, hashes"]
    EMBED["embeddings.py<br/>V4 provenance-aware SFace index"]
  end

  subgraph CVPIPE["Production CV pipeline - heuristic/review-only"]
    YOLOX["YOLOX person detector<br/>class 0, CPU ONNX, score threshold 0.45"]
    SIMPLE["SimpleTracker<br/>clip-local track IDs"]
    YUNET["YuNet face detector + 5 landmarks"]
    QUALITY["face quality heuristics"]
    SFACE["SFace 128-d embeddings<br/>candidate ranking only"]
    CROPDIR["data/cv/crops + provenance gate"]
  end

  subgraph STORAGE["Production storage and outputs"]
    DB[("data/sentinel.db")]
    UPLOADS[("data/uploads original files")]
    NORM[("data/videos normalized derivatives")]
    FRAMESDATA[("data/frames + thumbnails")]
    CVDATA[("data/cv runs and crops")]
    ENHDATA[("reports/.../task15-enhancements derived previews")]
    EXPORTS[("data/exports PDF/JSON/ZIP")]
    MODELS[("data/models pinned ONNX + SHA256SUMS.json")]
  end

  subgraph EXP["Isolated experiments - not production-integrated"]
    EXP1["Baseline / YuNet recall / fallback / person gate / YOLOX threshold"]
    EXP2["ByteTrack-inspired tracker"]
    EXP3["TASK15 classical enhancement measurements"]
    EXP4["TASK16 quality scoring experiment"]
    EXP5["TASK17 face-box GT benchmark"]
    EXP6["TASK18 SFace retrieval benchmark"]
    EXP7["Annotation pilot tool and QA reports"]
  end

  subgraph UNAVAIL["Planned or unavailable - must not be depicted as product"]
    U1["No RWATCH/Aadhaar/criminal DB matching"]
    U2["No live RTSP/ONVIF bank CCTV connection"]
    U3["No OCR or automatic CCTV clock extraction"]
    U4["No mask/helmet/cap classifier<br/>status remains not_assessed"]
    U5["No WORM/tamper-proof audit or certified custody"]
    U6["No per-user RBAC, actor attribution, logout, or revocation"]
    U7["GFPGAN / Real-ESRGAN / CodeFormer / CR-FIQA / MagFace<br/>not available locally"]
    U8["TASK10/11/13 artifacts not found; R4C real data not assessed"]
  end

  APP --> DASH & CASES & INV & WORK & EVID & COMPARE & CVUI & EXPORTUI
  DASH & CASES & INV & WORK & EVID & COMPARE & CVUI & EXPORTUI --> API
  API -->|JSON / multipart / file streams| MAIN
  MAIN --> SESSION & SYSTEM & CASEAPI & VIDEOAPI & JOBAPI & FRAMEAPI & EXPORTAPI & CVAPI & ENHAPI
  CASEAPI --> STORE
  VIDEOAPI --> SEC
  JOBAPI --> JOBS
  FRAMEAPI --> FRAMES
  EXPORTAPI --> EXPORTSVC
  CVAPI --> CVINT
  ENHAPI --> ENH
  SEC --> UPLOADS & NORM
  SEC --> STORE
  JOBS --> FRAMES
  FRAMES --> FRAMESDATA
  CVINT --> YOLOX & YUNET & SIMPLE & QUALITY & SFACE & CROPDIR
  CVINT --> ASSOC & BEST & EMBED & STORE
  YOLOX --> MODELS
  YUNET --> MODELS
  SFACE --> MODELS
  CVINT --> CVDATA
  ENH --> CROPDIR --> ENHDATA
  EXPORTSVC --> DB & NORM & FRAMESDATA & CVDATA --> EXPORTS
  SEC --> MODELS

  EXP1 -. isolated measurement .-> YUNET & YOLOX
  EXP2 -. isolated measurement .-> SIMPLE
  EXP3 -. isolated measurement .-> ENH
  EXP4 -. isolated measurement .-> QUALITY
  EXP5 -. isolated measurement .-> YUNET
  EXP6 -. isolated measurement .-> SFACE
  EXP7 -. annotation reports only .-> EXP5

  U1 & U2 & U3 & U4 & U5 & U6 & U7 & U8 -. absent or unavailable .-> UNAVAIL

  class APP,DASH,CASES,INV,WORK,EVID,COMPARE,CVUI,EXPORTUI,API,MAIN,SESSION,SYSTEM,CASEAPI,VIDEOAPI,JOBAPI,FRAMEAPI,EXPORTAPI,CVAPI,ENHAPI,SEC,STORE,JOBS,FRAMES,CVINT,ASSOC,BEST,ENH,EXPORTSVC,EMBED,YOLOX,SIMPLE,YUNET,QUALITY,SFACE,CROPDIR production
  class DB,UPLOADS,NORM,FRAMESDATA,CVDATA,ENHDATA,EXPORTS,MODELS data
  class EXP1,EXP2,EXP3,EXP4,EXP5,EXP6,EXP7 experiment
  class U1,U2,U3,U4,U5,U6,U7,U8 unavailable
