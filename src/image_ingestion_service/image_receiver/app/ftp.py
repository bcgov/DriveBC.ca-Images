from anyio import Path
import aioftp
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str) -> bool:
    host = os.getenv("FTP_HOST", "")
    port = int(os.getenv("FTP_PORT", 21))
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")
    target_dir = os.getenv("FTP_TARGET_DIR", "")

    client = aioftp.Client()
    client.passive = True

    tmp_dir = tempfile.gettempdir()
    tmp_file_path = Path(tmp_dir) / filename

    try:
        await client.connect(host, port)
        await client.login(user, password)
        logger.info(f"Connected to FTP server {host}:{port} as user {user}")

        try:
            await client.change_directory(target_dir)
        except aioftp.StatusCodeError:
            await client.make_directory(target_dir)
            await client.change_directory(target_dir)

        with tmp_file_path.open("wb") as tmp_file:
            tmp_file.write(image_bytes)

        remote_path = f"{camera_id}/{filename}"

        logger.info(f"Uploading {tmp_file_path} to {remote_path} on FTP server...")
        await client.upload(tmp_file_path, remote_path, write_into=True)
        logger.info(f"Uploaded {filename} to FTP server at {remote_path}")

        return True

    except Exception as e:
        logger.error(f"Push to FTP failed from {camera_id}: {e}")
        return False

    finally:
        await client.quit()
        tmp_file_path.unlink(missing_ok=True)

    # async with aioftp.Client.context(host, port, user, password) as client:
    #     logger.info(f"Connected to FTP server {host}:{port} as user {user}")
    #     try:
    #         await client.change_directory(target_dir)
    #     except aioftp.StatusCodeError as e:
    #         await client.make_directory(target_dir)
    #         await client.change_directory(target_dir)

    #     # Save to a temp file
    #     with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
    #         tmp_file.write(image_bytes)
    #         tmp_file_path = Path(tmp_file.name)
    #         remote_path = f"{camera_id}/{filename}"   
        
    #     tmp_file_path.rename(filename)
        
    #     # Upload the renamed file to FTP
    #     await client.upload(tmp_file_path, remote_path, write_into=True)
    #     logger.info(f"Uploaded {filename} to FTP server at {remote_path}")        

    #     # Clean up
    #     Path(tmp_file_path).unlink()


