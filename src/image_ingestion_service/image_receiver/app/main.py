import os
import sys
import uuid
import logging
import asyncio
from io import BytesIO
from datetime import datetime, timezone
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Tuple, Optional

from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from prometheus_fastapi_instrumentator import Instrumentator
from PIL import Image, UnidentifiedImageError

from .auth import (
    authenticate_request, get_client_ip,
    LOCATION_USER_PASS_MAPPING,
    update_credentials_periodically,
    record_processing_failure, record_processing_success
)
from .rabbitmq import send_to_rabbitmq


# -------------------- Request ID Context for Logging --------------------

# A context variable used to store the request ID per request.
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default=None)

# Retrieve the current request ID or fallback to "N/A"
def get_request_id() -> str:
    return request_id_ctx_var.get() or "N/A"


# -------------------- Logging Setup --------------------

# Custom logging filter that injects the request ID into every log record
class RequestIdLogFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        return True

# Initialize and configure structured logging
def setup_logging():
    log_level = os.getenv("PYTHON_LOG_LEVEL", "INFO").upper()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdLogFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.addHandler(handler)

    # Clear default handlers for Uvicorn to avoid duplicate logging
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

setup_logging()
logger = logging.getLogger(__name__)


# -------------------- Middleware --------------------

# Middleware to attach a unique request ID to each request for traceability
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())
        request_id_ctx_var.set(req_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# -------------------- Utility Functions --------------------

def _get_max_file_size() -> int:
    """
    Reads the max file size from the environment variable MAX_FILE_SIZE_BYTES.
    Falls back to a safe default if the variable is not set or is invalid.
    """
    # Define a sensible default value (e.g., 5MB)
    default_size = 5 * 1024 * 1024
    max_size_str = os.getenv("MAX_FILE_SIZE_BYTES")
    if not max_size_str:
        logger.info(f"MAX_FILE_SIZE_BYTES not set, using default of {default_size} bytes.")
        return default_size
    try:
        # Convert the environment variable (which is always a string) to an integer.
        size = int(max_size_str)
        logger.info(f"MAX_FILE_SIZE_BYTES loaded from environment: {size} bytes.")
        return size
    except (ValueError, TypeError):
        # This handles cases where the variable is set to a non-numeric string (e.g., "5MB").
        logger.warning(
            f"Invalid value '{max_size_str}' for MAX_FILE_SIZE_BYTES. "
            f"It must be an integer. Falling back to default of {default_size} bytes."
        )
        return default_size
    
MAX_FILE_SIZE = _get_max_file_size()    

# Validate that the image is a JPEG and under the max size limit
def validate_jpg_image(image_bytes: bytes) -> Tuple[bool, Optional[str]]:
    if not image_bytes:
        return False, "No image data received"
    if len(image_bytes) > MAX_FILE_SIZE:
        return False, "Image exceeds maximum size limit"
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.format.lower() not in ("jpeg", "jpg"):
                return False, "Unsupported image format, only JPEG is allowed"
    except UnidentifiedImageError:
        return False, "Invalid or corrupt image data"
    except IOError:
        return False, "Cannot read image data"
    return True, None

# Normalize the FTP folder path to a POSIX-compliant format
def get_normalized_ftp_path(folder_url: str) -> str:
    parsed_url = urlparse(folder_url)
    ftp_path = parsed_url.path
    if not ftp_path.startswith('/'):
        ftp_path = '/' + ftp_path
    return os.path.normpath(ftp_path)


# -------------------- FastAPI Application Setup --------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(update_credentials_periodically())
    yield
    task.cancel()

app = FastAPI(
    title="MOTT Image Ingestion Service",
    version="1.0.0",
    description="Handles image ingestion with auth per camera/location.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    middleware=[Middleware(RequestIdMiddleware)]
)

# Enable Prometheus metrics endpoint at /api/metrics
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")


# -------------------- Middleware Route Logging --------------------

# Logs POST requests including headers if DEBUG logging is enabled
@app.middleware("http")
async def log_post_request_details(request: Request, call_next):
    if request.method == "POST" and logger.isEnabledFor(logging.DEBUG):
        client_ip = get_client_ip(request)
        logger.debug(f"Incoming POST request from IP={client_ip}")
        logger.debug(f"POST Request Headers: {dict(request.headers)}")
    return await call_next(request)


# -------------------- Routes --------------------

# Basic health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Informational endpoint confirming image upload availability
@app.get("/")
@app.get("/api/images")
async def index():
    return Response(
        content="Image upload endpoint is reachable via GET",
        status_code=200,
        media_type="text/plain"
    )

# Main image ingestion route
@app.post("/api/images")
async def receive_image(request: Request, auth_data=Depends(authenticate_request)):
    camera_id = str(auth_data.get("ID", ""))
    TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        logger.warning(f"Content-Length ({content_length}) exceeds max size for camera_id={camera_id}")
        record_processing_failure()
        return Response(f"Image exceeds maximum size limit of {MAX_FILE_SIZE} bytes", status_code=413) # Payload Too Large

    image_bytes = bytearray()
    try:
        async for chunk in request.stream():
            image_bytes.extend(chunk)
            if len(image_bytes) > MAX_FILE_SIZE:
                logger.warning(f"Streamed image exceeds max size for camera_id={camera_id}")
                record_processing_failure()
                return Response(f"Image exceeds maximum size limit of {MAX_FILE_SIZE} bytes", status_code=413)
    except ClientDisconnect:
        logger.warning(f"Client disconnected before sending full image for camera_id={camera_id}. Proceeding with partial data.")

    if not image_bytes:
        logger.warning(f"No image data received for camera_id={camera_id}")
        record_processing_failure()
        return Response(content="No image data received", media_type="text/plain", status_code=400)

    # Validate the received image
    valid, error = validate_jpg_image(image_bytes)
    if not valid:
        logger.warning(f"Validation failed for camera_id={camera_id}: {error}")
        record_processing_failure()
        return Response(error, media_type="text/plain", status_code=400)

    # Extract FTP configuration from the auth metadata
    ftp_folder_url = auth_data.get("Cam_InternetFTP_Folder")
    ftp_target_filename = auth_data.get("Cam_InternetFTP_Filename")

    if not ftp_folder_url or not ftp_target_filename:
        logger.warning(f"Missing FTP configuration for camera_id={camera_id}")
        record_processing_failure()
        return Response(content="Missing FTP configuration", media_type="text/plain", status_code=200)

    # Normalize path and generate timestamped filename
    ftp_path = get_normalized_ftp_path(ftp_folder_url)

    timestamp_header = request.headers.get("timestamp")

    if timestamp_header:
        try:
            # Only allow compact UTC format: 20250819T142345Z
            ts = datetime.strptime(timestamp_header, TIMESTAMP_FORMAT)
            timestamp = ts.strftime(TIMESTAMP_FORMAT)
            logger.info(f"Using timestamp header for camera_id={camera_id} with timestamp={timestamp}")
        except ValueError:
            logger.warning(
                f"Invalid timestamp header for camera_id={camera_id}, "
                "falling back to current UTC time."
            )
            timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    else:
        timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)

    rabbitmq_filename = f"{camera_id}_{timestamp}.jpg"

    # --- Send image to RabbitMQ ---
    try:
        await send_to_rabbitmq(
            image_bytes,
            rabbitmq_filename,
            camera_id=camera_id,
            timestamp=timestamp,
            ftp_path=ftp_path,
            ftp_target_filename=ftp_target_filename
        )
        logger.info(f"Pushed to RabbitMQ for camera_id={camera_id} with filename={rabbitmq_filename}")
    except Exception as e:
        logger.error(f"Push to RabbitMQ failed for camera_id={camera_id}: {e}", exc_info=False)
        record_processing_failure()
        return Response(
            content="Image processed with errors: Push to RabbitMQ failed",
            media_type="text/plain",
            status_code=500
        )

    # All operations succeeded
    logger.info(f"Successfully processed image for camera_id={camera_id}")
    record_processing_success()
    return Response(content="Image received and processed successfully", media_type="text/plain", status_code=200)

