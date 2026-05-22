import io
import uuid
import time
import random
import logging
from datetime import datetime, timezone

import anyio
import json
from google import genai
from google.genai import types
from google.genai.errors import ServerError
from fastapi import HTTPException, UploadFile, status
from PIL import Image

from app.core.firebase import get_firestore_client
from app.core.cache import timetable_cache
from app.modules.ocr.schemas import ExtractedCourse, TimetableResponse, SaveTimetableRequest, TimetableSetupRequest
from config.settings import settings

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

# ── Strategy 2: Model fallback chain ─────────────────────────────────────────
# Ordered from newest/fastest to most available. Each model draws from a
# different capacity pool, so if one is overloaded the next is often fine.
_GEMINI_MODEL_CHAIN = [
    "gemini-2.5-flash",        # Primary — best free-tier model as of May 2026
    "gemini-2.5-flash-lite",   # Lighter sibling, different quota pool
]

# ── Strategy 1: Retry config ──────────────────────────────────────────────────
_MAX_RETRIES_PER_MODEL = 2   # Attempts per model before moving to the next
_BASE_BACKOFF_S = 1.5        # Initial wait in seconds
_MAX_BACKOFF_S = 12.0        # Cap to avoid long waits on the free tier
_JITTER_RANGE = 0.5          # ±0.5s random jitter so retries don't thunderherd

def _backoff_with_jitter(attempt: int) -> float:
    """Exponential backoff capped at _MAX_BACKOFF_S with uniform jitter."""
    delay = min(_BASE_BACKOFF_S * (2 ** attempt), _MAX_BACKOFF_S)
    jitter = random.uniform(-_JITTER_RANGE, _JITTER_RANGE)
    return max(0.0, delay + jitter)

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
    """
    Calls the Gemini Vision API with two resilience strategies:

    Strategy 1 — Tuned retry with exponential backoff + jitter
        On a 503 UNAVAILABLE, wait _BASE_BACKOFF_S * 2^attempt ± jitter before
        retrying the same model (up to _MAX_RETRIES_PER_MODEL times).
        Non-503 errors skip directly to the next model.

    Strategy 2 — Model fallback chain
        If retries for a model are exhausted, move to the next model in
        _GEMINI_MODEL_CHAIN. Each model draws from a different capacity pool.
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = """
    Extract the class schedule from this timetable image.
    Return ONLY a valid JSON array of objects. Do not include any markdown formatting or comments.
    Each object must have exactly these keys:
    "course_name" (string), "day_of_week" (string), "time_start" (string, e.g., "9:00 AM"), "time_end" (string, e.g., "11:00 AM"), "location" (string).
    If a field is missing, use "Unknown".
    Correct any obvious OCR typos (e.g. M0nday -> Monday).
    """

    last_error: Exception | None = None

    for model_id in _GEMINI_MODEL_CHAIN:
        for attempt in range(_MAX_RETRIES_PER_MODEL):
            try:
                logger.info("OCR attempt model=%s try=%d", model_id, attempt + 1)
                response = client.models.generate_content(
                    model=model_id,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        prompt,
                    ],
                )

                # ── Parse the response ────────────────────────────────────
                try:
                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                    data = json.loads(text)
                    logger.info("OCR succeeded model=%s", model_id)
                    return [ExtractedCourse(**item) for item in data]
                except Exception as parse_err:
                    logger.warning(
                        "OCR parse failed model=%s: %s | raw: %s",
                        model_id, parse_err, response.text[:200],
                    )
                    return []  # Parsed nothing — return empty, don't retry

            except ServerError as exc:
                last_error = exc
                # SDK v0.8+ uses exc.code; older versions used exc.status_code.
                # Fall back to string parsing as a safety net.
                _http_code = (
                    getattr(exc, "code", None)
                    or getattr(exc, "status_code", None)
                    or (503 if "503" in str(exc) else 0)
                )
                is_503 = _http_code == 503

                if is_503 and attempt < _MAX_RETRIES_PER_MODEL - 1:
                    # Strategy 1: back off then retry this same model
                    wait = _backoff_with_jitter(attempt)
                    logger.warning(
                        "503 on model=%s attempt=%d, retrying in %.1fs",
                        model_id, attempt + 1, wait,
                    )
                    time.sleep(wait)
                    continue  # retry same model

                # Retries exhausted or non-503 → try next model
                logger.warning(
                    "Giving up on model=%s after %d attempt(s): %s",
                    model_id, attempt + 1, exc,
                )
                break  # move to next model in chain

            except Exception as exc:
                # Unexpected error (network, auth, etc.) — skip to next model
                last_error = exc
                logger.warning("Unexpected error on model=%s: %s", model_id, exc)
                break

    # All models and all retries exhausted
    logger.error("All Gemini models failed. Last error: %s", last_error)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "The AI service is temporarily overloaded. "
            "Please wait a moment and try again."
        ),
    )

async def run_ocr_pipeline(image_bytes: bytes, mime_type: str) -> TimetableResponse:
    schedule = await anyio.to_thread.run_sync(
        lambda: _run_gemini_vision_sync(image_bytes, mime_type)
    )

    return TimetableResponse(
        timetable_id=str(uuid.uuid4()),
        extracted_at=datetime.now(timezone.utc),
        schedule=schedule,
    )


def validate_semester_expiration(timetable_data: dict) -> None:
    semester_end_date_str = timetable_data.get("semester_end_date")
    if semester_end_date_str:
        try:
            from datetime import date
            end_date = date.fromisoformat(semester_end_date_str)
            if date.today() > end_date:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Your semester timetable has expired.",
                )
        except ValueError:
            pass

async def save_timetable(user_id: str, body: SaveTimetableRequest) -> dict:
    await timetable_cache.delete(f"timetable:{user_id}")
    db = get_firestore_client()
    timetable_id = str(uuid.uuid4())
    doc_data = {
        "timetable_id": timetable_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "schedule": [course.model_dump() for course in body.schedule],
    }
    db.collection("users").document(user_id).collection("timetables").document(timetable_id).set(doc_data)
    return {"timetable_id": timetable_id, "message": "Timetable saved successfully."}

async def get_timetable(user_id: str, include_inactive: bool = False) -> dict:
    cache_key = f"timetable:{user_id}"
    cached_data = await timetable_cache.get(cache_key)
    if cached_data is not None:
        if not include_inactive:
            validate_semester_expiration(cached_data)
        return cached_data

    db = get_firestore_client()
    docs = db.collection("users").document(user_id).collection("timetables").order_by(
        "saved_at", direction="DESCENDING"
    ).limit(1).stream()

    timetable = None
    for doc in docs:
        timetable = doc.to_dict()
        break

    if not timetable:
        raise HTTPException(
            status_code=404,
            detail="No timetable found for this user.",
        )

    await timetable_cache.set(cache_key, timetable)

    if not include_inactive:
        validate_semester_expiration(timetable)

    return timetable

async def _fetch_latest_timetable(user_id: str) -> dict:
    return await get_timetable(user_id, include_inactive=True)

async def create_timetable_share(user_id: str) -> dict:
    latest_timetable = await _fetch_latest_timetable(user_id)
    share_code = uuid.uuid4().hex

    share_doc = {
        "share_code": share_code,
        "owner_id": user_id,
        "timetable_id": latest_timetable["timetable_id"],
        "saved_at": latest_timetable["saved_at"],
        "shared_at": datetime.now(timezone.utc).isoformat(),
        "semester_end_date": latest_timetable.get("semester_end_date"),
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

    data = doc.to_dict()
    validate_semester_expiration(data)
    return data

async def setup_timetable(user_id: str, timetable_id: str, payload: TimetableSetupRequest) -> dict:
    db = get_firestore_client()
    
    # Fetch specified timetable
    timetable_ref = db.collection("users").document(user_id).collection("timetables").document(timetable_id)
    timetable_doc = timetable_ref.get()
    
    if not timetable_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Timetable with ID {timetable_id} not found for this user."
        )
    
    timetable_data = timetable_doc.to_dict()
    schedule = timetable_data.get("schedule", [])
    
    # Map customized notification lead times
    notif_map = {}
    if payload.course_notifications:
        for cn in payload.course_notifications:
            notif_map[cn.course_name.lower().strip()] = cn.notification_lead_minutes
            
    updated_schedule = []
    for course in schedule:
        course_name = course.get("course_name", "")
        lead_time = notif_map.get(course_name.lower().strip(), 30)  # Default is 30 mins
        course["notification_lead_minutes"] = lead_time
        updated_schedule.append(course)
        
    # Firestore Batch Write
    batch = db.batch()
    
    # 1. Update timetable document
    timetable_updates = {
        "semester_end_date": payload.semester_end_date.isoformat(),
        "schedule": updated_schedule,
        "onboarded": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    batch.update(timetable_ref, timetable_updates)
    
    # 2. Update user profile document
    user_ref = db.collection("users").document(user_id)
    user_updates = {
        "onboarding_completed": True,
    }
    if payload.fcm_token:
        from firebase_admin import firestore
        user_updates["fcm_tokens"] = firestore.ArrayUnion([payload.fcm_token])
        user_updates["last_active_fcm_token"] = payload.fcm_token
        
    batch.update(user_ref, user_updates)
    
    # Commit changes atomically
    batch.commit()
    
    # Invalidate Cache
    await timetable_cache.delete(f"timetable:{user_id}")
    
    return {
        "timetable_id": timetable_id,
        "message": "Onboarding timetable setup completed successfully.",
        "semester_end_date": payload.semester_end_date.isoformat(),
    }
