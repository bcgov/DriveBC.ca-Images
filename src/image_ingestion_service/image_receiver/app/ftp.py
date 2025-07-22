from anyio import Path
import aioftp
import tempfile
import os
import logging
import aiofiles

logger = logging.getLogger(__name__)

async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str, target_ftp_path: str) -> bool:
    host = os.getenv("FTP_HOST", "")
    port = int(os.getenv("FTP_PORT", 21))
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")

    ftp_client = aioftp.Client()
    ftp_client.passive = True

    try:
        await ftp_client.connect(host, port)
        await ftp_client.login(user, password)
        logger.debug(f"Connected to FTP server {host}:{port} as user {user} for camera_id={camera_id}")

        # Build directory path manually
        path_segments = target_ftp_path.strip("/").split("/")
        current_path = ""

        for segment in path_segments:
            current_path = f"{current_path}/{segment}" if current_path else segment
            try:
                logger.debug("Creating directory on FTP: /%s", current_path)
                await ftp_client.command(f"MKD /{current_path}", "2xx")
            except aioftp.StatusCodeError as e:
                # 550 often means "already exists" — we can skip it
                logger.debug("Directory probably exists: /%s (%s)", current_path, str(e))

        # Only change directory *after* structure is created
        await ftp_client.change_directory(f"/{target_ftp_path.strip('/')}")
        logger.debug("Changed to FTP directory: /%s", target_ftp_path.strip("/"))

        # Write image bytes to a temporary file
        tmp_dir = tempfile.gettempdir()
        tmp_file_path = Path(tmp_dir) / filename
        async with aiofiles.open(tmp_file_path, "wb") as tmp_file:
            await tmp_file.write(image_bytes)

        # Upload the file
        await ftp_client.upload(tmp_file_path, filename, write_into=True)

        await Path(tmp_file_path).unlink()
        return True

    except Exception as e:
        logger.error(f"FTP error for camera_id={camera_id}: %s", str(e), exc_info=True)
        raise

    finally:
        await ftp_client.quit()