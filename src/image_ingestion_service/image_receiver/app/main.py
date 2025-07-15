import logging
import sys
import os
from contextvars import ContextVar
from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from PIL import Image
from io import BytesIO
from datetime import datetime
from urllib.parse import urlparse
import uuid

from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
from prometheus_fastapi_instrumentator import Instrumentator
from .auth import (
    authenticate_request, LOCATION_USER_PASS_MAPPING,
    start_credential_refresh_task, record_rabbitmq_failure,
    record_rabbitmq_success, get_client_ip
)
from contextlib import asynccontextmanager

# --- Request ID context ---
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default=None)

def get_request_id() -> str:
    return request_id_ctx_var.get() or "N/A"

class RequestIdLogFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        return True

# --- Logging Setup ---
log_level = os.getenv("PYTHON_LOG_LEVEL", "INFO").upper()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s")

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
handler.addFilter(RequestIdLogFilter())

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.setLevel(getattr(logging, log_level, logging.INFO))
root_logger.addHandler(handler)

# Ensure no duplicates from uvicorn
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    log = logging.getLogger(logger_name)
    log.handlers.clear()
    log.propagate = True

logger = logging.getLogger(__name__)

# --- Middleware for setting request_id ---
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())
        request_id_ctx_var.set(req_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

# --- FastAPI Setup ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = start_credential_refresh_task()
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

@app.middleware("http")
async def log_post_request_details(request: Request, call_next):
    if request.method == "POST" and logger.isEnabledFor(logging.DEBUG):
        client_ip = get_client_ip(request)
        logger.debug(f"Incoming POST request from IP={client_ip}")
        logger.debug(f"POST Request Headers: {dict(request.headers)}")
    response = await call_next(request)
    return response

@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")

@app.get("/")
@app.get("/api/images")
async def index():
    return Response(
        content="Image upload endpoint is reachable via GET",
        status_code=200,
        media_type="text/plain"
    )

def is_jpg_image(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.format.lower() in ("jpeg", "jpg")
    except Exception:
        return False

@app.post("/api/images")
async def receive_image(request: Request, auth_data=Depends(authenticate_request)):
    if "ID" not in auth_data:
        logger.error("Auth data missing 'ID' key")
        raise HTTPException(status_code=500, detail="Internal server error: Camera ID missing from authentication data.")

    camera_id = str(auth_data["ID"])

    image_bytes = bytearray()

    try:
        async for chunk in request.stream():
            image_bytes.extend(chunk)
    except ClientDisconnect:
        logger.warning(f"Client disconnected before sending full image for camera_id={camera_id}. Proceeding with partial data.")

    if not image_bytes:
        logger.error("No image data received for camera_id=%s", camera_id)
        return Response(content="No image data received", media_type="text/plain", status_code=500)

    if not is_jpg_image(image_bytes):
        logger.error("Invalid image format for camera_id=%s", camera_id)
        return Response(content="Invalid image format", media_type="text/plain", status_code=500)

    ftp_folder_url = auth_data.get("Cam_InternetFTP_Folder")
    ftp_target_filename = auth_data.get("Cam_InternetFTP_Filename")

    if not ftp_folder_url or not ftp_target_filename:
        logger.error("Missing FTP configuration for camera_id=%s", camera_id)
        return Response(content="Missing FTP configuration", media_type="text/plain", status_code=200)

    parsed_url = urlparse(ftp_folder_url)
    ftp_path = parsed_url.path
    if not ftp_path.startswith('/'):
        ftp_path = '/' + ftp_path
    ftp_path = os.path.normpath(ftp_path)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rabbitmq_filename = f"{camera_id}_{timestamp}.jpg"

    try:
        await send_to_rabbitmq(image_bytes, rabbitmq_filename, camera_id=camera_id)
        logger.info("Pushed to RabbitMQ for camera_id=%s with filename=%s", camera_id, rabbitmq_filename)
    except Exception as e:
        logger.error("Push to RabbitMQ failed for camera_id=%s: %s", camera_id, str(e), exc_info=True)
        record_rabbitmq_failure()
        return Response(content="Push to RabbitMQ failed", media_type="text/plain", status_code=200)

    try:
        result = await upload_to_ftp(image_bytes, ftp_target_filename, camera_id=camera_id, target_ftp_path=ftp_path)
        if not result:
            logger.error("FTP upload failed for camera_id=%s to path %s/%s", camera_id, ftp_path, ftp_target_filename)
            return Response(content="FTP upload failed", media_type="text/plain", status_code=200)
        logger.info("Pushed to FTP server for camera_id=%s to path %s/%s", camera_id, ftp_path, ftp_target_filename)
    except Exception as e:
        logger.error("FTP push failed for camera_id=%s: %s", camera_id, str(e), exc_info=True)
        return Response(content="FTP push failed", media_type="text/plain", status_code=200)

    record_rabbitmq_success()
    logger.info("Successfully finished processing image for camera_id=%s", camera_id)

    return Response(
        content="Image received and processed successfully",
        media_type="text/plain",
        status_code=200
    )