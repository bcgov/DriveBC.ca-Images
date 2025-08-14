import asyncio
import logging
import json
import secrets
import ipaddress
import re
import os
from typing import Optional, Dict

from fastapi import Request, Header, HTTPException, Response, status, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import Counter
from asyncio import Lock

from .db import get_all_from_db

# -------------------- Logger Setup --------------------
logger = logging.getLogger(__name__)

# -------------------- Helper Function to Load Mapping --------------------
def load_mapping_from_env(env_var: str, default: dict = None) -> dict:
    default = default or {}
    raw = os.getenv(env_var)
    if not raw:
        return default

    try:
        # First attempt: standard JSON
        parsed = json.loads(raw)

        # Handle double-encoded JSON (e.g., a JSON string inside a JSON string)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decoding failed for {env_var}: {e}")
    return default

# -------------------- Authentication Setup --------------------
security = HTTPBasic()

LOCATION_USER_PASS_MAPPING = load_mapping_from_env("LOCATION_USER_PASS_MAPPING")
SCRIPTED_IP_MAPPING = load_mapping_from_env("SCRIPTED_IP_MAPPING")

# In-memory cache of credentials fetched from the database
CREDENTIAL_CACHE: Dict[str, dict] = {}
CREDENTIAL_CACHE_LOCK = Lock()

# -------------------- Prometheus Counters --------------------
# These track various authentication and processing outcomes
successful_auth_counter = Counter("successful_auth_total", "Count of successful authentications")
unsuccessful_auth_counter = Counter("unsuccessful_auth_total", "Count of failed authentications")
successful_ip_counter = Counter("successful_ip_total", "Count of requests from authorized IPs")
unsuccessful_ip_counter = Counter("unsuccessful_ip_total", "Count of requests from unauthorized IPs")
unsuccessful_processing_counter = Counter("unsuccessful_processing_total", "Count of failed image processing attempts")
successful_processing_counter = Counter("successful_processing_total", "Count of successful image processing attempts")

# Increment helper functions
def record_auth_success(): successful_auth_counter.inc()
def record_auth_failure(): unsuccessful_auth_counter.inc()
def record_ip_success(): successful_ip_counter.inc()
def record_ip_failure(): unsuccessful_ip_counter.inc()
def record_processing_success(): successful_processing_counter.inc()
def record_processing_failure(): unsuccessful_processing_counter.inc()

# -------------------- Credential Refresh Task --------------------
async def update_credentials_periodically():
    """Background task to refresh credentials every 30 seconds."""
    while True:
        try:
            logger.info("Refreshing camera details from DB...")
            creds_list = get_all_from_db()
            if creds_list:
                new_cache = {str(record["ID"]): record for record in creds_list}
                async with CREDENTIAL_CACHE_LOCK:
                    CREDENTIAL_CACHE.clear()
                    CREDENTIAL_CACHE.update(new_cache)
                logger.info(f"Updated {len(new_cache)} camera details.")
        except Exception as e:
            logger.error(f"Error updating camera details: {e}")
        await asyncio.sleep(30)

async def get_cached_credentials():
    async with CREDENTIAL_CACHE_LOCK:
        return CREDENTIAL_CACHE.copy()

# -------------------- Initial Load of Credentials --------------------
def get_data_from_db():
    """One-time loading of credentials on startup or fallback."""
    try:
        logger.info("Initializing camera details from DB...")
        creds_list = get_all_from_db()
        if creds_list:
            # Build a dictionary with camera ID as the key
            new_cache = {str(record["ID"]): record for record in creds_list}
            CREDENTIAL_CACHE.clear()
            CREDENTIAL_CACHE.update(new_cache)
    except Exception as e:
        logger.error(f"Error initializing camera details: {e}")

# -------------------- Camera ID Validation --------------------
def validate_id_and_get_camera_record(data: dict, camera_id: str) -> dict:
    """Validate and return camera record based on numeric ID from the cache."""
    record = data.get(camera_id)
    if record:
        return record

    if not camera_id.isdigit():
        raise ValueError("Invalid camera ID format. Must be an integer.")
    
    raise ValueError("No matching record found for this camera ID")

# -------------------- IP & Protocol Extraction --------------------
def get_client_ip(request: Request) -> str:
    """Extract client IP from 'forwarded' header or request context."""
    forwarded = request.headers.get("forwarded")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        for_part = first.split(";")[0]
        if for_part.lower().startswith("for="):
            return for_part[4:]
        return for_part
    return request.client.host if request.client else "unknown"

def get_client_proto(request: Request) -> str:
    """Extract protocol (http/https) from 'forwarded' header."""
    forwarded = request.headers.get("forwarded", "")
    for forwarded_entry in forwarded.split(","):
        parts = forwarded_entry.strip().split(";")
        for part in parts:
            if part.strip().lower().startswith("proto="):
                return part.strip().split("=", 1)[1].lower()
    return "unknown"

# -------------------- IP Normalization -------------------- 
def normalize_and_validate_ip(ip: str) -> str:
    """Validate and normalize an IPv4 address or CIDR block,
    ignoring optional port if present. Returns normalized string or empty if invalid."""
    if not ip:
        return ""
    ip = ip.strip().split(":")[0] # Remove port if present
    try:
        if '/' in ip:
            network = ipaddress.IPv4Network(ip, strict=False)
            return str(network)
        else:
            address = ipaddress.IPv4Address(ip)
            return str(address)
    except ValueError:
        return ""        

# -------------------- IP & Credential Verification --------------------
def check_ip_match(client_ip: str, expected_ip: str) -> bool:
    """Check if client_ip matches expected_ip exactly or falls in expected CIDR block."""
    try:
        client_addr = ipaddress.ip_address(client_ip)
    except ValueError:
        logger.warning(f"Invalid client IP: {client_ip}")
        return False
    
    try:
        if '/' in expected_ip:
            # expected_ip is CIDR
            network = ipaddress.ip_network(expected_ip, strict=False)
            return client_addr in network
        else:
            # expected_ip is a single IP
            expected_addr = ipaddress.ip_address(expected_ip)
            return client_addr == expected_addr
    except ValueError:
        logger.warning(f"Invalid expected IP or CIDR: {expected_ip}")
        return False

def verify_credentials(credentials: HTTPBasicCredentials, expected_creds: dict) -> bool:
    """Secure comparison of credentials."""
    return (
        secrets.compare_digest(credentials.username, expected_creds["username"]) and
        secrets.compare_digest(credentials.password, expected_creds["password"])
    )

# -------------------- Record Fetch & Validation --------------------
def get_camera_record_and_validate(camera_id: str, db_data: list) -> dict:
    """Fetch camera record or raise HTTP 400."""
    try:
        return validate_id_and_get_camera_record(db_data, camera_id)
    except ValueError as e:
        record_auth_failure()
        logger.warning(f"Validation Error for camera {camera_id}: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

# -------------------- IP Authorization --------------------
def verify_ip_or_raise(client_ip: str, expected_ip: str, camera_id: str):
    """Validate client IP against expected, raise if mismatch."""
    if expected_ip:
        if not check_ip_match(client_ip, expected_ip):
            logger.warning(f"IP mismatch for {camera_id}: expected {expected_ip}, got {client_ip}")
            record_ip_failure()
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Basic"},
            )
        record_ip_success()
    else:
        record_ip_success()
        logger.info(f"No IP restriction for camera {camera_id}. Skipping IP validation.")

# -------------------- Credential Authorization --------------------
def verify_creds_or_raise(credentials: HTTPBasicCredentials, expected_creds: dict, camera_id: str):
    """Check credentials, log and raise if invalid."""
    if not expected_creds:
        logger.warning(f"No credentials configured for camera {camera_id}.")
        record_auth_failure()
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    if not verify_credentials(credentials, expected_creds):
        logger.warning(f"Invalid credentials for camera {camera_id}.")
        record_auth_failure()
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    record_auth_success()

# -------------------- Main Auth Function --------------------
async def authenticate_request(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security, use_cache=False),
) -> dict:
    """
    Authenticate image upload request:
    - Validate camera ID from filename in headers
    - Check IP and credentials
    - Return camera record
    """
    # Ensure we have credentials
    if not CREDENTIAL_CACHE:
        get_data_from_db()
    db_data = await get_cached_credentials()
    if not db_data:
        raise HTTPException(status_code=500, detail="Camera data unavailable.")

    # Extract filename from header to derive camera ID
    client_ip = get_client_ip(request)
    client_proto = get_client_proto(request)
    content_disposition = request.headers.get("content-disposition")
    if not content_disposition or "filename=" not in content_disposition:
        logger.warning(f"Request from IP={client_ip} has a missing or malformed Content-Disposition header.")
        record_auth_failure()
        raise HTTPException(status_code=400, detail="Missing or malformed Content-Disposition header")
    filename = content_disposition.split("filename=")[-1].strip('"')
    safe_basename = os.path.basename(filename)
    camera_id_raw = os.path.splitext(safe_basename)[0]
    camera_id = re.sub(r'[^a-zA-Z0-9_-]', '', camera_id_raw)[:20]
    if not camera_id:
        logger.warning(f"Request from IP={client_ip} has an invalid filename")
        record_auth_failure()
        raise HTTPException(status_code=400, detail="Invalid filename format")

    logger.info(f"Request from IP={client_ip} for camera={camera_id} using proto={client_proto}")

    # Handle scripted IPs (trusted automation)
    for scripted_name, ip_patterns in SCRIPTED_IP_MAPPING.items():
        # Ensure we always have a list, even if one IP is given
        if isinstance(ip_patterns, str):
            ip_patterns = [ip_patterns]

        for ip_pattern in ip_patterns:
            norm_ip = normalize_and_validate_ip(ip_pattern)
            if norm_ip and check_ip_match(client_ip, norm_ip):
                logger.info(f"Scripted request detected: {scripted_name}")
                creds = LOCATION_USER_PASS_MAPPING.get(scripted_name)
                verify_creds_or_raise(credentials, creds, camera_id)
                record_ip_success()

                record = get_camera_record_and_validate(camera_id, db_data)
                return {
                    **record,
                    "ID": str(record["ID"]),
                    "ip_address": client_ip,
                    "is_scripted": True
                }

    # Handle regular camera request
    record = get_camera_record_and_validate(camera_id, db_data)
    region = record.get("Cam_LocationsRegion", "").strip()
    
    expected_ip = normalize_and_validate_ip((record.get("Cam_MaintenancePublic_IP") or "").strip())

    verify_ip_or_raise(client_ip, expected_ip, camera_id)
    creds = LOCATION_USER_PASS_MAPPING.get(region)
    verify_creds_or_raise(credentials, creds, camera_id)

    return {
        **record,
        "ID": str(record["ID"]),
        "ip_address": client_ip,
        "is_scripted": False
    }