CREATE TABLE image_index (
    id SERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL,
    original_pvc_path TEXT,
    watermarked_pvc_path TEXT,
    original_s3_path TEXT,
    watermarked_s3_path TEXT,
    timestamp TIMESTAMPTZ NOT NULL
);