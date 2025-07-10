import React, { useEffect, useState } from "react";
import axios from "axios";

const originalImageUrl = "http://localhost:8081/api/images";
// const s3BucketUrl = "http://localhost:9000/test-s3-bucket";
const watermarkedPvcUrl = "http://localhost:8081/static/images/watermarked";
const originalPvcUrl = "http://localhost:8081/static/images/originals";

function DbcImage({ cameraId }) {
  const [imageMeta, setImageMeta] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchLatestImage = async () => {
      setLoading(true);
      try {
        const response = await axios.get(`${originalImageUrl}/${cameraId}`);
        setImageMeta(response.data);
        setError(null);
      } catch (err) {
        if (err.response && err.response.status === 404) {
          setError("No image found for this camera in the last 24 hours.");
        } else {
          setError("An error occurred while fetching the image.");
        }
        setImageMeta(null);
      } finally {
        setLoading(false);
      }
    };

    fetchLatestImage();
  }, [cameraId]);

  if (loading) {
    return <div>Loading latest image...</div>;
  }

  if (error) {
    return <div style={{ color: "red" }}>{error}</div>;
  }

  if (!imageMeta) {
    return null;
  }

  return (
    <div style={{ padding: "1rem" }}>
      

      <h2 style={{ fontWeight: "bold", fontSize: "1.25rem", marginBottom: "0.5rem" }}>
        Latest Watermarked Image, from PVC
      </h2>
      {/* <h3>{`${imageMeta.path}`}</h3> */}
      {/* <h3>{`${watermarkedPvcUrl}/${cameraId}/${imageMeta.path.split("/").pop()}`}</h3> */}
    {/* <img 
        src={`${watermarkedPvcUrl}/${cameraId}/${imageMeta.path.split("/").pop()}`}
        alt={`Watermarked from camera ${cameraId}`} 
        style={{ borderRadius: "0.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.1)", maxWidth: "70%" }}
    /> */}

        {imageMeta?.watermarked_pvc_path ? (
          <img 
            src={`${watermarkedPvcUrl}/${cameraId}/${imageMeta.watermarked_pvc_path.split("/").pop()}`}
            alt={`Watermarked from camera ${cameraId}`} 
            style={{ 
              borderRadius: "0.5rem", 
              boxShadow: "0 2px 8px rgba(0,0,0,0.1)", 
              maxWidth: "70%" 
            }}
          />
        ) : (
          <div>No image watermarked</div>
        )}


      <h2 style={{ fontWeight: "bold", fontSize: "1.25rem", marginBottom: "0.5rem" }}>
        Latest Original Image, from PVC
      </h2>
    <img 
        src={`${originalPvcUrl}/${cameraId}.jpg`} 
        alt={`Original from camera ${cameraId}`} 
        style={{ borderRadius: "0.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.1)", maxWidth: "70%" }}
    />

        <p style={{ fontSize: "0.875rem", color: "#555", marginTop: "0.25rem" }}>
            Captured at: {new Date(imageMeta.timestamp).toLocaleString()}
        </p>
    </div>
  );
}

export default DbcImage;