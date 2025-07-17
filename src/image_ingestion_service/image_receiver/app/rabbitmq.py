import aio_pika
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")
    # Get current timestamp in ISO 8601 format
    timestamp = datetime.now(timezone.utc).isoformat()
    connection = await aio_pika.connect_robust(rb_url)
    try:
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                    name="test.fanout_image_test",
                    type=aio_pika.ExchangeType.FANOUT,
                    durable=True
                )

            await exchange.publish(
                aio_pika.Message(
                    body=image_bytes,
                    headers={"camera_id": camera_id, "filename": filename, "timestamp": timestamp},
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key=""  # Ignored for fanout
            )
    except Exception as e:
        raise


