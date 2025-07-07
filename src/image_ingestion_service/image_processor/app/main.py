import io
import json
import logging
from math import floor
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from click import wrap_text
from fastapi import FastAPI, HTTPException, logger
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


tf = TimezoneFinder()


APP_DIR = Path(__file__).resolve().parent
FONT = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=14)
FONT_LARGE = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=24)
PVC_ORIGINAL_PATH = f'{APP_DIR}/images/webcams/originals'
PVC_WATERMARKED_PATH =f'{APP_DIR}/images/webcams/watermarked'

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    global index_db
    # Initialize database
    db_pool = await init_db()

    # Load image index
    index_db = await load_index_from_db(db_pool)

    # Start background tasks
    asyncio.create_task(consume_images(db_pool))

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
app.mount("/api/images/watermarked", StaticFiles(directory="/app/app/images/webcams/watermarked"), name="watermarked")




class ImageMeta(BaseModel):
    camera_id: str
    timestamp: datetime
    path: str



async def load_index_from_db(db_pool: any):
    print("Database connection pool initialized. Fetching records...")
    async with db_pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT camera_id, timestamp, s3_path, pvc_path, watermarked_path
            FROM image_index
            ORDER BY timestamp
        """)
        
        # Build the index list from DB rows
        index_db = [
            {
                "camera_id": record["camera_id"],
                # "timestamp": record["timestamp"].isoformat(),
                "timestamp": record["timestamp"],
                "s3_path": record["s3_path"],
                "pvc_path": record["pvc_path"],
                "watermarked_path": record["watermarked_path"],
                "path": record["s3_path"]  # if you want to keep this alias
            }
            for record in records
        ]
        print(f"Loaded {len(index_db)} records from the database index.")
        return index_db


# Consumer function to process images from RabbitMQ
async def consume_images(db_pool: any):
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
    print(f"Fanout exchange '{exchange.name}' created or already exists.")

    exchange = await channel.get_exchange("test.fanout_image_test")
    await queue.bind(exchange)

    # db_pool = await init_db()

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                filename = message.headers.get("filename", "unknown.jpg")
                await handle_image_message(db_pool, filename, message.body)

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

def watermark_image(camera_id: str, image_data: bytes, milliseconds: int, tz: str = 'America/Vancouver'):
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

 
async def handle_image_message(db_pool: any, filename: str, body: bytes):
    # Metadata: camera_id + timestamp
    camera_id = filename.split("_")[0].split('.')[0]
    timestamp = datetime.utcnow()
    milliseconds = int(timestamp.timestamp() * 1000)
    
    # Save original image to s3
    ext = "jpg"
    key = f"{camera_id}/{timestamp.strftime('%Y/%m/%d/%H')}/{milliseconds}.{ext}"
    s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=body)

    s3_path = key
    logger.info(f"Origianal image saved to S3 at {key}")

    # Save original image to PVC
    save_dir = os.path.join(PVC_ORIGINAL_PATH, camera_id)
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{milliseconds}.jpg"
    filepath = os.path.join(save_dir, filename)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(body)
    pvc_path = filepath
    logger.info(f"Original image saved to PVC at {filepath}")

    # Save watermarked image
    logger.info(f"Watermarking image for camera {camera_id} at {timestamp}")
    watermark_image(camera_id, body, milliseconds)
    watermarked_path = f"{PVC_WATERMARKED_PATH}/{camera_id}/{milliseconds}.jpg"

    # Update index
    index.append({
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "s3_path": s3_path,
        "pvc_path": pvc_path,
        "watermarked_path": watermarked_path,
        "path": s3_path
    })

    # Insert record into DB
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO image_index (camera_id, timestamp, s3_path, pvc_path, watermarked_path)
            VALUES ($1, $2, $3, $4, $5)
        """, camera_id, timestamp, s3_path, pvc_path, watermarked_path)

    logger.info(f"Image index for camera {camera_id} at {timestamp} saved to DB")

# Endpoint for replay the day
@app.get("/api/replay/{camera_id}")
async def get_replay(camera_id: str):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    results = [
        ImageMeta(**entry) for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    return results

# Endpoint for original image used for new control panel in RIDE
@app.get("/api/images/original/{camera_id}")
async def get_original_image(camera_id: str):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # db_pool = await init_db()
    # index_db = await load_index_from_db(db_pool)

    filtered = [
        # entry for entry in index
        entry for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]

    if not filtered:
        raise HTTPException(status_code=404, detail="No image found in the last 24 hours for this camera")

    # Find the latest one
    latest_entry = max(filtered, key=lambda e: e["timestamp"])
    
    return ImageMeta(**latest_entry)

# Endpoint for watermarked image used for new control panel in RIDE
@app.get("/api/images/watermarked/{camera_id}")
async def get_watermarked_image(camera_id: str):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # db_pool = await init_db()
    # index_db = await load_index_from_db(db_pool)
    filtered = [
        # entry for entry in index
        entry for entry in index_db
        if entry["camera_id"] == camera_id and entry["timestamp"] >= cutoff
    ]
    logger.info(f"filtered db: {filtered}")
    if not filtered:
        raise HTTPException(status_code=404, detail="No image found in the last 24 hours for this camera")

    # Find the latest one
    latest_entry = max(filtered, key=lambda e: e["timestamp"])
    
    return ImageMeta(**latest_entry)
