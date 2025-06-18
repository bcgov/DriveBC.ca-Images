from fastapi import Request, Header, HTTPException, status
from typing import Optional
import logging
import os
import json


CAMERA_IP_MAPPING = json.loads(os.getenv("CAMERA_IP_MAPPING", "{}"))
LOCATION_USER_PASS_MAPPING = json.loads(os.getenv("LOCATION_USER_PASS_MAPPING", "{}"))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """Extract the client's real IP address from request headers or connection."""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # In case of we use proxy, X-Forwarded-For may contain a list of IPs
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host

async def authenticate_request(
    request: Request,
    camera_id: Optional[str] = Header(None, alias="camera-id"),
    camera_location: Optional[str] = Header(None, alias="camera-location"),
    username: Optional[str] = Header(None),
    password: Optional[str] = Header(None),
):
    if not all([camera_id, camera_location, username, password]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authentication headers")

    client_ip = get_client_ip(request)
    expected_ip = CAMERA_IP_MAPPING.get(camera_id)

    if not expected_ip:
        logger.warning(f"Unknown camera ID: {camera_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid camera ID")

    if client_ip != expected_ip:
        logger.warning(f"IP mismatch for {camera_id}: expected {expected_ip}, got {client_ip}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP address mismatch")

    expected_creds = LOCATION_USER_PASS_MAPPING.get(camera_location)
    if not expected_creds:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid camera location")

    if username != expected_creds["username"] or password != expected_creds["password"]:
        logger.warning(f"Credential mismatch for location {camera_location}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return {
        "camera_id": camera_id,
        "camera_location": camera_location,
        "client_ip": client_ip,
        "username": username,
    }