from fastapi import FastAPI, HTTPException, Depends, Request
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

# Health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")

# bruce test
from fastapi import Request, HTTPException, status
from fastapi.security.utils import get_authorization_scheme_param
import base64

async def custom_basic_auth(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    scheme, credentials = get_authorization_scheme_param(auth_header)
    if scheme.lower() != "basic" or not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")

    try:
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
        print(f"DEBUG - Username: {username}, Password: {password}")  # Remove in production!
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid basic auth format")

    return username, password



# Image ingest endpoint
@app.post("/api/images")
async def receive_image(image: UploadFile = File(...),
                        # # bruce test
                        # auth_data=Depends(authenticate_request),

                        auth_data: tuple = Depends(custom_basic_auth)
                        # Use the rate limiter to limit requests per camera once Redis is set up
                        # _=Depends(cam_rate_limit_dep()),
                        ):
    username, password = auth_data
    print(f"Received credentials - Username: {username}, Password: {password}")
    

    # bruce test
    camera_id = "456" #auth_data["camera_id"]

    image_bytes = await image.read()
    if not is_jpg_image(image_bytes):
        logger.warning(f"Invalid image format ({image.content_type})")
        raise HTTPException(
            status_code=415,
            detail="The camera image is not in JPG/JPEG format."
        )
    
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{camera_id}_{timestamp}_{unique_id}.jpg"

    try:
        await send_to_rabbitmq(image_bytes, filename, camera_id=camera_id)
        logger.info(f"Pushed to RabbitMQ from {camera_id}")
    except Exception as e:
        logger.error(f"Pushed to RabbitMQ failed from {camera_id}: {e}")
        record_rabbitmq_failure()
        raise HTTPException(status_code=500, detail="Failed to push image to RabbitMQ")

    try:
        await upload_to_ftp(image_bytes, filename, camera_id=camera_id)
        logger.info(f"Push to FTP server from {camera_id}")
    except Exception as e:
        logger.error(f"Push to FTP failed from {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to push image to FTP")     
    
    record_rabbitmq_success()

    return {
            "status": "Success", 
            "camera_id": camera_id,
            "filename": filename
        }
