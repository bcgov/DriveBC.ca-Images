import urllib.request as urllib_req
import aio_pika
import logging
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id, timestamp):
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
        exchange = urllib_req.app.state.rabbitmq_exchange
        connection = urllib_req.app.state.rabbitmq_connection
        channel = await connection.channel()
        
        try:
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
        finally:
            await channel.close()
    except Exception as e:
        logger.error(f"Failed to publish message to RabbitMQ: {e}", exc_info=True)
        raise
