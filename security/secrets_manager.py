import os
import logging
from typing import Dict

logger = logging.getLogger(__name__)

_secrets_cache: Dict[str, str] = {}
_gcp_client = None
_gcp_project_id = None

def _initialize_gcp_client():
    global _gcp_client, _gcp_project_id
    if _gcp_client is not None:
        return

    try:
        from google.cloud import secretmanager
        _gcp_project_id = os.getenv("GCP_PROJECT_ID")
        if _gcp_project_id:
            _gcp_client = secretmanager.SecretManagerServiceClient()
            logger.info("Initialized Google Cloud Secret Manager client.")
        else:
            logger.debug("GCP_PROJECT_ID not set. Falling back to local environment variables.")
    except ImportError:
        logger.warning("google-cloud-secret-manager package not found. Falling back to local environment variables.")
    except Exception as e:
        logger.warning(f"Failed to initialize Secret Manager client: {e}. Falling back to local environment variables.")

def get_secret(secret_name: str, default: str = "") -> str:
    """
    Retrieve a secret from Google Cloud Secret Manager.
    Falls back to `os.getenv` if GCP is not configured (e.g. local dev).
    """
    # Return from cache if we have it
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]

    _initialize_gcp_client()

    # Try fetching from GCP if client is available
    if _gcp_client and _gcp_project_id:
        name = f"projects/{_gcp_project_id}/secrets/{secret_name}/versions/latest"
        try:
            response = _gcp_client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8")
            _secrets_cache[secret_name] = secret_value
            return secret_value
        except Exception as e:
            logger.warning(f"Could not retrieve {secret_name} from GCP Secret Manager: {e}. Trying local env.")

    # Fallback to local environment variable
    val = os.getenv(secret_name)
    if val is not None:
        _secrets_cache[secret_name] = val
        return val

    return default

def set_secret(secret_name: str, secret_value: str):
    """
    Set a secret locally in the cache for testing or runtime overrides.
    Does NOT write to GCP Secret Manager.
    """
    _secrets_cache[secret_name] = secret_value
