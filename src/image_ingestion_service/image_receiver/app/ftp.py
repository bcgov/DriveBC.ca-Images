from anyio import Path
import aioftp
import tempfile
import os
import logging
import aiofiles

logger = logging.getLogger(__name__)

async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str) -> bool:
    host = os.getenv("FTP_HOST", "")
    port = int(os.getenv("FTP_PORT", 21))
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")
    target_dir = os.getenv("FTP_TARGET_DIR", "")

    ftp_client = aioftp.Client()
    ftp_client.passive = True

    try:
        await ftp_client.connect(host, port)
        await ftp_client.login(user, password)
        logger.info(f"Connected to FTP server {host}:{port} as user {user}")

        # Ensure target directory exists
        try:
            await ftp_client.change_directory(target_dir)
        except aioftp.StatusCodeError:
            await ftp_client.make_directory(target_dir)
            await ftp_client.change_directory(target_dir)
        # Ensure camera id directory exists
        try:
            await ftp_client.change_directory(camera_id)
        except aioftp.StatusCodeError:
            await ftp_client.make_directory(camera_id)
            await ftp_client.change_directory(camera_id)

        # Create temp file path in system temp folder
        tmp_dir = tempfile.gettempdir()
        tmp_file_path = Path(tmp_dir) / filename
        async with aiofiles.open(tmp_file_path, "wb") as tmp_file:
            await tmp_file.write(image_bytes)
        
        try:
            await ftp_client.upload(tmp_file_path, filename, write_into=True)
        except aioftp.StatusCodeError as e:
            raise
        await Path(tmp_file_path).unlink()
        return True

    except Exception as e:
        logger.error(f"Push to FTP failed from {camera_id}: {e}")
        return False

    finally:
        # Clean up
        await ftp_client.quit()