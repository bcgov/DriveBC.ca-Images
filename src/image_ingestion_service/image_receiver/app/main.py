from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.responses import JSONResponse
import logging
from PIL import Image
from io import BytesIO
from fastapi import Header
from datetime import datetime
from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
from prometheus_fastapi_instrumentator import Instrumentator
from .auth import authenticate_request, LOCATION_USER_PASS_MAPPING, start_credential_refresh_task, record_rabbitmq_failure, record_rabbitmq_success, get_credentials
from contextlib import asynccontextmanager
import redis.asyncio as redis
from contextvars import ContextVar
import os
from contextlib import asynccontextmanager
from fastapi import Request, HTTPException
from fastapi.security.utils import get_authorization_scheme_param

import hashlib
import time
import base64
from fastapi import FastAPI, Request, Response
from typing import Optional
import re


USERNAME = "axis_user"
PASSWORD = "axis_pass"
REALM = "AxisCamera"
QOP = "auth"

logger = logging.getLogger(__name__)

def is_jpg_image(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.format.lower() in ("jpeg", "jpg")
    except Exception:
        return False

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Startup
#     task = start_credential_refresh_task()

#     yield
#     # Shutdown
#     task.cancel()

app = FastAPI(
    title="MOTT Image Ingestion Service",
    version="1.0.0",
    description="Handles image ingestion with auth per camera/location.",
    docs_url="/docs", 
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    # lifespan=lifespan,
)

filename_context: ContextVar[str] = ContextVar("filename_context", default="unknown")

async def get_cam_key_from_filename(request: Request):
    filename = filename_context.get()
    cam_id = os.path.splitext(filename)[0]
    return cam_id

import base64
@app.middleware("http")
async def log_headers(request: Request, call_next):
    if request.method == "POST":
        print("POST Request Headers:", dict(request.headers))
        # Remove 'Basic ' prefix
        auth_header = request.headers.get("authorization")
        http_version = request.scope.get("http_version", "unknown")
        print(f"HTTP Version: {http_version}")

    # if auth_header:
    #     encoded = auth_header.split(" ")[1]
    #     # Decode here safely...
    # else:
    #     # Log, raise, or skip
    #     print("No Authorization header found")

    #     # Decode from Base64
    #     decoded_bytes = base64.b64decode(encoded)
    #     decoded_str = decoded_bytes.decode('utf-8')

    #     # Split into username and password
    #     username, password = decoded_str.split(':', 1)

    #     print(f"Username: {username}")
    #     print(f"Password: {password}")
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
    # auth_header = request.headers.get("authorization")
    # if not auth_header:
    #     print("No Authorization header found")
    #     return Response(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         content="Unauthorized",
    #         headers={"WWW-Authenticate": "Basic realm='AxisCamera'"},
    #         media_type="text/plain"
    #     )

    # if not validated:
    #     logger.warning("Unauthorized access attempt, discarding request")
    #     return Response(status_code=200, content="OK")

    if auth_data.status_code == 401:
        logger.warning("Unauthorized access attempt, discarding request")
        return Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content="Unauthorized",
            headers={"WWW-Authenticate": "Basic realm='AxisCamera'"},
            media_type="text/plain"
        )

    # authenticate_request_result = await authenticate_request(request)
    
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="No image data received")

    # Extract filename from Content-Disposition header
    content_disposition = request.headers.get("content-disposition")
    filename = "123.jpg"
    if content_disposition and "filename=" in content_disposition:
        filename = content_disposition.split("filename=")[-1].strip('"')
 
    # camera_id = auth_data["camera_id"]

    # camera_id = "343"
    camera_id = os.path.splitext(filename)[0]




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
            # logger.error(f"FTP upload failed for {camera_id}")
            return Response(content="FTP upload failed", media_type="text/plain", status_code=200)
        logger.info(f"Pushed to FTP server from {camera_id}")
    except Exception as e:
        # logger.error(f"Push to FTP failed from {camera_id}: {e}")
        return Response(content="FTP push failed", media_type="text/plain", status_code=200)  
    
    record_rabbitmq_success()

    return {
            "status": "Success", 
            "camera_id": camera_id,
            "filename": filename
        }





# def generate_nonce():
#     return base64.b64encode(hashlib.md5(str(time.time()).encode()).digest()).decode()

# def md5_hex(s: str) -> str:
#     return hashlib.md5(s.encode()).hexdigest()

# def parse_digest_header(header: str) -> dict:
#     digest_parts = {}
#     pattern = re.compile(r'(\b\w+\b)="?([^",]+)"?')
#     for match in pattern.finditer(header):
#         digest_parts[match.group(1)] = match.group(2)
#     return digest_parts

# @app.post("/api/images")
# async def receive_image(request: Request, 
#                         ):
#     auth_header: Optional[str] = request.headers.get("authorization")
#     print("Authorization header:", auth_header)
#     if not auth_header or not auth_header.startswith("Digest "):
#         nonce = generate_nonce()
#         # return Response(
#         #     status_code=401,
#         #     headers={
#         #         "WWW-Authenticate": f'Digest realm="{REALM}", nonce="{nonce}", qop="{QOP}"'
#         #     },
#         #     content="Unauthorized",
#         # )
#         return Response(
#             status_code=401,
#             headers={
#                 "WWW-Authenticate": (
#                     f'Digest realm="{REALM}", '
#                     f'nonce="{nonce}", '
#                     f'qop="{QOP}", '
#                     f'algorithm="MD5", '
#                     f'opaque="0000000000000000"'
#                 )
#             },
#             content="Unauthorized",
#     )

#     # Parse the Digest header
#     digest = parse_digest_header(auth_header[7:])  # Skip "Digest "

#     # Validate required fields
#     for field in ("username", "realm", "nonce", "uri", "response", "nc", "cnonce"):
#         if field not in digest:
#             logger.warning(f"Missing field in digest: {field}")
#             return Response(status_code=400, content=f"Missing field: {field}")

#     if digest["username"] != USERNAME or digest["realm"] != REALM:
#         logger.warning("Invalid username or realm in digest")
#         return Response(status_code=401, content="Invalid credentials")

#     # Calculate expected response
#     HA1 = md5_hex(f"{USERNAME}:{REALM}:{PASSWORD}")
#     HA2 = md5_hex(f"{request.method}:{digest['uri']}")
#     valid_response = md5_hex(
#         f"{HA1}:{digest['nonce']}:{digest['nc']}:{digest['cnonce']}:{QOP}:{HA2}"
#     )

#     if valid_response != digest["response"]:
#         logger.warning("Invalid response hash in digest")
#         return Response(status_code=401, content="Invalid response hash")

#     return {"message": "Digest auth success — image accepted"}
