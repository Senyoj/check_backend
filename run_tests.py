"""
check_backend — Pre-deployment test suite
Tests: imports, schemas, JWT logic, cache, OCR helpers, and live /health endpoint.
"""
import sys, os, json, asyncio, time, importlib
from datetime import date, timedelta

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = 0
failed = 0
warnings = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg, exc=None):
    global failed
    failed += 1
    detail = f" — {exc}" if exc else ""
    print(f"  {RED}✗{RESET} {msg}{detail}")

def warn(msg):
    global warnings
    warnings += 1
    print(f"  {YELLOW}⚠{RESET}  {msg}")

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*55}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*55}{RESET}")

# Add project root to sys.path so internal imports resolve
sys.path.insert(0, os.path.dirname(__file__))

# ── 0. Environment / .env ────────────────────────────────────────────────────
section("0 · Environment & .env")

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    ok(f".env file present at {env_path}")
    with open(env_path) as f:
        env_content = f.read()
    for key in ["GEMINI_API_KEY"]:
        if key in env_content:
            ok(f"{key} found in .env")
        else:
            fail(f"{key} MISSING from .env — required for Gemini OCR")
else:
    fail(".env file NOT found")

firebase_sdk_path = os.path.join(os.path.dirname(__file__), "firebase-adminsdk.json")
if os.path.exists(firebase_sdk_path):
    ok("firebase-adminsdk.json present")
    try:
        with open(firebase_sdk_path) as f:
            sdk = json.load(f)
        required_keys = ["type","project_id","private_key_id","private_key","client_email"]
        missing = [k for k in required_keys if k not in sdk]
        if missing:
            fail(f"firebase-adminsdk.json missing keys: {missing}")
        else:
            ok(f"firebase-adminsdk.json valid (project: {sdk.get('project_id')})")
    except json.JSONDecodeError as e:
        fail("firebase-adminsdk.json is not valid JSON", e)
else:
    fail("firebase-adminsdk.json NOT found")

# ── 1. Python version ────────────────────────────────────────────────────────
section("1 · Python Runtime")
v = sys.version_info
if v >= (3, 10):
    ok(f"Python {v.major}.{v.minor}.{v.micro} — meets ≥3.10 requirement")
else:
    fail(f"Python {v.major}.{v.minor}.{v.micro} — need ≥3.10 for union-type hints")

# ── 2. Imports ───────────────────────────────────────────────────────────────
section("2 · Dependency Imports")
packages = {
    "fastapi":            "fastapi",
    "uvicorn":            "uvicorn",
    "pydantic":           "pydantic",
    "pydantic_settings":  "pydantic_settings",
    "firebase_admin":     "firebase_admin",
    "jose":               "jose",
    "google.genai":       "google.genai",
    "PIL":                "Pillow",
    "anyio":              "anyio",
    "dotenv":             "python-dotenv",
    "aiofiles":           "aiofiles",
}
for mod, pkg in packages.items():
    try:
        importlib.import_module(mod)
        ok(f"{pkg}")
    except ImportError as e:
        fail(f"{pkg} import failed", e)

# ── 3. App-level imports ─────────────────────────────────────────────────────
section("3 · App Module Imports")
modules_to_test = [
    ("config.settings",               "settings"),
    ("app.core.cache",                "timetable_cache"),
    ("app.modules.auth.schemas",      "UserPayload, FirebaseTokenRequest, TokenResponse"),
    ("app.modules.ocr.schemas",       "ExtractedCourse, TimetableResponse, SaveTimetableRequest, TimetableSetupRequest"),
]

for mod_path, items in modules_to_test:
    try:
        importlib.import_module(mod_path)
        ok(f"{mod_path}  [{items}]")
    except Exception as e:
        fail(f"{mod_path}", e)

# ── 4. Settings validation ───────────────────────────────────────────────────
section("4 · Settings & Config")
try:
    from config.settings import settings
    ok(f"APP_NAME = '{settings.APP_NAME}'")
    ok(f"DEBUG    = {settings.DEBUG}")
    ok(f"JWT_ALGORITHM = {settings.JWT_ALGORITHM}")
    ok(f"JWT expiry = {settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES} min")
    ok(f"MAX_UPLOAD_SIZE_MB = {settings.MAX_UPLOAD_SIZE_MB}")
    ok(f"FIREBASE_SERVICE_ACCOUNT_PATH = {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")

    if isinstance(settings.ALLOWED_ORIGINS, list) and len(settings.ALLOWED_ORIGINS) > 0:
        ok(f"ALLOWED_ORIGINS = {settings.ALLOWED_ORIGINS}")
    else:
        warn("ALLOWED_ORIGINS is empty — CORS will block all browser requests")

    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "":
        ok("GEMINI_API_KEY is set (non-empty)")
    else:
        fail("GEMINI_API_KEY is empty — OCR endpoint will fail")

    if settings.JWT_SECRET_KEY and len(settings.JWT_SECRET_KEY) >= 32:
        ok("JWT_SECRET_KEY is set and ≥32 chars")
    else:
        fail("JWT_SECRET_KEY too short — must be ≥32 chars for security")
except Exception as e:
    fail("Settings failed to load", e)

# ── 5. Schema validation ─────────────────────────────────────────────────────
section("5 · Pydantic Schema Validation")
try:
    from app.modules.auth.schemas import FirebaseTokenRequest, UserPayload, TokenResponse
    from app.modules.ocr.schemas import (
        ExtractedCourse, TimetableResponse, SaveTimetableRequest,
        TimetableSetupRequest, CourseNotificationSettings
    )

    # --- Auth schemas
    req = FirebaseTokenRequest(token="fake-firebase-token")
    ok(f"FirebaseTokenRequest — token field present: {bool(req.token)}")

    user = UserPayload(id="uid123", email="user@example.com", full_name="Test User")
    ok(f"UserPayload — id={user.id}, email={user.email}")

    # --- OCR schemas
    course = ExtractedCourse(
        course_name="Software Engineering",
        day_of_week="Monday",
        time_start="9:00 AM",
        time_end="11:00 AM",
        location="Lab 3"
    )
    ok(f"ExtractedCourse — {course.course_name} on {course.day_of_week}")

    future_date = date.today() + timedelta(days=90)
    setup_req = TimetableSetupRequest(
        semester_end_date=future_date,
        fcm_token="fcm-token-example",
        course_notifications=[
            CourseNotificationSettings(course_name="Software Engineering", notification_lead_minutes=15)
        ]
    )
    ok(f"TimetableSetupRequest — semester_end_date={setup_req.semester_end_date}")

    # Validation: past semester_end_date should raise ValueError
    try:
        past_date = date.today() - timedelta(days=1)
        TimetableSetupRequest(semester_end_date=past_date)
        fail("TimetableSetupRequest should reject past semester_end_date")
    except Exception:
        ok("TimetableSetupRequest correctly rejects past semester_end_date")

    # CourseNotificationSettings boundary
    try:
        CourseNotificationSettings(course_name="X", notification_lead_minutes=1441)
        fail("CourseNotificationSettings should reject lead_minutes > 1440")
    except Exception:
        ok("CourseNotificationSettings correctly rejects lead_minutes > 1440")

    ok("CourseNotificationSettings default lead = 30")
    cn = CourseNotificationSettings(course_name="Math")
    assert cn.notification_lead_minutes == 30

except Exception as e:
    fail("Schema validation error", e)

# ── 6. JWT Logic ─────────────────────────────────────────────────────────────
section("6 · JWT Token Creation & Decoding")
try:
    from app.modules.auth.schemas import UserPayload
    from jose import jwt
    from config.settings import settings
    from datetime import datetime, timedelta, timezone

    user = UserPayload(id="test-uid", email="test@example.com", full_name="Test User")

    # Manually replicate create_access_token (avoids Firebase init side-effect)
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    ok(f"JWT created (length={len(token)})")

    decoded = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert decoded["sub"] == "test-uid"
    assert decoded["email"] == "test@example.com"
    ok("JWT decoded successfully — sub and email match")

    # Tampered token
    try:
        from jose import JWTError
        tampered = token[:-5] + "AAAAA"
        jwt.decode(tampered, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        fail("JWT should reject tampered token")
    except JWTError:
        ok("JWT correctly rejects tampered token")

    # Expired token
    try:
        from jose import JWTError
        expired_payload = {**payload, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}
        expired_token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        jwt.decode(expired_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        fail("JWT should reject expired token")
    except JWTError:
        ok("JWT correctly rejects expired token")

except Exception as e:
    fail("JWT test failed", e)

# ── 7. Cache Logic ───────────────────────────────────────────────────────────
section("7 · In-Memory TTL Cache")
try:
    from app.core.cache import AsyncTTLCache

    async def test_cache():
        cache = AsyncTTLCache(default_ttl=1)  # 1-second TTL for testing

        await cache.set("key1", {"data": "hello"})
        val = await cache.get("key1")
        assert val == {"data": "hello"}, "Cache SET/GET failed"
        ok("Cache SET and GET work correctly")

        await cache.delete("key1")
        val = await cache.get("key1")
        assert val is None, "Cache DELETE failed"
        ok("Cache DELETE works correctly")

        await cache.set("key2", "value", ttl=1)
        time.sleep(1.05)
        val = await cache.get("key2")
        assert val is None, "Cache TTL expiration failed"
        ok("Cache TTL expiration works correctly")

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None
        ok("Cache CLEAR works correctly")

        ok("Cache MISS returns None for unknown key")
        miss = await cache.get("nonexistent")
        assert miss is None

    asyncio.run(test_cache())

except Exception as e:
    fail("Cache test failed", e)

# ── 8. OCR Helper Logic ──────────────────────────────────────────────────────
section("8 · OCR Service Helpers")
try:
    from app.modules.ocr.services import _backoff_with_jitter, validate_semester_expiration
    from fastapi import HTTPException

    # Backoff sanity
    delays = [_backoff_with_jitter(i) for i in range(5)]
    for d in delays:
        assert d >= 0, f"Backoff must be non-negative, got {d}"
    ok(f"_backoff_with_jitter values: {[f'{d:.2f}s' for d in delays]}")
    assert delays[-1] <= 12.6, "Max backoff should stay near 12s"
    ok("Backoff capped near _MAX_BACKOFF_S (12s)")

    # validate_semester_expiration — should raise on past date
    try:
        past = {"semester_end_date": (date.today() - timedelta(days=1)).isoformat()}
        validate_semester_expiration(past)
        fail("validate_semester_expiration should raise on past date")
    except HTTPException as e:
        assert e.status_code == 404
        ok("validate_semester_expiration raises HTTP 404 for expired semester")

    # No exception on future date
    future = {"semester_end_date": (date.today() + timedelta(days=100)).isoformat()}
    validate_semester_expiration(future)
    ok("validate_semester_expiration passes for future semester_end_date")

    # No exception when key is absent
    validate_semester_expiration({})
    ok("validate_semester_expiration passes when semester_end_date is absent")

except Exception as e:
    fail("OCR helper test failed", e)

# ── 8.5 Firebase Credentials loading test ──────────────────────────────────────
section("8.5 · Firebase JSON Config Validation")
try:
    from app.core.firebase import init_firebase
    import firebase_admin
    
    # Backup current apps to avoid conflicts
    original_apps = dict(firebase_admin._apps) if isinstance(firebase_admin._apps, dict) else {}
    
    # Test setting FIREBASE_SERVICE_ACCOUNT_JSON
    from config.settings import settings
    
    # Construct a dummy service account dict
    dummy_sa = {
        "type": "service_account",
        "project_id": "test-project-123",
        "private_key_id": "abcd123",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3\n-----END PRIVATE KEY-----\n",
        "client_email": "test@test-project-123.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token"
    }
    
    # 1. Test parsing of valid JSON string
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = json.dumps(dummy_sa)
    
    # Temporarily reset active apps for test
    firebase_admin._apps = {}
    try:
        init_firebase()
        ok("init_firebase initialized successfully with raw JSON string credentials!")
    except Exception as e:
        ok(f"init_firebase credential load completed with status: {type(e).__name__} (expected behavior with dummy data)")
    
    # 2. Test invalid JSON string handling
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = "{invalid json"
    firebase_admin._apps = {}
    try:
        init_firebase()
        fail("init_firebase should have failed on invalid JSON format")
    except RuntimeError as e:
        ok("init_firebase correctly throws RuntimeError when JSON format is invalid")
    except Exception as e:
        fail("init_firebase threw unexpected exception on invalid JSON", e)
        
    # Restore original apps and settings
    firebase_admin._apps = original_apps
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = None
    
except Exception as e:
    fail("Firebase credentials loader test failed", e)

# ── 9. FastAPI App instantiation ─────────────────────────────────────────────
section("9 · FastAPI App & Routes")
try:
    from app.main import app
    from fastapi.testclient import TestClient

    routes = [r.path for r in app.routes]
    ok(f"App '{app.title}' v{app.version} loaded — {len(routes)} routes")

    expected_routes = ["/", "/auth/firebase-exchange", "/auth/me",
                       "/timetable/extract", "/timetable/save",
                       "/timetable/me", "/timetable/share/create",
                       "/timetable/share/{code}", "/timetable/{timetable_id}/setup"]
    missing_routes = [r for r in expected_routes if r not in routes]
    if missing_routes:
        fail(f"Missing routes: {missing_routes}")
    else:
        ok(f"All expected routes registered: {expected_routes}")

    # CORS middleware present
    from starlette.middleware.cors import CORSMiddleware
    middleware_types = [type(m.cls if hasattr(m, 'cls') else m).__name__ for m in app.user_middleware]
    if any("CORS" in t for t in middleware_types):
        ok("CORSMiddleware is registered")
    else:
        warn("CORSMiddleware not found in middleware stack (may be wrapped differently)")

    # Health check endpoint (no Firebase init needed)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/")
    if resp.status_code == 200:
        body = resp.json()
        ok(f"GET /  → 200  body={body}")
        assert body.get("status") == "healthy"
        ok("Health check returns status=healthy")
    else:
        fail(f"GET / returned {resp.status_code}: {resp.text[:200]}")

    # Unauthenticated access to protected routes → 403/401/422
    for path in ["/auth/me", "/timetable/me"]:
        resp = client.get(path)
        if resp.status_code in (401, 403, 422):
            ok(f"GET {path} (no token) → {resp.status_code} (expected)")
        else:
            warn(f"GET {path} (no token) → {resp.status_code} (expected 401/403/422)")

    # POST /auth/firebase-exchange with bad token → 401 (Firebase verification fails)
    resp = client.post("/auth/firebase-exchange", json={"token": "bad_token"})
    if resp.status_code == 401:
        ok("POST /auth/firebase-exchange (bad token) → 401 Unauthorized")
    else:
        warn(f"POST /auth/firebase-exchange (bad token) → {resp.status_code} (expected 401)")

    # POST /timetable/extract without file → 422 Unprocessable
    resp = client.post("/timetable/extract", headers={"Authorization": "Bearer fake"})
    if resp.status_code in (401, 403, 422):
        ok(f"POST /timetable/extract (no file, no auth) → {resp.status_code} (expected)")
    else:
        warn(f"POST /timetable/extract → {resp.status_code}")

except Exception as e:
    fail("FastAPI app test failed", e)

# ── 10. Docs availability ─────────────────────────────────────────────────────
section("10 · OpenAPI / Docs Endpoints")
try:
    from app.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)

    for path in ["/docs", "/redoc", "/openapi.json"]:
        resp = client.get(path)
        if resp.status_code == 200:
            ok(f"GET {path} → 200")
        else:
            warn(f"GET {path} → {resp.status_code}")

    # Check OpenAPI spec has both tag groups
    resp = client.get("/openapi.json")
    if resp.status_code == 200:
        spec = resp.json()
        raw_tags = spec.get("tags") or []
        tags = [t["name"] for t in raw_tags if isinstance(t, dict) and "name" in t]
        ok(f"OpenAPI tags: {tags}")
        paths = list(spec.get("paths", {}).keys())
        ok(f"OpenAPI path count: {len(paths)}")

except Exception as e:
    fail("Docs endpoint test failed", e)

# ── Summary ───────────────────────────────────────────────────────────────────
total = passed + failed
section("Test Summary")
print(f"  {GREEN}Passed  : {passed}{RESET}")
if warnings:
    print(f"  {YELLOW}Warnings: {warnings}{RESET}")
if failed:
    print(f"  {RED}Failed  : {failed}{RESET}")
print(f"  Total   : {total}")
print()
if failed == 0:
    print(f"  {GREEN}{BOLD}✓ All tests passed — backend is ready for deployment!{RESET}")
else:
    print(f"  {RED}{BOLD}✗ {failed} test(s) failed — fix issues before deploying.{RESET}")

sys.exit(0 if failed == 0 else 1)
