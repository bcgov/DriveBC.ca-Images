from fastapi import Request, Header, HTTPException, status
import logging
import os
import json
from starlette.datastructures import FormData, UploadFile


CAMERA_IP_MAPPING = json.loads(os.getenv("CAMERA_IP_MAPPING", "{}"))
LOCATION_USER_PASS_MAPPING = json.loads(os.getenv("LOCATION_USER_PASS_MAPPING", "{}"))
CAMERA_LOCATION_MAPPING = json.loads(os.getenv("CAMERA_LOCATION_MAPPING", "{}"))

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
):
    form: FormData = await request.form()
    image: UploadFile = form.get("image")

    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")

    filename = image.filename
    name_without_ext = os.path.splitext(filename)[0]
    camera_id = request.headers.get("camera-id")
    username = request.headers.get("username")
    password = request.headers.get("password")

    # Check if all required headers are present
    if not all([camera_id, username, password]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required headers")
    
    # Check if the camera ID matches the image filename
    if camera_id != name_without_ext:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera ID does not match image filename")
    
    client_ip = get_client_ip(request)
    expected_ip = CAMERA_IP_MAPPING.get(camera_id)
    camera_location = CAMERA_LOCATION_MAPPING.get(camera_id)

    # Validate camera IP
    if not expected_ip:
        # If the camera ip does not exist in the camera ip mapping, check the credentials against the location mapping
        logger.warning(f"Unknown camera IP: {client_ip}")
        
        if not camera_location:
            logger.warning(f"Camera ID {camera_id} does not have a valid location mapping")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid camera ID")
        expected_creds = LOCATION_USER_PASS_MAPPING.get(camera_location)

        if username != expected_creds["username"] or password != expected_creds["password"]:
            logger.warning(f"Credential mismatch for location {camera_location}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")
        
    # If the camera IP is known, check if it matches the client's IP
    if expected_ip and client_ip != expected_ip:
        logger.warning(f"IP mismatch for {camera_id}: expected {expected_ip}, got {client_ip}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP address mismatch")

    expected_creds = LOCATION_USER_PASS_MAPPING.get(camera_location)
    if not expected_creds:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid camera location")
    
    # Validate username and password against the expected credentials for the camera location
    if username != expected_creds["username"] or password != expected_creds["password"]:
        logger.warning(f"Credential mismatch for location {camera_location}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return {
        "camera_id": camera_id,
        "camera_location": camera_location,
        "client_ip": client_ip,
        "username": username,
    }