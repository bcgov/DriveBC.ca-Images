from fastapi import FastAPI, HTTPException, Depends, Request, Response
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
from contextlib import asynccontextmanager
from fastapi import Request, HTTPException
from fastapi import FastAPI, Request, Response


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
        print("POST Request Headers:", dict(request.headers))

    response = await call_next(request)
    return response

# Health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")


@app.get("/api/images")
async def index():
    return Response(
        content="Image upload endpoint is reachable via GET",
        status_code=200,
        media_type="text/plain"
    )

@app.get("/")
async def index():
    return Response(
        content="Image upload endpoint is reachable via GET root",
        status_code=200,
        media_type="text/plain"
    )

@app.post("/api/images")
async def receive_image(request: Request, 
                        auth_data=Depends(authenticate_request),
                        ):
    
    # Extract filename from Content-Disposition header
    content_disposition = request.headers.get("content-disposition")
    filename = "123.jpg"
    if content_disposition and "filename=" in content_disposition:
        filename = content_disposition.split("filename=")[-1].strip('"')
 
    camera_id = auth_data["camera_id"]
    image_bytes = await request.body()
    if not image_bytes:
        logger.error(f"No image data received")
        return Response(content="No image data received", media_type="text/plain", status_code=200)  

    if not is_jpg_image(image_bytes):
        logger.error(f"Invalid image format")
        return Response(content="Invalid image format", media_type="text/plain", status_code=200)  
    
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{camera_id}_{timestamp}.jpg"

    try:
        await send_to_rabbitmq(image_bytes, filename, camera_id=camera_id)
        logger.info(f"Pushed to RabbitMQ")
    except Exception as e:
        logger.error(f"Pushed to RabbitMQ failed")
        record_rabbitmq_failure()
        return Response(content="Push to RabbitMQ failed", media_type="text/plain", status_code=200)  

    try:
        result = await upload_to_ftp(image_bytes, filename, camera_id=camera_id)
        if not result:
            return Response(content="FTP upload failed", media_type="text/plain", status_code=200)
        logger.info(f"Pushed to FTP server from {camera_id}")
    except Exception as e:
        logger.error(f"FTP push failed")
        return Response(content="FTP push failed", media_type="text/plain", status_code=200)  
    
    record_rabbitmq_success()

    return Response(
        content=f"Image received and processed successfully for camera {camera_id} with filename {filename}",
        media_type="text/plain",
        status_code=200
    )
