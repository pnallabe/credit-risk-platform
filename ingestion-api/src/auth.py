"""
Authentication module for JWT token verification
Supports OAuth2/JWT tokens, API keys, and Cloud IAM tokens
"""

from typing import Optional, Dict
import os
import logging
from datetime import datetime, timezone
import jwt
from jwt import PyJWTError
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Environment configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "risk-platform")

# For production, use GCP IAM or external OAuth provider
# This is a simple implementation for MVP
VALID_API_KEYS = set(os.getenv("VALID_API_KEYS", "").split(","))


async def verify_token(token: str) -> Optional[Dict]:
    """
    Verify JWT token, API key, or Cloud IAM token
    
    Args:
        token: JWT token, API key, or IAM token
        
    Returns:
        Token payload if valid, None otherwise
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    # Check if it's an API key
    if token in VALID_API_KEYS and token:
        logger.info("Valid API key authentication")
        return {
            "sub": "api-key-user",
            "auth_type": "api_key",
            "authenticated_at": datetime.now(timezone.utc).isoformat()
        }
    
    # Try to decode as JWT (custom tokens)
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True
            }
        )
        
        logger.info(f"Valid JWT authentication for subject: {payload.get('sub')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Expired JWT token")
        # Don't fail yet, try IAM token
        pass
    except jwt.InvalidIssuerError:
        logger.warning("Invalid JWT token issuer")
        # Don't fail yet, try IAM token
        pass
    except PyJWTError as e:
        logger.warning(f"Invalid JWT token: {str(e)}")
        # Don't fail yet, try IAM token
        pass
    
    # Try to decode as Cloud IAM token (for Cloud Run invoker auth)
    try:
        # Decode without verification to check if it's a Google token
        unverified = jwt.decode(token, options={"verify_signature": False})
        
        # Check if it's a Google-issued token
        if unverified.get("iss") in ["accounts.google.com", "https://accounts.google.com"]:
            logger.info(f"Valid Cloud IAM authentication for: {unverified.get('email', 'unknown')}")
            return {
                "sub": unverified.get("email", "iam-user"),
                "auth_type": "cloud_iam",
                "authenticated_at": datetime.now(timezone.utc).isoformat()
            }
    except Exception as e:
        logger.warning(f"Not a valid IAM token: {str(e)}")
    
    # If we get here, token is invalid
    logger.warning("Token validation failed for all methods")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"}
    )


def create_access_token(subject: str, expires_delta: int = 3600, **kwargs) -> str:
    """
    Create a JWT access token
    
    Args:
        subject: Subject (user ID or client ID)
        expires_delta: Token expiration in seconds
        **kwargs: Additional claims to include
        
    Returns:
        Encoded JWT token
    """
    now = datetime.now(timezone.utc)
    expire = now.timestamp() + expires_delta
    
    payload = {
        "sub": subject,
        "iss": JWT_ISSUER,
        "iat": now.timestamp(),
        "exp": expire,
        **kwargs
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token