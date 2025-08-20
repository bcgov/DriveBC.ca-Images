import aio_pika
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id, timestamp):
    """
    Sends the image to RabbitMQ with the provided camera_id, filename, and timestamp.
    The timestamp should already be in compact UTC format (YYYYMMDDTHHMMSSZ).
    """
    # Read and validate environment variables
    cluster = os.getenv("CLUSTER")
    rb_url_gold = os.getenv("RABBITMQ_GOLD_URL")
    rb_url_golddr = os.getenv("RABBITMQ_GOLDDR_URL")
    rb_exchange_name = os.getenv("RABBITMQ_EXCHANGE_NAME")

    if not cluster:
        raise ValueError("Missing environment variable: CLUSTER")    
    if not rb_url_gold:
        raise ValueError("Missing environment variable: RABBITMQ_GOLD_URL")
    if not rb_url_golddr:
        raise ValueError("Missing environment variable: RABBITMQ_GOLDDR_URL")
    if not rb_exchange_name:
        raise ValueError("Missing environment variable: RABBITMQ_EXCHANGE_NAME")
    
    # Pick the RabbitMQ URL based on cluster (default to GOLD)
    if cluster.upper() == "GOLDDR":
        rb_url = rb_url_golddr
    else:
        rb_url = rb_url_gold
        if cluster.upper() != "GOLD":
            logger.warning(f"Unknown CLUSTER value '{cluster}', defaulting to GOLD URL.")

    dt = datetime.fromisoformat(timestamp)
    # Format as YYYYMMDDHHMMSSfff (fff = milliseconds)
    formatted_timestamp = dt.strftime("%Y%m%d%H%M%S") + f"{int(dt.microsecond / 1000):03d}"

    processed_dt = datetime.now(timezone.utc)
    processed_timestamp = processed_dt.strftime("%Y%m%d%H%M%S") + f"{int(processed_dt.microsecond / 1000):03d}"

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
                    "timestamp": formatted_timestamp,
                    "processed_timestamp": processed_timestamp
                },
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            )

            await exchange.publish(message, routing_key="")  # Routing key is ignored for FANOUT
            logger.debug(f"Published message for camera_id={camera_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Failed to publish message to RabbitMQ: {e}", exc_info=True)
        raise
