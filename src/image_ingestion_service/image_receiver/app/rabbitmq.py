import aio_pika
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")
    rb_exchange_name = os.getenv("RABBITMQ_EXCHANGE_NAME")
    if not rb_exchange_name:
        raise ValueError("RABBITMQ_EXCHANGE_NAME environment variable is not set")
    # Get current timestamp in ISO 8601 format
    timestamp = datetime.now(timezone.utc).isoformat()
    # Parse back to datetime object
    dt = datetime.fromisoformat(timestamp)

    # Format as YYYYMMDDHHMM
    formatted_timestamp = dt.strftime("%Y%m%d%H%M")
    connection = await aio_pika.connect_robust(rb_url)
    try:
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                    name=rb_exchange_name,
                    type=aio_pika.ExchangeType.FANOUT,
                    durable=True
                )

            await exchange.publish(
                aio_pika.Message(
                    body=image_bytes,
                    headers={"camera_id": camera_id, "filename": filename, "timestamp": formatted_timestamp},
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key=""  # Ignored for fanout
            )
    except Exception as e:
        raise


