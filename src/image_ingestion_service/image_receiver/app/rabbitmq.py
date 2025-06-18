import aio_pika
import os

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")
    connection = await aio_pika.connect_robust(rb_url)
    
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange("amq.fanout")

        await exchange.publish(
            aio_pika.Message(
                body=image_bytes,
                headers={"camera_id": camera_id, "filename": filename},
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=""  # Ignored for fanout
        )

