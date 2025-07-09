CREATE TABLE image_index (
    id SERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    s3_path TEXT,
    pvc_path TEXT,
    watermarked_path TEXT
);