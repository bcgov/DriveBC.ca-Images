import aio_pika
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    # Read and validate environment variables
    rb_url = os.getenv("RABBITMQ_URL")
    rb_exchange_name = os.getenv("RABBITMQ_EXCHANGE_NAME")
    
    if not rb_url:
        raise ValueError("Missing environment variable: RABBITMQ_URL")
    if not rb_exchange_name:
        raise ValueError("Missing environment variable: RABBITMQ_EXCHANGE_NAME")

    # Use timezone-aware UTC timestamp formatted as YYYYMMDDHHMM
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")

    try:
        connection = await aio_pika.connect_robust(rb_url)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                name=rb_exchange_name,
                type=aio_pika.ExchangeType.FANOUT,
                durable=True
            )

            message = aio_pika.Message(
                body=image_bytes,
                headers={
                    "camera_id": camera_id,
                    "filename": filename,
                    "timestamp": timestamp
                },
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            )

            await exchange.publish(message, routing_key="")  # Routing key is ignored for FANOUT
            logger.debug(f"Published message for camera_id={camera_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Failed to publish message to RabbitMQ: {e}", exc_info=True)
        raise
