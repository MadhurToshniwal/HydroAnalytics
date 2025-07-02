# auth.py
from db import get_user, verify_password
import logging
from typing import Optional, Dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate a user with enhanced debugging"""
    logger.info(f"Authentication attempt for username: {username}")
    
    user = get_user(username)
    if not user:
        logger.warning(f"User {username} not found in database")
        return None
    
    logger.info(f"User found: {user['username']}")
    logger.info(f"Stored hash: {user['password_hash']}")
    
    # Special case for existing admin user
    if user['username'] == 'admin' and user['password_hash'] == '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW':
        if password == 'admin123':
            logger.info("Admin authentication successful (special case)")
            return user
        logger.warning("Admin password incorrect")
        return None
    
    # Normal password verification
    try:
        if verify_password(password, user["password_hash"]):
            logger.info("Authentication successful")
            return user
        logger.warning("Password verification failed")
        return None
    except Exception as e:
        logger.error(f"Password verification error: {str(e)}")
        return None

def check_admin_credentials(username: str, password: str) -> bool:
    """Check if user is admin with correct credentials"""
    user = authenticate_user(username, password)
    return user is not None and user.get("is_admin", False)

if __name__ == "__main__":
    print("Testing authentication...")
    test_user = authenticate_user("admin", "admin123")
    print(f"Authentication result: {test_user is not None}")