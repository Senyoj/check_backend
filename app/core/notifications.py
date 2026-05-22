import logging
from typing import Any, Dict, List, Optional
from firebase_admin import messaging, exceptions
from app.core.firebase import get_firestore_client

logger = logging.getLogger("check.notifications")

async def clean_up_invalid_token(fcm_token: str) -> None:
    """
    Scans the database to find the user(s) holding the invalid FCM token and removes it.
    """
    try:
        db = get_firestore_client()
        # Find users who have this token in their fcm_tokens array
        users_ref = db.collection("users")
        query = users_ref.where("fcm_tokens", "array_contains", fcm_token).stream()
        
        batch = db.batch()
        count = 0
        for doc in query:
            user_ref = users_ref.document(doc.id)
            # Remove from array and clear last_active_fcm_token if it matches
            doc_data = doc.to_dict()
            updates = {
                "fcm_tokens": doc_data.get("fcm_tokens", [])
            }
            if fcm_token in updates["fcm_tokens"]:
                updates["fcm_tokens"].remove(fcm_token)
            
            # If last_active matches, clear it or set it to another token in the list
            if doc_data.get("last_active_fcm_token") == fcm_token:
                updates["last_active_fcm_token"] = updates["fcm_tokens"][0] if updates["fcm_tokens"] else None
            
            batch.update(user_ref, updates)
            count += 1
        
        if count > 0:
            batch.commit()
            logger.info(f"Cleaned up invalid FCM token from {count} user documents.")
    except Exception as e:
        logger.error(f"Error during FCM token cleanup: {e}")

async def send_push_notification(
    fcm_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None
) -> bool:
    """
    Sends a push notification to a single FCM device token.
    Cleans up the token if Firebase reports it as invalid or unregistered.
    """
    if not fcm_token:
        logger.warning("FCM token is empty, skipping notification.")
        return False

    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data or {},
        token=fcm_token,
    )
    
    try:
        # messaging.send is blocking, but run in thread or called directly
        # In a highly asynchronous app, running messaging.send is usually fast, but we can do it directly.
        response = messaging.send(message)
        logger.info(f"Successfully sent notification: {response}")
        return True
    except (messaging.UnregisteredError, exceptions.InvalidArgumentError) as e:
        logger.warning(f"Unregistered or invalid token detected during send: {e}. Starting cleanup.")
        await clean_up_invalid_token(fcm_token)
        return False
    except Exception as e:
        logger.error(f"Failed to send push notification: {e}")
        return False

async def send_multicast_notifications(
    fcm_tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None
) -> List[str]:
    """
    Sends a push notification to multiple FCM device tokens.
    Automatically filters out inactive/invalid tokens and triggers cleanup.
    Returns a list of successfully sent token results.
    """
    valid_tokens = [t for t in fcm_tokens if t]
    if not valid_tokens:
        logger.warning("No valid FCM tokens provided for multicast, skipping.")
        return []

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data or {},
        tokens=valid_tokens,
    )
    
    try:
        response = messaging.send_multicast(message)
        logger.info(
            f"Multicast status: {response.success_count} success, "
            f"{response.failure_count} failure."
        )
        
        successful_tokens = []
        invalid_tokens = []
        
        for idx, resp in enumerate(response.responses):
            token = valid_tokens[idx]
            if resp.success:
                successful_tokens.append(token)
            else:
                # If error indicates token is unregistered, queue it for cleanup
                error_exc = resp.exception
                if isinstance(error_exc, messaging.UnregisteredError) or "unregistered" in str(error_exc).lower():
                    invalid_tokens.append(token)
                    
        # Cleanup invalid tokens asynchronously
        for token in invalid_tokens:
            await clean_up_invalid_token(token)
            
        return successful_tokens
    except Exception as e:
        logger.error(f"Failed to send multicast notification: {e}")
        return []
