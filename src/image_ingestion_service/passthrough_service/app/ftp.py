from anyio import Path
import aioftp
import tempfile
import os

async def upload_to_ftp(image_bytes: bytes, filename: str, camera_id: str):
    host = os.getenv("FTP_HOST", "ftp-server")
    port = int(os.getenv("FTP_PORT", 21))
    user = os.getenv("FTP_USER", "test")
    password = os.getenv("FTP_PASS", "test")
    target_dir = os.getenv("FTP_TARGET_DIR", "uploads")
    async with aioftp.Client.context(host, port, user, password) as client:
        try:
            print("Changing to target directory:", target_dir)
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

        # Clean up
        Path(tmp_file_path).unlink()


