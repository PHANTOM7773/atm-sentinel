from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services.image_enhancement import (
    ImageEnhancementError,
    enhance_observation_crop,
    get_enhancement_meta,
    presets,
    resolve_enhanced_crop,
)

router = APIRouter(prefix="/api/cv", tags=["cv-enhancement"])


class EnhanceRequest(BaseModel):
    case_id: str = Field(min_length=1)
    cv_run_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    crop_id: str = Field(min_length=1)
    preset: str = Field(default="general_enhancement")
    overrides: dict | None = None


@router.get("/enhancement/presets")
def enhancement_presets():
    return {"items": presets(), "derived_label": "AI-enhanced derived image - not original evidence"}


@router.post("/enhancement/face-crop")
def enhancement_face_crop(req: EnhanceRequest):
    try:
        return enhance_observation_crop(
            case_id=req.case_id,
            cv_run_id=req.cv_run_id,
            observation_id=req.observation_id,
            crop_id=req.crop_id,
            preset=req.preset,
            overrides=req.overrides,
        )
    except ImageEnhancementError as e:
        raise HTTPException(e.status_code, e.message)
    except Exception as e:
        raise HTTPException(500, f"Enhancement failed: {type(e).__name__}")


@router.get("/enhancement/face-crop/meta")
def enhancement_face_crop_meta(
    case_id: str = Query(...),
    cv_run_id: str = Query(...),
    observation_id: str = Query(...),
    crop_id: str = Query(...),
    preset: str = Query("general_enhancement"),
):
    try:
        return get_enhancement_meta(case_id, cv_run_id, observation_id, crop_id, preset)
    except ImageEnhancementError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/enhancement/face-crop/image")
def enhancement_face_crop_image(
    case_id: str = Query(...),
    cv_run_id: str = Query(...),
    observation_id: str = Query(...),
    crop_id: str = Query(...),
    preset: str = Query("general_enhancement"),
):
    try:
        path = resolve_enhanced_crop(case_id, cv_run_id, observation_id, crop_id, preset)
    except ImageEnhancementError as e:
        raise HTTPException(e.status_code, e.message)
    return FileResponse(path, media_type="image/jpeg", filename=path.name)
