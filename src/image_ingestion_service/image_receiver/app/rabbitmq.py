import json
from urllib import request

import aio_pika
import os
import logging
from datetime import datetime, timezone

from image_ingestion_service.image_receiver import app

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
        exchange = request.app.state.rabbitmq_exchange
        connection = request.app.state.rabbitmq_connection
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


class RabbitMQManager:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.exchange = None

    async def connect(self, rabbitmq_url: str):
        logger.info("Connecting to RabbitMQ...")

        self.connection = await aio_pika.connect_robust(
            rabbitmq_url
        )

        self.channel = await self.connection.channel()

        # Prevent unlimited unacked messages
        await self.channel.set_qos(prefetch_count=100)

        self.exchange = self.channel.default_exchange

        logger.info("RabbitMQ connected")

    async def close(self):
        if self.connection:
            await self.connection.close()
            logger.info("RabbitMQ connection closed")

    async def publish_image(
        self,
        image_bytes: bytes,
        filename: str,
        camera_id: str,
        timestamp: str
    ):
        message_data = {
            "filename": filename,
            "camera_id": camera_id,
            "timestamp": timestamp,
            # Better: store image externally and only send path
            "image": image_bytes.hex()
        }

        message = aio_pika.Message(
            body=json.dumps(message_data).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )

        await self.exchange.publish(
            message,
            routing_key="images"
        )


rabbitmq_manager = RabbitMQManager()