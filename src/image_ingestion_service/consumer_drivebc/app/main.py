import aio_pika
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime, timezone, timedelta

def format_time(past_time):
    now = datetime.now(timezone.utc)
    diff = now - past_time

    minutes = int(diff.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    elif minutes == 1:
        return "1 minute ago"
    else:
        return f"{minutes} minutes ago"
    
def add_custom_watermark(image_bytes, source_timestamp=None):
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    # New image with space for watermark
    bar_height = 30
    new_image = Image.new("RGB", (width, height + bar_height), (0, 0, 0))
    new_image.paste(image, (0, 0))

    draw = ImageDraw.Draw(new_image)

    # Font settings
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 16)

    # Generate time
    now = datetime.now(timezone(timedelta(hours=-7)))
    timestamp_str = now.strftime("%a, %b %d, %Y, %-I:%M %p PDT")

    if source_timestamp:
        if isinstance(source_timestamp, (int, float)):
            source_dt = datetime.fromtimestamp(source_timestamp, tz=timezone.utc)
        elif isinstance(source_timestamp, str):
            source_dt = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
        else:
            source_dt = datetime.now(timezone.utc)
    else:
        source_dt = datetime.now(timezone.utc)

    relative_label = format_time(source_dt)

    # Draw DriveBC label
    drivebc_label = "Drive"
    drivebc_suffix = "BC"
    y_pos = height + 5
    draw.text((5, y_pos), drivebc_label, font=font, fill="white")
    drivebc_w = draw.textlength(drivebc_label, font=font)
    draw.text((5 + drivebc_w, y_pos), drivebc_suffix, font=font, fill="orange")

    # Draw timestamp
    ts_w = draw.textlength(timestamp_str, font=font)
    draw.text(((width - ts_w) / 2, y_pos), timestamp_str, font=font, fill="lightblue")

    # Draw "X minutes ago" on the right
    ago_w = draw.textlength(relative_label, font=font)
    draw.text((width - ago_w - 5, y_pos), relative_label, font=font, fill="white")

    # Save result
    output_folder = "/tmp/watermarked"
    os.makedirs(output_folder, exist_ok=True)
    output_path = os.path.join(output_folder, "watermarked.jpg")
    new_image.save(output_path)
    print(f"Watermarked image saved to: {output_path}")
    return output_path

async def consume():
    rb_url = os.getenv("RABBITMQ_URL")
    if not rb_url:
        raise ValueError("RABBITMQ_URL environment variable is not set")

    connection = await aio_pika.connect_robust(rb_url)
    channel = await connection.channel()
    queue = await channel.declare_queue(
        "image-queue-drivebc",
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

                # Save original image
                received_dir = "/tmp/received_images"
                os.makedirs(received_dir, exist_ok=True)
                original_path = f"{received_dir}/{filename}"
                with open(original_path, "wb") as f:
                    f.write(message.body)
                print(f"Original image saved to {original_path}")

                # Save watermarked image
                watermarked_dir = "/tmp/watermarked"
                os.makedirs(watermarked_dir, exist_ok=True)
                watermarked_path = f"{watermarked_dir}/{filename}"
                filename = message.headers.get("filename", "unknown.jpg")
                timestamp_header = message.headers.get("timestamp")

                # Add watermark
                add_custom_watermark(message.body, timestamp_header)


if __name__ == "__main__":
    asyncio.run(consume())
