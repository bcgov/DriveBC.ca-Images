import asyncio
from typing import Optional
from fastapi import Request, Header, HTTPException, Response, status, Depends
import logging
import json
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from .db import get_all_from_db 
from prometheus_client import Counter
import ipaddress
import re
import os

security = HTTPBasic()

# Load environment variables
CAMERA_IP_MAPPING = json.loads(os.getenv("CAMERA_IP_MAPPING", "{}"))
LOCATION_USER_PASS_MAPPING = json.loads(os.getenv("LOCATION_USER_PASS_MAPPING", "{}"))
CAMERA_LOCATION_MAPPING = json.loads(os.getenv("CAMERA_LOCATION_MAPPING", "{}"))
SCRIPTED_IP_MAPPING = json.loads(os.getenv("SCRIPTED_IP_MAPPING", "{}"))

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

def normalize_and_validate_ip(ip: str) -> str:
    """Strip port if present, validate IP, or return partial prefix for matching."""
    if not ip:
        return ""

    # Remove port if present (e.g., '192.168.1.1:8080' -> '192.168.1.1')
    ip = ip.strip().split(":")[0]

    # Allow pattern like '142.32.' (partial IP) — we'll treat that as valid
    # This regex ensures it matches "X.Y." or "X.Y.Z." but not "X.Y.Z.W"
    # For full IP validation, ipaddress.ip_address handles it.
    if re.match(r"^\d{1,3}\.\d{1,3}\.$", ip) or re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.$", ip):
        return ip

    # Validate full IP
    try:
        ipaddress.ip_address(ip)
        return ip
    except ValueError:
        return ""   # Invalid IP gets blanked out

async def update_credentials_periodically():
    while True:
        try:
            logger.info("Refreshing camera details from DB...")
            creds = get_all_from_db()

            if creds:
                CREDENTIAL_CACHE.clear()
                CREDENTIAL_CACHE.extend(creds)
                logger.info("Updated %d camera details.", len(creds))
        except Exception as e:
            logger.error(f"Error updating camera details: {e}")
        await asyncio.sleep(30)

def start_credential_refresh_task():
    return asyncio.create_task(update_credentials_periodically())

def get_data_from_db():
    try:
        logger.info("Initializing camera details from DB...")
        creds = get_all_from_db()

        if creds:
            CREDENTIAL_CACHE.clear()
            CREDENTIAL_CACHE.extend(creds)
    except Exception as e:
        logger.error(f"Error initializing camera details: {e}")

def validate_id_and_get_camera_record(data: list, camera_id: str) -> dict:
    """
    Validates the camera_id against DB records and retrieves the full camera record.
    """
    try:
        camera_id_int = int(camera_id)
    except ValueError:
        logger.error("Invalid camera ID format: %s. Must be an integer.", camera_id)
        raise ValueError("Unauthorized or unknown camera ID")

    for record in data:
        if record.get("ID") == camera_id_int:
            return record

    logger.error("No matching record found for camera ID: %s", camera_id)
    raise ValueError("Unauthorized or unknown camera ID")

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("forwarded")
    if forwarded:
        first = forwarded.split(",")[0].strip() 
        for_part = first.split(";")[0]
        if for_part.lower().startswith("for="):
            return for_part[4:]
        return for_part
    return request.client.host if request.client else "unknown"

def verify_credentials(credentials: HTTPBasicCredentials, expected_creds: dict) -> bool:
    return (
        secrets.compare_digest(credentials.username, expected_creds["username"]) and
        secrets.compare_digest(credentials.password, expected_creds["password"])
    )

def convert_camera_json_to_db_data(camera_ip_map: dict) -> list[dict]:
    location_map = json.loads(os.getenv("CAMERA_LOCATION_MAPPING", "{}"))

    db_data = []
    for cam_id_str, ip in camera_ip_map.items():
        try:
            cam_id_int = int(cam_id_str)
        except ValueError:
            logger.warning("Skipping non-integer camera ID in CAMERA_IP_MAPPING: %s", cam_id_str)
            continue

        db_data.append({
            'ID': cam_id_int,
            'Cam_InternetFTP_Folder': 'https://placeholder.com/default/path',
            'Cam_InternetFTP_Filename': f"{cam_id_str}.jpg",
            'Cam_LocationsRegion': location_map.get(cam_id_str, 'Unknown'),
            'Cam_MaintenancePublic_IP': ip
        })

    return db_data


async def authenticate_request(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security, use_cache=False),
) -> dict:
    if not CREDENTIAL_CACHE:
        get_data_from_db()

    db_data = CREDENTIAL_CACHE if CREDENTIAL_CACHE else convert_camera_json_to_db_data(CAMERA_IP_MAPPING)

    if not db_data:
        logger.error("Credential cache is empty after DB load and fallback. Cannot authenticate.")
        raise HTTPException(status_code=500, detail="Server configuration error: Camera data unavailable.")

    content_disposition = request.headers.get("content-disposition")
    if not (content_disposition and "filename=" in content_disposition):
        logger.error("Request missing 'content-disposition' header with filename. Discarding.")
        raise HTTPException(status_code=200, detail="Image file is required (missing filename in Content-Disposition)")

    filename = content_disposition.split("filename=")[-1].strip('"')
    camera_id = os.path.splitext(filename)[0]

    client_ip = get_client_ip(request)
    logger.info("Incoming request from IP=%s for camera-id=%s", client_ip, camera_id)

    is_scripted_request = False
    for scripted_name, scripted_ip_pattern in SCRIPTED_IP_MAPPING.items():
        normalized_scripted_ip = normalize_and_validate_ip(scripted_ip_pattern)
        if normalized_scripted_ip and client_ip.startswith(normalized_scripted_ip):
            is_scripted_request = True
            logger.info("Request from known scripted IP pattern '%s' (%s) detected for camera %s.", scripted_ip_pattern, scripted_name, camera_id)
            break

    if is_scripted_request:
        # Enforce HTTPS for scripted uploads using Forwarded header
        forwarded = request.headers.get("forwarded", "")
        proto = ""
        for part in forwarded.split(";"):
            if part.strip().startswith("proto="):
                proto = part.strip().split("=")[1].lower()
                break
        if proto != "https":
            logger.warning("Scripted camera %s attempted upload over non-HTTPS protocol: %s", camera_id, proto or "missing")
            raise HTTPException(status_code=403, detail="Scripted uploads must use HTTPS")
        scripted_region_key = "Scripted"
        expected_creds_scripted = LOCATION_USER_PASS_MAPPING.get(scripted_region_key)

        if not expected_creds_scripted:
            logger.warning(f"No '{scripted_region_key}' credentials configured in LOCATION_USER_PASS_MAPPING for scripted uploads.")
            record_auth_failure()
            raise HTTPException(status_code=401, detail=f"Scripted upload credentials not configured for '{scripted_region_key}'")

        if not (credentials and verify_credentials(credentials, expected_creds_scripted)):
            logger.warning("Invalid credentials for scripted camera %s from IP %s.", camera_id, client_ip)
            record_auth_failure()
            raise HTTPException(status_code=401, detail="Invalid credentials for scripted upload")

        logger.info(f"Successfully authenticated scripted camera {camera_id}.")
        record_ip_success()
        record_auth_success()

        # Return full DB record including FTP config for scripted cams
        try:
            camera_record = validate_id_and_get_camera_record(db_data, camera_id)
        except ValueError as e:
            logger.error("Validation Error for scripted camera %s: %s", camera_id, str(e))
            raise HTTPException(status_code=400, detail="Unauthorized or unknown camera ID")

        camera_record_copy = camera_record.copy()
        camera_record_copy["ID"] = str(camera_record_copy["ID"])
        camera_record_copy["ip_address"] = client_ip
        camera_record_copy["is_scripted"] = True

        return camera_record_copy

    else:
        try:
            camera_record = validate_id_and_get_camera_record(db_data, camera_id)
            region = camera_record.get("Cam_LocationsRegion", "").strip()
            raw_ip = camera_record.get("Cam_MaintenancePublic_IP", "").strip()
            ip_address = normalize_and_validate_ip(raw_ip)

        except ValueError as e:
            logger.error(f"Validation Error for {filename}: {e}. Discarding image.")
            record_ip_failure()
            record_auth_failure()
            raise HTTPException(status_code=400, detail="Unauthorized or unknown camera ID")

        expected_creds = LOCATION_USER_PASS_MAPPING.get(region)

        if ip_address:
            if ip_address.endswith("."):
                if not client_ip.startswith(ip_address):
                    logger.warning("Partial IP mismatch for %s: expected prefix %s, got %s", camera_id, ip_address, client_ip)
                    record_ip_failure()
                    record_auth_failure()
                    raise HTTPException(status_code=401, detail="IP mismatch")
            elif client_ip != ip_address:
                logger.warning("IP mismatch for %s: expected %s, got %s", camera_id, ip_address, client_ip)
                record_ip_failure()
                record_auth_failure()
                raise HTTPException(status_code=401, detail="IP mismatch")
        else:
            logger.info(f"No IP restriction for camera {camera_id} (Cam_MaintenancePublic_IP is empty/None). Skipping IP validation.")
        record_ip_success()

        if not expected_creds:
            logger.warning("No credentials configured for location '%s' (camera %s).", region, camera_id)
            record_auth_failure()
            raise HTTPException(status_code=401, detail="Credential mismatch for camera location")

        if not verify_credentials(credentials, expected_creds):
            logger.warning("Invalid credentials for camera %s from IP %s. Expected credentials for region %s", camera_id, client_ip, region)
            record_auth_failure()
            raise HTTPException(status_code=401, detail="Invalid credentials for camera")

        logger.info(f"Successfully authenticated camera {camera_id}.")
        record_auth_success()

        camera_record_copy = camera_record.copy()
        camera_record_copy["ID"] = str(camera_record_copy["ID"])
        camera_record_copy["ip_address"] = client_ip
        camera_record_copy["is_scripted"] = False

        return camera_record_copy
