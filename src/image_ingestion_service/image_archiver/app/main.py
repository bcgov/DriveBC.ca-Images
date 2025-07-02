import os
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import boto3
import aio_pika
import asyncio
import aiofiles

from fastapi.middleware.cors import CORSMiddleware



# Environment variables
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
STORAGE_MODE = os.getenv("STORAGE_MODE", "s3")
PVC_PATH = os.getenv("PVC_PATH", "/app/data")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")

# S3 client
s3_client = None
if STORAGE_MODE == "s3":
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

async def handle_image_message(filename: str, body: bytes):
    
    # Simulate metadata: camera_id + timestamp
    camera_id = filename.split("_")[0].split('.')[0]
    timestamp = datetime.utcnow()

    if STORAGE_MODE == "s3":
        ext = "jpg"
        key = f"{camera_id}/{timestamp.strftime('%Y/%m/%d/%H')}/{uuid.uuid4()}.{ext}"
        s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=body)

        path = key
    else:  # PVC
        save_dir = os.path.join(PVC_PATH, camera_id, timestamp.strftime('%Y/%m/%d/%H'))
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}.jpg"
        filepath = os.path.join(save_dir, filename)
        # with open(filepath, "wb") as f:
        #     f.write(body)
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(body)

        path = filepath

    # Update index
    index.append({
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "path": path
    })

# API endpoint for replay the day
@app.get("/replay/{camera_id}")
async def get_replay(camera_id: str):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    results = [
        ImageMeta(**entry) for entry in index
        if entry["camera_id"] == camera_id and datetime.fromisoformat(entry["timestamp"]) >= cutoff
    ]
    return results

# Startup task
@app.on_event("startup")
async def startup():
    asyncio.create_task(consume_images())
