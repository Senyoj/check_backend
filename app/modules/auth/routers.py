from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from app.modules.auth.schemas import FirebaseTokenRequest, TokenResponse, UserPayload
from app.modules.auth.services import (
    create_access_token,
    get_current_user,
    verify_firebase_token,
)
from app.core.firebase import get_firestore_client

router = APIRouter()

@router.post("/firebase-exchange", response_model=TokenResponse)
def firebase_login(body: FirebaseTokenRequest):
    claims = verify_firebase_token(body.token)

    user = UserPayload(
        id=claims["uid"],
        email=claims.get("email", ""),
        full_name=claims.get("name", ""),
    )

    access_token = create_access_token(user)
    
    # Check if user is new in Firestore
    db = get_firestore_client()
    user_ref = db.collection("users").document(user.id)
    user_doc = user_ref.get()
    
    is_new = not user_doc.exists
    
    if is_new:
        # Initialize user document if new
        user_ref.set({
            "email": user.email,
            "full_name": user.full_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    return TokenResponse(access_token=access_token, user=user, is_new=is_new)

@router.get("/me", response_model=UserPayload)
def get_me(current_user: UserPayload = Depends(get_current_user)):
    return current_user
