import aio_pika
import os
import logging

logger = logging.getLogger(__name__)

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")
    connection = await aio_pika.connect_robust(rb_url)
    
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
                name="test.fanout_image_test",
                type=aio_pika.ExchangeType.FANOUT,
                durable=True
            )
        logger.info(f"Fanout exchange '{exchange.name}' created or already exists.")

        await exchange.publish(
            aio_pika.Message(
                body=image_bytes,
                headers={"camera_id": camera_id, "filename": filename},
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=""  # Ignored for fanout
        )

