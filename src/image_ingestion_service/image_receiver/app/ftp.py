from anyio import Path
import aioftp
import tempfile
import os
import logging
import aiofiles
import ssl

logger = logging.getLogger(__name__)

async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str, target_ftp_path: str) -> bool:
    host = os.getenv("FTP_HOST", "")
    port = int(os.getenv("FTP_PORT", 990))  # Default to 990 for FTPS implicit TLS
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")

    # Create SSL context for implicit TLS
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False  # Often needed for FTP servers
    ssl_context.verify_mode = ssl.CERT_NONE  # Skip certificate verification
    
    ftp_client = aioftp.Client(
        ssl=ssl_context  # Use implicit TLS with SSL context
    )
    
    ftp_client.passive = True

    try:
        # For implicit TLS, the connection is encrypted from the start
        await ftp_client.connect(host, port)
        logger.debug(f"Connected to FTPS server {host}:{port} as user {user} for camera_id={camera_id} (implicit TLS)")
        
        await ftp_client.login(user, password)

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

        # Upload the file with retry logic for connection issues
        try:
            await ftp_client.upload(tmp_file_path, filename, write_into=True)
        except ConnectionResetError:
            # Try switching to active mode if passive fails
            logger.debug("Passive mode failed, trying active mode for camera_id=%s", camera_id)
            ftp_client.passive = False
            await ftp_client.upload(tmp_file_path, filename, write_into=True)

        await Path(tmp_file_path).unlink()
        return True

    except Exception as e:
        logger.error(f"FTP error for camera_id={camera_id}: %s", str(e), exc_info=True)
        raise

    finally:
        await ftp_client.quit()