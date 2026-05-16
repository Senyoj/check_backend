from fastapi import APIRouter, Depends, File, UploadFile

from app.modules.auth.schemas import UserPayload
from app.modules.auth.services import get_current_user
from app.modules.ocr.schemas import TimetableResponse, SaveTimetableRequest
from app.modules.ocr.services import run_ocr_pipeline, validate_and_read_image, save_timetable, get_timetable

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
    current_user: UserPayload = Depends(get_current_user),
):
    return await get_timetable(current_user.id)
