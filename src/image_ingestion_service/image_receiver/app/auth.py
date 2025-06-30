import asyncio
from typing import Optional
from fastapi import Request, Header, HTTPException, Response, status, Depends
import logging
import sys
import os
import json
from starlette.datastructures import FormData, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from .db import get_all_from_db
from prometheus_client import Counter

security = HTTPBasic()

CAMERA_IP_MAPPING = json.loads(os.getenv("CAMERA_IP_MAPPING", "{}"))
LOCATION_USER_PASS_MAPPING = json.loads(os.getenv("LOCATION_USER_PASS_MAPPING", "{}"))
CAMERA_LOCATION_MAPPING = json.loads(os.getenv("CAMERA_LOCATION_MAPPING", "{}"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Shared cache
CREDENTIAL_CACHE = []

# Counters for monitoring in Sysdig
successful_auth_counter = Counter("successful_auth_total", "Count of successful authentications")
unsuccessful_auth_counter = Counter("unsuccessful_auth_total", "Count of failed authentications")
successful_ip_counter = Counter("successful_ip_total", "Count of requests from authorized IPs")
unsuccessful_ip_counter = Counter("unsuccessful_ip_total", "Count of requests from unauthorized IPs")
rabbitmq_push_fail_counter = Counter("rabbitmq_push_fail_total", "Count of failed pushes to RabbitMQ")
rabbitmq_push_success_counter = Counter("rabbitmq_push_success_total", "Count of successful pushes to RabbitMQ")

def record_auth_success():
    successful_auth_counter.inc()

def record_auth_failure():
    unsuccessful_auth_counter.inc()

def record_ip_success():
    successful_ip_counter.inc()

def record_ip_failure():
    unsuccessful_ip_counter.inc()

def record_rabbitmq_success():
    rabbitmq_push_success_counter.inc()

def record_rabbitmq_failure():
    rabbitmq_push_fail_counter.inc()

async def update_credentials_periodically():
    while True:
        try:
            logger.info("Refreshing credentials from DB...")
            creds = get_all_from_db()
            
            if creds:
                CREDENTIAL_CACHE.clear()
                CREDENTIAL_CACHE.extend(creds)
                logger.info(f"Updated {len(creds)} credentials.")
        except Exception as e:
            logger.error(f"Error updating credentials: {e}")
        await asyncio.sleep(30)

def start_credential_refresh_task():
    return asyncio.create_task(update_credentials_periodically())

def get_data_from_db():
    try:
        logger.info("Initializing credentials from DB...")
        creds = get_all_from_db()  
            
        if creds:
            CREDENTIAL_CACHE.clear()
            CREDENTIAL_CACHE.extend(creds)
            # logger.info(f"Initialized {len(creds)} credentials.")
    except Exception as e:
            logger.error(f"Error initilizing credentials: {e}")


def validate_filename_and_get_region_ip(data: list, filename: str) -> tuple[str, str]:
    for record in data:
        clean_filename = record.get("Cam_InternetFTP_Filename", "").strip()
        if clean_filename == filename:
            region = record.get("Cam_LocationsRegion", "").strip()
            ip_address = record.get("Cam_MaintenancePublic_IP", "").strip()
            return region, ip_address
        else:
            logging.debug(f"Filename {clean_filename} does not match {filename}")

    # If no match found, log and raise error
    logging.error(f"No matching record found for filename: {filename}")
    raise ValueError("Unauthorized or unknown image filename")

def get_client_ip(request: Request) -> str:
    """Extract the client's real IP address from request headers or connection."""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # For proxy, X-Forwarded-For contains a list of IPs
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host

def verify_credentials(credentials: HTTPBasicCredentials, expected_creds: dict) -> bool:
    return (
        secrets.compare_digest(credentials.username, expected_creds["username"]) and
        secrets.compare_digest(credentials.password, expected_creds["password"])
    )

def verify_credentials_test(username: str, password: str) -> bool:
    return (
        username == "test" and password == "test" 
    )

def convert_camera_json_to_db_data(camera_ip_map: dict) -> list[dict]:
    location_map = json.loads(os.getenv("CAMERA_LOCATION_MAPPING", "{}"))

    db_data = []
    for idx, (cam_id, ip) in enumerate(camera_ip_map.items(), start=1):
        cam_number = cam_id
        db_data.append({
            'ID': idx,
            'Cam_InternetFTP_Folder': 'https://xxxx',
            'Cam_InternetFTP_Filename': f"{cam_number}.jpg",
            'Cam_LocationsRegion': location_map.get(cam_id, 'Unknown'),
            'Cam_MaintenancePublic_IP': ip
        })
    
    return db_data


async def authenticate_request(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security, use_cache=False),
):
    get_data_from_db()
    db_data = CREDENTIAL_CACHE if CREDENTIAL_CACHE else convert_camera_json_to_db_data(CAMERA_IP_MAPPING)
    
    content_disposition = request.headers.get("content-disposition")
    if not (content_disposition and "filename=" in content_disposition):
        logger.error("Request missing 'content-disposition' header with filename. Discarding.")
        raise HTTPException(status_code=400, detail="Image file is required")
        
    filename = content_disposition.split("filename=")[-1].strip('"')
    camera_id = os.path.splitext(filename)[0]
    
    try:
        region, ip_address = validate_filename_and_get_region_ip(db_data, filename)
    except ValueError as e:
        logger.error(f"Validation Error for {filename}: {e}. Discarding image and returning 200 OK.")
        record_ip_failure()
        record_auth_failure()
        raise HTTPException(status_code=400, detail="Image file is required")

    client_ip = get_client_ip(request)
    expected_creds = LOCATION_USER_PASS_MAPPING.get(region)

    logger.info(f"Camera connect attempt: IP={client_ip}, camera-id={filename}")

    # Validate IP
    if client_ip != ip_address:
        logger.warning(f"IP mismatch for {camera_id}: expected {ip_address}, got {client_ip}. Discarding image and returning 200 OK.")
        record_ip_failure()
        record_auth_failure()
        raise HTTPException(status_code=401, detail="IP mismatch")

    # Validate that credentials exist for the location
    if not expected_creds:
        logger.warning(f"No credentials configured for location '{region}' (camera {camera_id}). Discarding image and returning 200 OK.")
        record_auth_failure()
        raise HTTPException(status_code=401, detail="Credential mismatch")
        
    # Validate the provided credentials
    if not verify_credentials(credentials, expected_creds):
        logger.warning(f"Invalid credentials for camera {camera_id} from IP {client_ip}. Discarding image and returning 200 OK.")
        record_auth_failure()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    logger.info(f"Successfully authenticated camera {camera_id}.")
    record_ip_success()
    record_auth_success()
    return {
        "camera_id": camera_id,
        "region": region,
        "ip_address": ip_address
    }