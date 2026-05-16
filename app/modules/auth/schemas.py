from pydantic import BaseModel, EmailStr

class FirebaseTokenRequest(BaseModel):
    token: str

class UserPayload(BaseModel):
    id: str
    email: EmailStr
    full_name: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPayload
    is_new: bool = False
