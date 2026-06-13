import json
import firebase_admin
from firebase_admin import credentials, firestore
from config.settings import settings

def init_firebase():
    if not firebase_admin._apps:
        if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
            try:
                cred_dict = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
                cred = credentials.Certificate(cred_dict)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON environment variable: {e}"
                )
        elif settings.FIREBASE_SERVICE_ACCOUNT_PATH:
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        else:
            raise RuntimeError(
                "Neither FIREBASE_SERVICE_ACCOUNT_JSON nor FIREBASE_SERVICE_ACCOUNT_PATH is configured"
            )
        firebase_admin.initialize_app(cred)

def get_firestore_client():
    init_firebase()
    return firestore.client()
