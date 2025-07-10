import io
import json
import logging
from math import floor
import os
from datetime import datetime, timedelta, timezone
import sys
from zoneinfo import ZoneInfo
from click import wrap_text
from fastapi import FastAPI, HTTPException, Request, logger
from pydantic import BaseModel
import boto3
import aio_pika
import asyncio
import aiofiles
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .db import get_all_from_db, db_pool, init_db
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo
import asyncpg
from contextlib import asynccontextmanager
from dateutil import parser
from aiormq.exceptions import ChannelInvalidStateError


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

# S3 client
s3_client = None
s3_client = boto3.client(
    "s3",
    region_name=S3_REGION,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT_URL
)

index = []  # image index in memory

index_db = [] # image index loaded from DB
ready_event = asyncio.Event()

print("✅ main.py loaded")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔁 Lifespan startup triggered")
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
# app.mount("/api/images", StaticFiles(directory="/app/app/images/webcams"), name="images")
app.mount("/static/images", StaticFiles(directory="/app/app/images/webcams"), name="static-images")








class ImageMeta(BaseModel):
    camera_id: str
    original_pvc_path: str
    watermarked_pvc_path: str
    original_s3_path: str
    watermarked_s3_path: str
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

# async def consume_images(db_pool: any):
#     connection = None
#     channel = None

#     try:
#         rb_url = os.getenv("RABBITMQ_URL")
#         if not rb_url:
#             raise ValueError("RABBITMQ_URL environment variable is not set")

#         connection = await aio_pika.connect_robust(rb_url)
#         channel = await connection.channel()

#         exchange = await channel.declare_exchange(
#             name="test.fanout_image_test",
#             type=aio_pika.ExchangeType.FANOUT,
#             durable=True
#         )

#         queue = await channel.declare_queue(
#             "image-queue-image-archiver",
#             durable=True,
#             exclusive=False,
#             auto_delete=False,
#             arguments={"x-max-length-bytes": 419430400}
#         )

#         await queue.bind(exchange)

#         async with queue.iterator() as queue_iter:
#             async for message in queue_iter:
#                 async with message.process():
#                     filename = message.headers.get("filename", "unknown.jpg")
#                     await handle_image_message(db_pool, filename, message.body)

#     except asyncio.CancelledError:
#         logger.info("Image consumer task was cancelled.")
#         raise
#     except ChannelInvalidStateError:
#         logger.warning("AMQP channel closed during shutdown. Skipping further cleanup.")
#     except Exception as e:
#         logger.exception("Unhandled error in consume_images")
#     finally:
#         logger.info("Cleaning up RabbitMQ resources...")
#         try:
#             if channel and not channel.is_closed:
#                 await channel.close()
#         except Exception as e:
#             logger.warning(f"Error closing channel: {e}")

#         try:
#             if connection and not connection.is_closed:
#                 await connection.close()
#         except Exception as e:
#             logger.warning(f"Error closing connection: {e}")

def process_camera_rows(rows):
    if not rows:
        logger.error("No camera rows found in the database.")
        return []
    camera_list = []
    for row in rows:
        camera_obj = {
            'id': row.get('ID'),
            'cam_locationsGeo_latitude': row.get('Cam_LocationsGeo_Latitude'),
            'cam_locationsGeo_longitude': row.get('Cam_LocationsGeo_Longitude'),
            "last_update_modified": datetime.now(timezone.utc),
            "update_period_mean": 300,
            "update_period_stddev": 60,
            "dbc_mark": "DriveBC",
            "is_on": True,
            "message": {
                "long": "This is a sample message for the webcam."
            }
        }
        camera_list.append(camera_obj)
    return camera_list

def get_timezone(webcam):
    lat = float(webcam.get('cam_locationsGeo_latitude'))
    lon = float(webcam.get('cam_locationsGeo_longitude'))

    tz_name = tf.timezone_at(lat=lat, lng=lon)
    return tz_name if tz_name else 'America/Vancouver'  # Fallback to PST if no timezone found

def watermark_image(camera_id: str, image_data: bytes, milliseconds: int):
    # Load camera data from the database
    rows = get_all_from_db()
    db_data = process_camera_rows(rows)
    if not db_data:
        logger.error("No camera data available for watermarking.")
        return
    webcams = [cam for cam in db_data if cam['id'] == int(camera_id)]
    webcam = webcams[0] if webcams else None
    tz = get_timezone(webcam) if webcam else 'America/Vancouver'
    try:
        if image_data is None:
            return

        raw = Image.open(io.BytesIO(image_data))
        width, height = raw.size
        if width > 800:
            ratio = 800 / width
            width = 800
            height = floor(height * ratio)
            raw = raw.resize((width, height))

        stamped = Image.new('RGB', (width, height + 18))
        pen = ImageDraw.Draw(stamped)
        lastmod = webcam.get('last_update_modified')

        if webcam.get('is_on'):
            stamped.paste(raw)  # leaves 18 pixel black bar left at bottom

            timestamp = 'Last modification time unavailable'
            if lastmod is not None:
                month = lastmod.strftime('%b')
                day = lastmod.strftime('%d')
                day = day[1:] if day[:1] == '0' else day  # strip leading zero
                dt_local = lastmod.astimezone(ZoneInfo(tz))
                timestamp = f'{month} {day}, {dt_local.strftime("%Y %H:%M:%S %p %Z")}'
            pen.text((width - 3,  height + 14), timestamp, fill="white",
                     anchor='rs', font=FONT)

        else:  # camera is unavailable, replace image with message
            message = webcam.get('message', {}).get('long')
            wrapped = wrap_text(message, pen, FONT_LARGE, min(width - 40, 500))
            bbox = pen.multiline_textbbox((0, 0), wrapped, font=FONT_LARGE)
            x = (width - bbox[2]) / 2
            pen.multiline_text((x, 20), wrapped, fill="white", align='center',
                               font=FONT_LARGE)
            pen.polygon(((0, height), (width, height),
                         (width, height + 18), (0, height + 18)),
                        fill="red")

        # add mark and timestamp to black bar
        mark = webcam.get('dbc_mark', '')
        pen.text((3,  height + 14), mark, fill="white", anchor='ls', font=FONT)

        # save image in shared volume
        os.makedirs(os.path.dirname(f'{PVC_WATERMARKED_PATH}'), exist_ok=True)

        save_dir = os.path.join(PVC_WATERMARKED_PATH, camera_id)
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{milliseconds}.jpg"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'wb') as saved:
            stamped.save(saved, 'jpeg', quality=75, exif=raw.getexif())
        logger.info(f"Watermarked image saved to {filepath}")
        # Set the last modified time to the last modified time plus a timedelta
        # calculated mean time between updates, minus the standard
        # deviation.  If that can't be calculated, default to 5 minutes.  This is
        # then used to set the expires header in nginx.
        delta = 300  # 5 minutes
        try:
            mean = webcam.get('update_period_mean')
            stddev = webcam.get('update_period_stddev', 0)
            delta = mean - stddev

        except Exception as e:
            logger.error(f"Error calculating delta: {e}")

    except Exception as e:
        logger.error(f"Error processing image from camer: {camera_id} - {e}")


# Endpoint for replay the day
@app.get("/api/replay/{camera_id}")
async def get_replay(camera_id: str, request: Request):
    await ready_event.wait()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    db_pool = request.app.state.db_pool
    index_db = await load_index_from_db(db_pool)

    results = [
        ImageMeta(**entry) for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    return results

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
            await purge_old_pvc_images(db_pool, age="5 minutes")
            await purge_old_s3_images(db_pool, age="10 minutes")
        except Exception as e:
            print(f"Error during purge: {e}")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)

# Define data directory (PVC)
PVC_ROOT = "/app/app/images/webcams/watermarked"

async def purge_old_pvc_images(db_pool, age: str = "5 minutes"):
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
async def purge_old_s3_images(db_pool, age: str = "10 minutes"):
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

        # Setup S3 client for MinIO
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

                s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
                print(f"Deleted from S3: {s3_key}")

            except s3_client.exceptions.NoSuchKey:
                print(f"S3 key not found: {s3_key}")
            except Exception as e:
                print(f"Error deleting S3 file {s3_key}: {e}")

        # Delete all records if all images paths are NULL
        await conn.execute("""
            DELETE image_index
            WHERE original_pvc_path IS NULL
            AND watermarked_pvc_path IS NULL
            AND original_s3_path IS NULL
            AND watermarked_s3_path IS NULL
        """)
        print("All purged recordes are deleted successfully.")