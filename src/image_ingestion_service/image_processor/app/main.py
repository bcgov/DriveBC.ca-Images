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
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    global index_db
    # Initialize database
    db_pool = await init_db()
    app.state.db_pool = db_pool  # Store the pool in app state for later use

    # Load image index
    index_db = await load_index_from_db(db_pool)

    # Save background task to prevent GC
    app.state.consume_images_task = asyncio.create_task(consume_images(db_pool))

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

async def consume_images(db_pool: any):
    connection = None
    channel = None

    try:
        rb_url = os.getenv("RABBITMQ_URL")
        if not rb_url:
            raise ValueError("RABBITMQ_URL environment variable is not set")

        connection = await aio_pika.connect_robust(rb_url)
        channel = await connection.channel()

        exchange = await channel.declare_exchange(
            name="test.fanout_image_test",
            type=aio_pika.ExchangeType.FANOUT,
            durable=True
        )

        queue = await channel.declare_queue(
            "image-queue-image-archiver",
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={"x-max-length-bytes": 419430400}
        )

        await queue.bind(exchange)

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    filename = message.headers.get("filename", "unknown.jpg")
                    timestamp = format_timestamp(message.headers.get("timestamp", "unknown"))
                    await handle_image_message(db_pool, filename, message.body, timestamp)

    except asyncio.CancelledError:
        logger.info("Image consumer task was cancelled.")
        raise
    except ChannelInvalidStateError:
        logger.warning("AMQP channel closed during shutdown. Skipping further cleanup.")
    except Exception as e:
        logger.exception("Unhandled error in consume_images")
    finally:
        logger.info("Cleaning up RabbitMQ resources...")
        try:
            if channel and not channel.is_closed:
                await channel.close()
        except Exception as e:
            logger.warning(f"Error closing channel: {e}")

        try:
            if connection and not connection.is_closed:
                await connection.close()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

def format_timestamp(timestamp: str) -> str:
    try:
        if timestamp and timestamp != "unknown":
            dt = datetime.fromisoformat(timestamp)

            # Desired format: YYYYMMDDHHMM
            timestamp = dt.strftime("%Y%m%d%H%M")
        else:
            timestamp = "unknown"
    except Exception as e:
        logger.error(f"Error parsing timestamp {timestamp}: {e}")
    return timestamp  

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
            "is_on": True if not row.get('Cam_ControlDisabled') else False,
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

def watermark(camera_id: str, image_data: bytes):
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
            wrapped = wrap_text(
                text=message,
                width=min(width - 40, 500),
                initial_indent="",
                subsequent_indent="",
                preserve_paragraphs=False
            )
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

        # Return image as byte array
        buffer = io.BytesIO()
        stamped.save(buffer, format="JPEG")
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"Error processing image from camer: {camera_id} - {e}")

def save_original_image_to_pvc(camera_id: str, image_bytes: bytes):
    # Save original image to PVC, can be overwritten each time
    save_dir = os.path.join(PVC_ORIGINAL_PATH)
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{camera_id}.jpg"

    filepath = os.path.join(save_dir, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
    except Exception as e:
        logger.error(f"Error saving original image to PVC {filepath}: {e}")

    original_pvc_path = filepath
    logger.info(f"Original image saved to PVC at {filepath}")
    return original_pvc_path

def save_original_image_to_s3(camera_id: str, image_bytes: bytes):
    # Save original image to s3
    ext = "jpg"
    key = f"originals/{camera_id}.{ext}"
    
    try:
        s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=image_bytes)
    except Exception as e:
        logger.error(f"Error saving original image to S3 bucket {S3_BUCKET}: {e}")

    original_s3_path = key
    logger.info(f"Origianal image saved to S3 at {key}")
    return original_s3_path

def save_watermarked_image_to_pvc(camera_id: str, image_bytes: bytes, timestamp: str):  
    os.makedirs(os.path.dirname(f'{PVC_WATERMARKED_PATH}'), exist_ok=True)

    save_dir = os.path.join(PVC_WATERMARKED_PATH, camera_id)
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{timestamp}.jpg"
    filepath = os.path.join(save_dir, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Watermarked image saved to PVC at {filepath}")
    except Exception as e:
        logger.error(f"Error saving Watermarked image to PVC {filepath}: {e}")
    
    watermarked_pvc_path = filepath
    return watermarked_pvc_path

def save_watermarked_image_to_s3(camera_id: str, image_bytes: bytes, timestamp: str):
    ext = "jpg"
    key = f"watermarked/{camera_id}/{timestamp}.{ext}"
    
    try:
        s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=image_bytes)
    except Exception as e:
        logger.error(f"Error saving watermarked image to S3 bucket {S3_BUCKET}: {e}")
    
    watermarked_s3_path = key
    logger.info(f"Wartermarked image saved to S3 at {key}")
    return watermarked_s3_path


# Save files under "json" folder
OUTPUT_DIR = "/app/ReplayTheDay/json"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mount the folder so it’s accessible at /json
async def get_images_within(camera_id: str, db_pool: any, hours: int = 24) -> list:
    await ready_event.wait()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    index_db = await load_index_from_db(db_pool)

    results = [
        ImageMeta(**entry) for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    return results

async def update_replay_json(camera_id: str, db_pool: any):
    results = await get_images_within(camera_id, db_pool, hours=24)

    # Convert results into JSON-safe format
    encoded_results = jsonable_encoder(results)

    # Extract numeric IDs from watermarked_pvc_path
    ids = []
    for item in encoded_results:
        watermarked_path = item.get("watermarked_pvc_path", "")
        filename = os.path.basename(watermarked_path)  # e.g., "1752692963163.jpg"
        file_id, _ = os.path.splitext(filename)  # split "1752692963163" and ".jpg"
        ids.append(file_id)

    # Create the JSON file with only IDs
    logger.info(f"Updating JSON file for camera {camera_id} with {len(ids)} IDs")
    file_path = os.path.join(OUTPUT_DIR, f"{camera_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(ids, f, indent=4)
    logger.info(f"JSON file for camera {camera_id} saved at {file_path}")

    return JSONResponse({
        "status": "success",
        "file_path": f"/ReplayTheDay/json/{camera_id}.json",
        "count": len(ids)
    })


async def handle_image_message(db_pool: any, filename: str, body: bytes, timestamp: str):
    # Metadata: camera_id + timestamp
    camera_id = filename.split("_")[0].split('.')[0]
    # timestamp = datetime.utcnow()
    dt = datetime.strptime(timestamp, "%Y%m%d%H%M")
    # milliseconds = int(timestamp.timestamp() * 1000)

    original_pvc_path = save_original_image_to_pvc(camera_id, body)
    original_s3_path = save_original_image_to_s3(camera_id, body)

    image_bytes = watermark(camera_id, body)

    watermarked_pvc_path = save_watermarked_image_to_pvc(camera_id, image_bytes, timestamp)
    watermarked_s3_path = save_watermarked_image_to_s3(camera_id, image_bytes, timestamp)

    # Update index
    index.append({
        "camera_id": camera_id, 
        "original_pvc_path": original_pvc_path,
        "watermarked_pvc_path": watermarked_pvc_path,
        "original_s3_path": original_s3_path,
        "watermarked_s3_path": watermarked_s3_path,
        "path": watermarked_s3_path,
        "timestamp": timestamp
    })

    # update json file for replay the day
    await update_replay_json(camera_id, db_pool)


    # Insert record into DB
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO image_index (camera_id, original_pvc_path, watermarked_pvc_path, original_s3_path, watermarked_s3_path, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, camera_id, original_pvc_path, watermarked_pvc_path, original_s3_path, watermarked_s3_path, dt)