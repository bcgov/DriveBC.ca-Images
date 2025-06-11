import aio_pika
import os

async def send_to_rabbitmq(image_bytes, filename, camera_id):
    connection = await aio_pika.connect_robust(os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/"))
    
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

