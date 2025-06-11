from fastapi import FastAPI, Request, HTTPException
from datetime import datetime
from .rabbitmq import send_to_rabbitmq
from .ftp import upload_to_ftp
import uuid

app = FastAPI()

@app.post("/forward")
async def forward_image(request: Request):
    content_type = request.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid image content")
    camera_id = request.headers.get("camera_id")
    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id header missing")

    image_bytes = await request.body()
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique_id = uuid.uuid4().hex[:8]  # Unique suffix
    filename = f"{camera_id}_{timestamp}_{unique_id}.jpg"

    await send_to_rabbitmq(image_bytes, filename, camera_id=camera_id)
    await upload_to_ftp(image_bytes, filename, camera_id=camera_id)

    return {
            "status": "forwarded", 
            "camera_id": camera_id,
            "filename": filename
        }
