from anyio import Path
import aioftp
import tempfile
import os
import logging
import aiofiles
import io

logger = logging.getLogger(__name__)

# async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str) -> bool:
#     host = os.getenv("FTP_HOST", "")
#     port = int(os.getenv("FTP_PORT", 21))
#     user = os.getenv("FTP_USER", "test")
#     password = os.getenv("FTP_PASS", "test")
#     target_dir = os.getenv("FTP_TARGET_DIR", "")

#     client = aioftp.Client()
#     client.passive = True

#     tmp_dir = tempfile.gettempdir()
#     tmp_file_path = Path(tmp_dir) / filename

#     try:
#         await client.connect(host, port)
#         await client.login(user, password)
#         logger.info(f"Connected to FTP server {host}:{port} as user {user}")

#         try:
#             await client.change_directory(target_dir)
#         except aioftp.StatusCodeError:
#             await client.make_directory(target_dir)
#             await client.change_directory(target_dir)

#         # print(f"Changed directory to {target_dir} on FTP server")
#         # with tmp_file_path.open("wb") as tmp_file:
#         #     tmp_file.write(image_bytes)
#         # print(f"Saved image to temporary file {tmp_file_path}")
            
#         try:
#             # with tmp_file_path.open("wb") as tmp_file:
#             #     tmp_file.write(image_bytes)
#             async with aiofiles.open(tmp_file_path, "wb") as tmp_file:
#                 await tmp_file.write(image_bytes)
#             print(f"Saved image to temporary file {tmp_file_path}")
#         except Exception as e:
#             print(f"Failed to write temp file: {e}")
#             raise

#         remote_path = f"{camera_id}/{filename}"

#         logger.info(f"Uploading {tmp_file_path} to {remote_path} on FTP server...")
#         try:
#             await client.remove_file(remote_path)
#             logger.info(f"Removed existing file on FTP: {remote_path}")
#         except aioftp.StatusCodeError as e:
#             # 550 means "file not found" or "can't delete" — safe to ignore if file isn't there
#             if "550" in str(e):
#                 logger.info(f"No existing file to remove: {remote_path}")
#             else:
#                 logger.warning(f"Unexpected FTP error when trying to remove file: {e}")
#         await client.upload(tmp_file_path, remote_path, write_into=True)
#         logger.info(f"Uploaded {filename} to FTP server at {remote_path}")

#         return True

#     except Exception as e:
#         logger.error(f"Push to FTP failed from {camera_id}: {e}")
#         return False

#     finally:
#         await client.quit()
#         await tmp_file_path.unlink(missing_ok=True)

# async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str) -> bool:
#     host = os.getenv("FTP_HOST", "")
#     port = int(os.getenv("FTP_PORT", 21))
#     user = os.getenv("FTP_USER", "test")
#     password = os.getenv("FTP_PASS", "test")
#     target_dir = os.getenv("FTP_TARGET_DIR", "")

#     ftp_client = aioftp.Client()
#     ftp_client.passive = True

#     try:
#         await ftp_client.connect(host, port)
#         await ftp_client.login(user, password)
#         logger.info(f"Connected to FTP server {host}:{port} as user {user}")

#         # Ensure target directory exists
#         try:
#             await ftp_client.change_directory(target_dir)
#             print(f"Changed directory to {target_dir} on FTP server")
#         except aioftp.StatusCodeError:
#             await ftp_client.make_directory(target_dir)
#             await ftp_client.change_directory(target_dir)
#             print(f"Created and changed directory to {target_dir} on FTP server")
#         # Ensure camera id directory exists
#         try:
#             await ftp_client.change_directory(camera_id)
#             print(f"Changed directory to {camera_id} on FTP server")
#         except aioftp.StatusCodeError:
#             await ftp_client.make_directory(camera_id)
#             await ftp_client.change_directory(camera_id)
#             print(f"Created and changed directory to {camera_id} on FTP server")


#         # Build remote path (e.g. "343/343_20240625T194300Z.jpg")
#         remote_path = f"{target_dir}/{camera_id}/{filename}"

#         # Try to remove existing file (ignore if it doesn't exist)
#         try:
#             await ftp_client.remove_file(filename)
#             logger.info(f"Removed existing file on FTP: {remote_path}")
#         except aioftp.StatusCodeError as e:
#             if "550" in str(e):
#                 logger.info(f"No existing file to remove: {remote_path}")
#             else:
#                 logger.warning(f"Unexpected FTP error when trying to remove file: {e}")

#         # Save bytes to temp file asynchronously
#         # Create temp file path in system temp folder
#         tmp_dir = tempfile.gettempdir()
#         tmp_file_path = Path(tmp_dir) / filename
#         async with aiofiles.open(tmp_file_path, "wb") as tmp_file:
#             await tmp_file.write(image_bytes)
#         logger.info(f"Saved image to temporary file {tmp_file_path}")

#         # # Upload from in-memory bytes
#         # logger.info(f"Uploading in-memory bytes to {remote_path} on FTP server...")
#         # stream = io.BytesIO(image_bytes)
#         # await ftp_client.upload_stream(stream, filename)
#         # logger.info(f"Uploaded {filename} to FTP server at {remote_path}")

#          # Upload the file from disk
#         logger.info(f"Uploading {tmp_file_path} to FTP as {filename}...")
#         try:
#             await ftp_client.upload(tmp_file_path, filename, write_into=True)
#         except aioftp.StatusCodeError as e:
#             print(f"Upload to remote server failed: {e}")
#             raise
        
#         logger.info(f"Upload successful")
                

#         return True

#     except Exception as e:
#         logger.error(f"Push to FTP failed from {camera_id}: {e}")
#         return False

#     finally:
#         await ftp_client.quit()


async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str):
    host = os.getenv("FTP_HOST", "")
    port = int(os.getenv("FTP_PORT", 21))
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")
    target_dir = os.getenv("FTP_TARGET_DIR", "")
    async with aioftp.Client.context(host, port, user, password) as client:
        logger.info(f"Connected to FTP server {host}:{port} as user {user}")
        try:
            await client.change_directory(target_dir)
        except aioftp.StatusCodeError as e:
            await client.make_directory(target_dir)
            await client.change_directory(target_dir)

        # Save to a temp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_file_path = Path(tmp_file.name)
            remote_path = f"{camera_id}/{filename}"   
        
        tmp_file_path.rename(filename)
        
        # Upload the renamed file to FTP
        await client.upload(tmp_file_path, remote_path, write_into=True)
        logger.info(f"Uploaded {filename} to FTP server at {remote_path}")        

        # Clean up
        await Path(tmp_file_path).unlink()


