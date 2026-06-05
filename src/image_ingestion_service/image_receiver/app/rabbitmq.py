import aio_pika
import logging
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

async def send_to_rabbitmq(request, image_bytes, filename, camera_id, timestamp):
    """
    Sends the image to RabbitMQ with the provided camera_id, filename, and timestamp.
    The timestamp should already be in compact UTC format (YYYYMMDDTHHMMSSZ).
    """

    dt = datetime.fromisoformat(timestamp)
    # Format as YYYYMMDDHHMMSSfff (fff = milliseconds)
    formatted_timestamp = dt.strftime("%Y%m%d%H%M%S") + f"{int(dt.microsecond / 1000):03d}"

    processed_dt = datetime.now(timezone.utc)
    processed_timestamp = processed_dt.strftime("%Y%m%d%H%M%S") + f"{int(processed_dt.microsecond / 1000):03d}"

    try:
        exchange = request.app.state.rabbitmq_exchange
        channel_lock = getattr(request.app.state, "rabbitmq_channel_lock", None)

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

        if channel_lock:
            async with channel_lock:
                await exchange.publish(message, routing_key="")
        else:
            await exchange.publish(message, routing_key="")

        logger.debug(f"Published message for camera_id={camera_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Failed to publish message to RabbitMQ: {e}", exc_info=True)
        raise
