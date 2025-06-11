import aio_pika
import asyncio
import os

async def consume():
    connection = await aio_pika.connect_robust(
        os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
    )
    channel = await connection.channel()
    queue = await channel.declare_queue(
            "image-queue-consumer",
            durable=True,
            exclusive=False,
            auto_delete=False
        )

    exchange = await channel.get_exchange("amq.fanout")
    await queue.bind(exchange)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                filename = message.headers.get("filename", "unknown.jpg")
                print(f"Received: {filename} ({len(message.body)} bytes)")

                # Save to disk
                output_dir = "/tmp/received_images"
                os.makedirs(output_dir, exist_ok=True)
                with open(f"{output_dir}/{filename}", "wb") as f:
                    f.write(message.body)
                print(f"Saved to {output_dir}/{filename}")


if __name__ == "__main__":
    asyncio.run(consume())
