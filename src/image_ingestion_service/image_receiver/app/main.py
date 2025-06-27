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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from http import HTTPStatus


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



from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

class LogResponseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        excluded_paths = ["/api/healthz", "/api/metrics"]

        # Skip logging for excluded paths
        if path in excluded_paths:
            return await call_next(request)

        response = await call_next(request)

        # Read and buffer the body
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        # Create new response with same content
        new_response = StarletteResponse(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )

        # Log status and headers
        logger.info(f"Response Status: {new_response.status_code} {HTTPStatus(new_response.status_code).phrase}")
        logger.info(f"Response Headers: {dict(new_response.headers)}")

        return new_response



app = FastAPI(
    title="MOTT Image Ingestion Service",
    version="1.0.0",
    description="Handles image ingestion with auth per camera/location.",
    docs_url="/docs", 
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    # lifespan=lifespan,
)

app.add_middleware(LogResponseMiddleware)

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
        auth_header = request.headers.get("authorization")

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
    return Response(
        content="<p>Image upload endpoint is reachable via GET</p>",
        status_code=200,
        media_type="text/html"
    )

@app.get("/")
async def index():
    return Response(
        content="<p>Image upload endpoint is reachable via GET root</p>",
        status_code=200,
        media_type="text/html"
    )

@app.post("/api/images")
async def receive_image(request: Request):
    auth_header = request.headers.get("authorization")
    logger.info(f"Checking to see if Authorization header exists: {auth_header}")
    if not auth_header or not auth_header.lower().startswith("basic "):
        logger.info(f"Confirmed, there is no authorization header or it is not Basic auth")
        response = Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Login Required"'},
            media_type="text/html",
        )
        return response
    
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

    response = Response(
        content="Upload successful",
        status_code=200,
        media_type="text/html",
    )
    return response
