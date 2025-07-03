from fastapi import FastAPI, HTTPException, Request, Response, Depends
import logging
from PIL import Image
from io import BytesIO
from datetime import datetime
from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
from prometheus_fastapi_instrumentator import Instrumentator
from .auth import authenticate_request, LOCATION_USER_PASS_MAPPING, start_credential_refresh_task, record_rabbitmq_failure, record_rabbitmq_success
from contextlib import asynccontextmanager
from contextvars import ContextVar
import os
from urllib.parse import urlparse # Import urlparse

logger = logging.getLogger(__name__)

def is_jpg_image(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.format.lower() in ("jpeg", "jpg")
    except Exception:
        return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = start_credential_refresh_task()

    yield
    # Shutdown
    task.cancel()

app = FastAPI(
    title="MOTT Image Ingestion Service",
    version="1.0.0",
    description="Handles image ingestion with auth per camera/location.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

filename_context: ContextVar[str] = ContextVar("filename_context", default="unknown")


@app.middleware("http")
async def log_headers(request: Request, call_next):
    if request.method == "POST":
        logger.debug("POST Request Headers: %s", dict(request.headers))

    response = await call_next(request)
    return response

# Health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")

@app.get("/")
@app.get("/api/images")
async def index():
    return Response(
        content="Image upload endpoint is reachable via GET",
        status_code=200,
        media_type="text/plain"
    )


@app.post("/api/images")
async def receive_image(request: Request,
                        auth_data=Depends(authenticate_request),
                        ):
    if "ID" not in auth_data:
        logger.error("Auth data missing 'ID' key")
        raise HTTPException(status_code=500, detail="Internal server error: Camera ID missing from authentication data.")

    camera_id = str(auth_data["ID"]) 

    image_bytes = await request.body()
    if not image_bytes:
        logger.error("No image data received for camera_id=%s", camera_id)
        return Response(content="No image data received", media_type="text/plain", status_code=200)

    if not is_jpg_image(image_bytes):
        logger.error("Invalid image format for camera_id=%s", camera_id)
        return Response(content="Invalid image format", media_type="text/plain", status_code=200)

    # Extract required info from auth_data
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
    rabbitmq_filename = f"{camera_id}_{timestamp}.jpg" # This is for RabbitMQ

    try:
        await send_to_rabbitmq(image_bytes, rabbitmq_filename, camera_id=camera_id)
        logger.info("Pushed to RabbitMQ for camera_id=%s with filename=%s", camera_id, rabbitmq_filename)
    except Exception as e:
        logger.error("Push to RabbitMQ failed for camera_id=%s: %s", camera_id, str(e), exc_info=True)
        record_rabbitmq_failure()
        return Response(content="Push to RabbitMQ failed", media_type="text/plain", status_code=200)

    try:
        # Pass the extracted path and filename to the FTP upload function
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
        content=f"Image received and processed successfully",
        media_type="text/plain",
        status_code=200
    )