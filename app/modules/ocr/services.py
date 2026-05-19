import io
import uuid
from datetime import datetime, timezone

import anyio
import json
from google import genai
from google.genai import types
from fastapi import HTTPException, UploadFile, status
from PIL import Image

from app.core.firebase import get_firestore_client
from app.modules.ocr.schemas import ExtractedCourse, TimetableResponse, SaveTimetableRequest
from config.settings import settings

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

async def validate_and_read_image(file: UploadFile) -> tuple[bytes, str]:
    raw_bytes = await file.read()

    if len(raw_bytes) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        mime_type = Image.MIME.get(image.format or "", "")
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported image format. Allowed types: JPEG, PNG, WEBP, BMP.",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded file. Please upload a valid image.",
        )

    return raw_bytes, mime_type

def _run_gemini_vision_sync(image_bytes: bytes, mime_type: str) -> list[ExtractedCourse]:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = """
    Extract the class schedule from this timetable image.
    Return ONLY a valid JSON array of objects. Do not include any markdown formatting or comments.
    Each object must have exactly these keys:
    "course_name" (string), "day_of_week" (string), "time_start" (string, e.g., "9:00 AM"), "time_end" (string, e.g., "11:00 AM"), "location" (string).
    If a field is missing, use "Unknown".
    Correct any obvious OCR typos (e.g. M0nday -> Monday).
    """
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt
        ]
    )
    
    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        data = json.loads(text)
        return [ExtractedCourse(**item) for item in data]
    except Exception as e:
        print(f"Failed to parse Gemini response: {e}\nResponse was: {response.text}")
        return []

async def run_ocr_pipeline(image_bytes: bytes, mime_type: str) -> TimetableResponse:
    schedule = await anyio.to_thread.run_sync(
        lambda: _run_gemini_vision_sync(image_bytes, mime_type)
    )

    return TimetableResponse(
        timetable_id=str(uuid.uuid4()),
        extracted_at=datetime.now(timezone.utc),
        schedule=schedule,
    )

async def save_timetable(user_id: str, body: SaveTimetableRequest) -> dict:
    db = get_firestore_client()
    timetable_id = str(uuid.uuid4())
    doc_data = {
        "timetable_id": timetable_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "schedule": [course.model_dump() for course in body.schedule],
    }
    db.collection("users").document(user_id).collection("timetables").document(timetable_id).set(doc_data)
    return {"timetable_id": timetable_id, "message": "Timetable saved successfully."}

async def get_timetable(user_id: str) -> dict:
    db = get_firestore_client()
    docs = db.collection("users").document(user_id).collection("timetables").order_by(
        "saved_at", direction="DESCENDING"
    ).limit(1).stream()

    for doc in docs:
        return doc.to_dict()

    raise HTTPException(
        status_code=404,
        detail="No timetable found for this user.",
    )

async def _fetch_latest_timetable(user_id: str) -> dict:
    db = get_firestore_client()
    docs = db.collection("users").document(user_id).collection("timetables").order_by(
        "saved_at", direction="DESCENDING"
    ).limit(1).stream()

    for doc in docs:
        return doc.to_dict()

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No timetable found for this user.",
    )

async def create_timetable_share(user_id: str) -> dict:
    latest_timetable = await _fetch_latest_timetable(user_id)
    share_code = uuid.uuid4().hex

    share_doc = {
        "share_code": share_code,
        "owner_id": user_id,
        "timetable_id": latest_timetable["timetable_id"],
        "saved_at": latest_timetable["saved_at"],
        "shared_at": datetime.now(timezone.utc).isoformat(),
        "schedule": latest_timetable["schedule"],
    }

    db = get_firestore_client()
    db.collection("shares").document(share_code).set(share_doc)

    return {"share_code": share_code, "message": "Share created successfully."}

async def get_shared_timetable(code: str) -> dict:
    db = get_firestore_client()
    doc = db.collection("shares").document(code).get()

    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shared timetable not found for code: {code}",
        )

    return doc.to_dict()
