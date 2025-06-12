from fastapi import FastAPI, Request, HTTPException
import httpx
import os
from fastapi import File, UploadFile
from PIL import Image
from io import BytesIO
from fastapi import Header
import logging
import sys
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

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

PASSTHROUGH_URL = os.getenv("PASSTHROUGH_URL")

app = FastAPI()

# Metrics endpoint
Instrumentator().instrument(app).expose(app)

# Health check endpoint
@app.get("/healthz")
async def health_check():
    return {"status": "ok"}

# Image ingest endpoint
@app.post("/upload")
async def receive_image(request: Request,
                        image: UploadFile = File(...),
                        camera_id: str = Header(...)
                        ):
    client_ip = request.headers.get("x-real-ip") or request.client.host

    successful_auth_counter.inc()

    if not image.content_type.startswith("image/"):
        logger.warning(f"Invalid image type from {camera_id} ({client_ip}): {image.content_type}")
        raise HTTPException(status_code=400, detail="Only image uploads allowed")
    
    if not camera_id:
        logger.warning(f"Camera connection failed from {client_ip}: Missing camera_id")
        raise HTTPException(status_code=400, detail="camera_id header missing")

    image_bytes = await image.read()

    if not is_jpg_image(image_bytes):
        logger.warning(f"Camera image failed from {client_ip}: invalid format ({image.content_type})")
        raise HTTPException(
            status_code=415,
            detail="The camera image is not in JPG/JPEG format."
        )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            PASSTHROUGH_URL,
            content=image_bytes,
            headers={"Content-Type": image.content_type,
                    "camera_id": camera_id
                }
        )
    
    # # Unauthorized IP (TBD)
    # unsuccessful_ip_counter.inc()

    # # Failed auth (TBD)
    # unsuccessful_auth_counter.inc()

    if response.status_code != 200:
        logger.info(f"Camera image  from {client_ip} passed through failed. Response: {response.status_code}")
        
        rabbitmq_push_fail_counter.inc()
    else:
        logger.info(f"Camera image  from {client_ip} passed through successfully. Response: {response.status_code}")
        rabbitmq_push_success_counter.inc()

    return {"status": "received", "passthrough_status": response.status_code}
