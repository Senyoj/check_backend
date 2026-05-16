import firebase_admin
from firebase_admin import credentials, firestore
from config.settings import settings

def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        firebase_admin.initialize_app(cred)

def get_firestore_client():
    init_firebase()
    return firestore.client()
