from io import BytesIO
import json
import logging
from math import floor
import os
from datetime import datetime, timedelta, timezone
import sys
from typing import Optional
from click import wrap_text
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import boto3
import asyncio
from pathlib import Path
from PIL import ImageFont
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .db import get_all_from_db, init_db
from timezonefinder import TimezoneFinder
from contextlib import asynccontextmanager

tf = TimezoneFinder()

APP_DIR = Path(__file__).resolve().parent
FONT = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=14)
FONT_LARGE = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=24)
PVC_ORIGINAL_PATH = f'{APP_DIR}/images/webcams/originals'
PVC_WATERMARKED_PATH =f'{APP_DIR}/images/webcams/watermarked'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Environment variables
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")

index_db = [] # image index loaded from DB
ready_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global index_db
    # Initialize database
    db_pool = await init_db()
    app.state.db_pool = db_pool  # Store the pool in app state for later use

    # Load image index
    index_db = await load_index_from_db(db_pool)

    # Start periodic purge
    app.state.consume_images_task = asyncio.create_task(purge_old_images_periodically(db_pool))

    ready_event.set()

    # Yield control back to FastAPI
    yield

app = FastAPI(lifespan=lifespan)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    # ["*"] to allow all origins
    allow_origins=["http://localhost:3000"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for watermarked images on PVC
app.mount("/static/images", StaticFiles(directory="/app/app/images/webcams"), name="static-images")



class ImageMeta(BaseModel):
    camera_id: str
    original_pvc_path: Optional[str] = None
    watermarked_pvc_path: Optional[str] = None
    original_s3_path: Optional[str] = None
    watermarked_s3_path: Optional[str] = None
    timestamp: datetime

async def load_index_from_db(db_pool: any):
    # logger.info("Database connection pool initialized. Fetching records...")
    async with db_pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT camera_id, original_pvc_path, watermarked_pvc_path, original_s3_path, watermarked_s3_path, timestamp
            FROM image_index
            WHERE original_s3_path IS NOT NULL
            AND watermarked_s3_path IS NOT NULL
            ORDER BY timestamp
        """)
        
        # Build the index list from DB rows
        index_db = [
            {
                "camera_id": record["camera_id"],
                "original_pvc_path": record["original_pvc_path"],
                "watermarked_pvc_path": record["watermarked_pvc_path"],
                "original_s3_path": record["original_s3_path"],
                "watermarked_s3_path": record["watermarked_s3_path"],
                "timestamp": record["timestamp"],
            }
            for record in records
        ]
        # logger.info(f"Loaded {len(index_db)} records from the database index.")
        return index_db


async def get_images_within(camera_id: str, request: Request, hours: int = 24) -> list:
    await ready_event.wait()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    db_pool = request.app.state.db_pool
    index_db = await load_index_from_db(db_pool)

    results = [
        ImageMeta(**entry) for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    return results

# Save files under "json" folder
OUTPUT_DIR = "/app/ReplayTheDay/json"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mount the folder so it’s accessible at /json
app.mount("/ReplayTheDay/json", StaticFiles(directory=OUTPUT_DIR), name="replay_json")


async def get_images_within_test(camera_id: str, request: Request, hours: int = 24) -> list:
    await ready_event.wait()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    db_pool = request.app.state.db_pool
    index_db = await load_index_from_db(db_pool)

    results = [
        ImageMeta(**entry) for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]
    return results

# Endpoint for timelaps (30 days)
@app.get("/Timelapse/archive/{camera_id}")
async def get_timelaps(camera_id: str, request: Request):
    return await get_images_within(camera_id, request, hours=30 * 24)

# Endpoint for replay the day
@app.get("/api/replay/{camera_id}")
async def get_replay(camera_id: str, request: Request):
    return await get_images_within(camera_id, request, hours=24)

# Endpoint for timelaps (30 days)
@app.get("/api/timelaps/{camera_id}")
async def get_timelaps(camera_id: str, request: Request):
    return await get_images_within(camera_id, request, hours=30 * 24)

# Endpoint for original image used for new control panel in RIDE
@app.get("/api/images/{camera_id}")
async def get_original_image(camera_id: str, request: Request):
    await ready_event.wait()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    db_pool = request.app.state.db_pool
    index_db = await load_index_from_db(db_pool)

    filtered = [
        # entry for entry in index
        entry for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    if not filtered:
        return []

    # Find the latest one
    latest_entry = max(filtered, key=lambda e: e["timestamp"])
    
    return ImageMeta(**latest_entry)

# How often to run (in seconds)
PURGE_INTERVAL_SECONDS = int(os.getenv("PURGE_INTERVAL_SECONDS", "10"))  # default: 1 hour

async def purge_old_images_periodically(db_pool):
    while True:
        try:
            print(f"[{datetime.now(timezone.utc)}] Starting purge task...")
            purge_pvc_age = os.getenv("PURGE_PVC_AGE", "24 hours")
            await purge_old_pvc_images(db_pool, age=f"{purge_pvc_age} hours")
            await purge_old_s3_images(db_pool, age=f"{purge_pvc_age} days")
        except Exception as e:
            print(f"Error during purge: {e}")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)

# Define data directory (PVC)
PVC_ROOT = "/app/app/images/webcams/watermarked"

async def purge_old_pvc_images(db_pool, age: str = "24 hours"):
    # Fetch records older than 24 hours
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT camera_id, original_pvc_path, watermarked_pvc_path,
                original_s3_path, watermarked_s3_path, timestamp
            FROM image_index
            WHERE timestamp < NOW() - INTERVAL '{age}'
            AND original_pvc_path IS NOT NULL
            AND watermarked_pvc_path IS NOT NULL
        """)


        if not rows:
            print("No old images to purge in pvc.")
            return

        files_to_delete = []
        ids_to_delete = []

        for row in rows:
            path = row["watermarked_pvc_path"]
            if path:
                full_path = os.path.join(PVC_ROOT, path)
                files_to_delete.append(full_path)
                ids_to_delete.append(row["timestamp"])

        await conn.execute(f"""
            UPDATE image_index
            SET original_pvc_path = NULL,
                watermarked_pvc_path = NULL
            WHERE timestamp < NOW() - INTERVAL '{age}'
            AND original_pvc_path IS NOT NULL
            AND watermarked_pvc_path IS NOT NULL
        """)


        # Delete files from PVC
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            except FileNotFoundError:
                print(f"File not found: {file_path}")
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")


S3_ROOT = "/test-s3-bucket"
async def purge_old_s3_images(db_pool, age: str = "30 days"):
    print(f"[{datetime.now(timezone.utc)}] Starting S3 purge task...")
    async with db_pool.acquire() as conn:
        # Fetch records older than 30 days
        rows = await conn.fetch(f"""
            SELECT camera_id, original_pvc_path, watermarked_pvc_path, original_s3_path, watermarked_s3_path, timestamp
            FROM image_index
            WHERE timestamp < NOW() - INTERVAL '{age}'
            AND original_s3_path IS NOT NULL
            AND watermarked_s3_path IS NOT NULL
        """)

        if not rows:
            print("No old images to purge in s3.")
            return

        # Create list of file paths to delete
        files_to_delete = []
        ids_to_delete = []

        for row in rows:
            path = row["watermarked_s3_path"]
            if path:
                full_path = os.path.join(S3_ROOT, path)
                files_to_delete.append(full_path)
                ids_to_delete.append(row["timestamp"])

        print(f"Deleting {len(files_to_delete)} old S3 images...")
        print(f"Deleting {len(ids_to_delete)} old S3 image index records...")
                
        await conn.execute(f"""
            UPDATE image_index
            SET original_s3_path = NULL,
                watermarked_s3_path = NULL
            WHERE timestamp < NOW() - INTERVAL '{age}'
            AND original_s3_path IS NOT NULL
            AND watermarked_s3_path IS NOT NULL
        """)

        # Setup S3 client
        s3_client = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            endpoint_url=S3_ENDPOINT_URL
        )

        BUCKET_NAME = "test-s3-bucket"

        # Delete files from S3
        for file_path in files_to_delete:
            try:
                s3_key = file_path.strip("/")

                if s3_key.startswith(f"{BUCKET_NAME}/"):
                    s3_key = s3_key[len(BUCKET_NAME) + 1:]

                s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
                print(f"Deleted from S3: {s3_key}")

            except s3_client.exceptions.NoSuchKey:
                print(f"S3 key not found: {s3_key}")
            except Exception as e:
                print(f"Error deleting S3 file {s3_key}: {e}")

        # Delete all records if all images paths are NULL
        await conn.execute("""
            DELETE FROM image_index
            WHERE original_pvc_path IS NULL
            AND watermarked_pvc_path IS NULL
            AND original_s3_path IS NULL
            AND watermarked_s3_path IS NULL
        """)
        print("All purged recordes are deleted successfully.")