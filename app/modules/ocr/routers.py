from fastapi import APIRouter, Depends, File, UploadFile

from app.modules.auth.schemas import UserPayload
from app.modules.auth.services import get_current_user
from app.modules.ocr.schemas import (
    TimetableResponse,
    SaveTimetableRequest,
    ShareCreateResponse,
    SharedTimetableResponse,
    TimetableSetupRequest,
)
from app.modules.ocr.services import (
    run_ocr_pipeline,
    validate_and_read_image,
    save_timetable,
    get_timetable,
    create_timetable_share,
    get_shared_timetable as fetch_shared_timetable,
    setup_timetable,
)

router = APIRouter()

@router.post("/extract", response_model=TimetableResponse)
async def extract_timetable(
    file: UploadFile = File(...),
    current_user: UserPayload = Depends(get_current_user),
):
    image_bytes, mime_type = await validate_and_read_image(file)
    result = await run_ocr_pipeline(image_bytes, mime_type)
    return result

@router.post("/save")
async def save_user_timetable(
    body: SaveTimetableRequest,
    current_user: UserPayload = Depends(get_current_user),
):
    return await save_timetable(current_user.id, body)

@router.get("/me")
async def get_user_timetable(
    include_inactive: bool = False,
    current_user: UserPayload = Depends(get_current_user),
):
    return await get_timetable(current_user.id, include_inactive=include_inactive)

@router.post("/share/create", response_model=ShareCreateResponse, status_code=201)
async def create_timetable_share_endpoint(
    current_user: UserPayload = Depends(get_current_user),
):
    return await create_timetable_share(current_user.id)

@router.get("/share/{code}", response_model=SharedTimetableResponse)
async def get_shared_timetable_endpoint(code: str):
    return await fetch_shared_timetable(code)

@router.post("/{timetable_id}/setup")
async def setup_user_timetable(
    timetable_id: str,
    body: TimetableSetupRequest,
    current_user: UserPayload = Depends(get_current_user),
):
    return await setup_timetable(current_user.id, timetable_id, body)

