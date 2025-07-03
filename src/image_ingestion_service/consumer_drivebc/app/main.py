from math import floor
from zoneinfo import ZoneInfo
from click import wrap_text
from fastapi import logger
import aio_pika
import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime, timezone, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
FONT = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=14)
FONT_LARGE = ImageFont.truetype(f'{APP_DIR}/static/BCSans.otf', size=24)
CAMS_DIR = f'{APP_DIR}/images/webcams'

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
    exchange = await channel.declare_exchange(
                name="test.fanout_image_test",
                type=aio_pika.ExchangeType.FANOUT,
                durable=True
            )
    queue = await channel.declare_queue(
        "image-queue-drivebc",
        durable=True,
        exclusive=False,
        auto_delete=False
    )
    print(f"Fanout exchange '{exchange.name}' created or already exists.")

    exchange = await channel.get_exchange("test.fanout_image_test")
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

                # Add watermark as before
                # update_webcam_image_from_rabbitmq(, message.body, "America/Vancouver")

def update_webcam_image_from_rabbitmq(webcam, image_data, tz):
    '''
    Retrieve the current cam image, stamp it and save it

    Per JIRA ticket DBC22-1857

    '''

    try:
        if image_data is None:
            return

        raw = Image.open(image_data)
        width, height = raw.size
        if width > 800:
            ratio = 800 / width
            width = 800
            height = floor(height * ratio)
            raw = raw.resize((width, height))

        stamped = Image.new('RGB', (width, height + 18))
        pen = ImageDraw.Draw(stamped)
        lastmod = webcam.get('last_update_modified')

        if webcam.get('is_on'):
            stamped.paste(raw)  # leaves 18 pixel black bar left at bottom

            timestamp = 'Last modification time unavailable'
            if lastmod is not None:
                month = lastmod.strftime('%b')
                day = lastmod.strftime('%d')
                day = day[1:] if day[:1] == '0' else day  # strip leading zero
                dt_local = lastmod.astimezone(ZoneInfo(tz))
                timestamp = f'{month} {day}, {dt_local.strftime("%Y %H:%M:%S %p %Z")}'

            pen.text((width - 3,  height + 14), timestamp, fill="white",
                     anchor='rs', font=FONT)

        else:  # camera is unavailable, replace image with message
            message = webcam.get('message', {}).get('long')
            wrapped = wrap_text(message, pen, FONT_LARGE, min(width - 40, 500))
            bbox = pen.multiline_textbbox((0, 0), wrapped, font=FONT_LARGE)
            x = (width - bbox[2]) / 2
            pen.multiline_text((x, 20), wrapped, fill="white", align='center',
                               font=FONT_LARGE)
            pen.polygon(((0, height), (width, height),
                         (width, height + 18), (0, height + 18)),
                        fill="red")

        # add mark and timestamp to black bar
        mark = webcam.get('dbc_mark', '')
        pen.text((3,  height + 14), mark, fill="white", anchor='ls', font=FONT)

        # save image in shared volume
        filename = f'{CAMS_DIR}/{webcam["id"]}.jpg'
        with open(filename, 'wb') as saved:
            stamped.save(saved, 'jpeg', quality=75, exif=raw.getexif())

        # Set the last modified time to the last modified time plus a timedelta
        # calculated mean time between updates, minus the standard
        # deviation.  If that can't be calculated, default to 5 minutes.  This is
        # then used to set the expires header in nginx.
        delta = 300  # 5 minutes
        try:
            mean = webcam.get('update_period_mean')
            stddev = webcam.get('update_period_stddev', 0)
            delta = mean - stddev

        except Exception as e:
            logger.info(e)

        if lastmod is not None:
            delta = datetime.timedelta(seconds=delta)
            lastmod = floor((lastmod + delta).timestamp())  # POSIX timestamp
            os.utime(filename, times=(lastmod, lastmod))

    except HTTPError as e:  # log HTTP errors without stacktrace to reduce log noise
        logger.error(f'{e} on camera {webcam['id']}')

    except Exception as e:
        logger.exception(e)



if __name__ == "__main__":
    asyncio.run(consume())
