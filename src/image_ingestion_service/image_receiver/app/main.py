from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import JSONResponse
import logging
from fastapi import File, UploadFile
from PIL import Image
from io import BytesIO
from fastapi import Header
from datetime import datetime
from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
import uuid
from prometheus_fastapi_instrumentator import Instrumentator
from .auth import authenticate_request, LOCATION_USER_PASS_MAPPING, start_credential_refresh_task, record_rabbitmq_failure, record_rabbitmq_success
from contextlib import asynccontextmanager
from fastapi_limiter import FastAPILimiter
import redis.asyncio as redis
from contextvars import ContextVar
import os
from fastapi_limiter.depends import RateLimiter
from contextlib import asynccontextmanager
from fastapi import Request, HTTPException, status
from fastapi.security.utils import get_authorization_scheme_param

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

    # # Rate limiter
    # redis_client = await redis.from_url("redis://redis", encoding="utf8", decode_responses=True)
    # await FastAPILimiter.init(redis_client)

    yield
    # Shutdown
    task.cancel()
    # await redis.close()

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

async def get_cam_key_from_filename(request: Request):
    filename = filename_context.get()
    cam_id = os.path.splitext(filename)[0]
    return cam_id

def cam_rate_limit_dep():
    return RateLimiter(times=1, seconds=20, identifier=get_cam_key_from_filename)

# For debugging purposes
@app.middleware("http")
async def log_headers(request: Request, call_next):
    if request.method == "POST":
        print("POST Request Headers:", dict(request.headers))
    response = await call_next(request)
    return response
    # pass


# Health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")


@app.get("/api/images")
async def index():
    return JSONResponse(
        status_code=200,
        content={"message": "Image upload endpoint is reachable via GET"}
    )

@app.get("/")
async def index():
    return JSONResponse(
        status_code=200,
        content={"message": "Image upload endpoint is reachable via GET root"}
    )

@app.post("/api/images")
async def receive_image(request: Request, 
                        auth_data=Depends(authenticate_request),
                        ):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="No image data received")

    # Extract filename from Content-Disposition header
    content_disposition = request.headers.get("content-disposition")
    filename = "123.jpg"
    if content_disposition and "filename=" in content_disposition:
        filename = content_disposition.split("filename=")[-1].strip('"')
 
    camera_id = auth_data["camera_id"]
    image_bytes = await request.body()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="No image data received")

    if not is_jpg_image(image_bytes):
        logger.warning(f"Invalid image format")
        raise HTTPException(
            status_code=415,
            detail="The camera image is not in JPG/JPEG format."
        )
    
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{camera_id}_{timestamp}.jpg"

    try:
        await send_to_rabbitmq(image_bytes, filename, camera_id=camera_id)
        logger.info(f"Pushed to RabbitMQ from {camera_id}")
    except Exception as e:
        logger.error(f"Pushed to RabbitMQ failed from {camera_id}: {e}")
        record_rabbitmq_failure()
        raise HTTPException(status_code=500, detail="Failed to push image to RabbitMQ")

    try:
        result = await upload_to_ftp(image_bytes, filename, camera_id=camera_id)
        if not result:
            logger.error(f"FTP upload failed for {camera_id}")
            return Response(content="FTP upload failed", media_type="text/plain", status_code=200)
        logger.info(f"Pushed to FTP server from {camera_id}")
    except Exception as e:
        logger.error(f"Push to FTP failed from {camera_id}: {e}")
        return Response(content="FTP push failed", media_type="text/plain", status_code=200)  
    
    record_rabbitmq_success()

    return {
            "status": "Success", 
            "camera_id": camera_id,
            "filename": filename
        }
