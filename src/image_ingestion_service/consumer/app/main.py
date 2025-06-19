import aio_pika
import asyncio
import os

async def consume():
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")
    connection = await aio_pika.connect_robust(rb_url)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
                name="test.fanout_image_test",
                type=aio_pika.ExchangeType.FANOUT,
                durable=True
            )
    queue = await channel.declare_queue(
        "image-queue-consumer",
        durable=True,
        exclusive=False,
        auto_delete=False
    )
    print(f"Fanout exchange '{exchange.name}' created or already exists.")
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
