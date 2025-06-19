from fastapi import FastAPI, Request, HTTPException, Depends
import logging
from fastapi import File, UploadFile
from PIL import Image
from io import BytesIO
from fastapi import Header
from datetime import datetime
from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
import uuid
from typing import Optional
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from .auth import authenticate_request, CAMERA_IP_MAPPING, LOCATION_USER_PASS_MAPPING

logger = logging.getLogger(__name__)

# Counters for monitoring in Sysdig
successful_auth_counter = Counter("successful_auth_total", "Count of successful authentications")
unsuccessful_ip_counter = Counter("unsuccessful_ip_total", "Count of requests from unauthorized IPs")
unsuccessful_auth_counter = Counter("unsuccessful_auth_total", "Count of failed authentications")
rabbitmq_push_fail_counter = Counter("rabbitmq_push_fail_total", "Count of failed pushes to RabbitMQ")
rabbitmq_push_success_counter = Counter("rabbitmq_push_success_total", "Count of successful pushes to RabbitMQ")


def is_jpg_image(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.format.lower() in ("jpeg", "jpg")
    except Exception:
        return False


app = FastAPI(
    title="MOTT Image Ingestion Service",
    version="1.0.0",
    description="Handles image ingestion with auth per camera/location.",
    docs_url="/docs", 
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Health check endpoint
@app.get("/api/healthz")
async def health_check():
    return {"status": "ok"}

# Metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")


# Image ingest endpoint
@app.post("/api/images")
async def receive_image(request: Request,
                        image: UploadFile = File(...),
                        camera_id: str = Header(...),
                        auth_data=Depends(authenticate_request),
                        ):
    successful_auth_counter.inc()

    client_ip = auth_data["client_ip"]
    expected_ip = CAMERA_IP_MAPPING.get(camera_id)
    if client_ip != expected_ip:
        unsuccessful_ip_counter.inc()

    camera_location: Optional[str] = Header(None, alias="camera-location"),
    
    expected_creds = LOCATION_USER_PASS_MAPPING.get(camera_location)
    if not expected_creds:
        unsuccessful_auth_counter.inc()

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
    except Exception as e:
        logger.error(f"Push to RabbitMQ failed from {camera_id}: {e}")
        rabbitmq_push_fail_counter.inc()
        raise HTTPException(status_code=500, detail="Failed to push image to RabbitMQ")

    try:
        await upload_to_ftp(image_bytes, filename, camera_id=camera_id)
    except Exception as e:
        logger.error(f"Push to FTP failed from {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to push image to FTP")     
    
    rabbitmq_push_success_counter.inc()

    return {
            "status": "forwarded", 
            "camera_id": camera_id,
            "filename": filename
        }
