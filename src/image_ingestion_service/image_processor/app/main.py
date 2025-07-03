import io
import logging
from math import floor
import os
from datetime import datetime, timedelta
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

app = FastAPI()

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
app.mount("/images/watermarked", StaticFiles(directory="/app/app/images/webcams/watermarked"), name="watermarked")

index = []  # Redis or DB indexes

class ImageMeta(BaseModel):
    camera_id: str
    timestamp: datetime
    path: str

# Consumer function to process images from RabbitMQ
async def consume_images():
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
        auto_delete=False
    )
    print(f"Fanout exchange '{exchange.name}' created or already exists.")

    exchange = await channel.get_exchange("test.fanout_image_test")
    await queue.bind(exchange)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                filename = message.headers.get("filename", "unknown.jpg")
                await handle_image_message(filename, message.body)

def watermark_image(camera_id: str, image_data: bytes, tz: str = 'America/Vancouver'):
    # fake webcam data
    webcam = {
        "id": camera_id,
        "last_update_modified": datetime.utcnow(),
        "update_period_mean": 300,
        "update_period_stddev": 60,
        "dbc_mark": "DriveBC",
        "is_on": True,
        "message": {
            "long": "This is a sample message for the webcam."
        }
    }
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
        os.makedirs(os.path.dirname(f'{PVC_ORIGINAL_PATH}'), exist_ok=True)
        filename = f'{PVC_WATERMARKED_PATH}/{webcam["id"]}.jpg'
        with open(filename, 'wb') as saved:
            stamped.save(saved, 'jpeg', quality=75, exif=raw.getexif())
        print(f"Watermarked image saved to {filename}")
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

        if lastmod is not None:
            delta = timedelta(seconds=delta)
            lastmod = floor((lastmod + delta).timestamp())  # POSIX timestamp
            os.utime(filename, times=(lastmod, lastmod))

    except Exception as e:
        logger.error(f"Error processing image {filename}: {e}")


async def handle_image_message(filename: str, body: bytes):
    
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
    watermark_image(camera_id, body)
    watermarked_path = f"{PVC_WATERMARKED_PATH}/{camera_id}.jpg"

    # Update index
    index.append({
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "s3_path": s3_path,
        "pvc_path": pvc_path,
        "watermarked_path": watermarked_path,
        "path": s3_path
    })

# Endpoint for replay the day
@app.get("/replay/{camera_id}")
async def get_replay(camera_id: str):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    results = [
        ImageMeta(**entry) for entry in index
        if entry["camera_id"] == camera_id and datetime.fromisoformat(entry["timestamp"]) >= cutoff
    ]
    return results

# Endpoint for original image used for new control panel in RIDE
@app.get("/images/{camera_id}")
async def get_original_image(camera_id: str):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    # Filter images for camera_id within the last 24 hours
    filtered = [
        entry for entry in index
        if entry["camera_id"] == camera_id and datetime.fromisoformat(entry["timestamp"]) >= cutoff
    ]

    if not filtered:
        raise HTTPException(status_code=404, detail="No image found in the last 24 hours for this camera")

    # Find the latest one
    latest_entry = max(filtered, key=lambda e: datetime.fromisoformat(e["timestamp"]))
    
    return ImageMeta(**latest_entry)

# Startup task
@app.on_event("startup")
async def startup():
    asyncio.create_task(consume_images())
