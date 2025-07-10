import React, { useEffect, useState, useRef } from "react";
import axios from "axios";

const ReplayFrame = ({ cameraId, apiUrl, s3BucketUrl, pvcUrl, replayTheDay }) => {
  const [images, setImages] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    const fetchImages = async () => {
      try {
        const response = await axios.get(`${apiUrl}/${cameraId}`);
        setImages(response.data);
        setError(null);
      } catch (err) {
        setError("Could not load images for replay.");
      }
    };
    fetchImages();
  }, [cameraId, apiUrl]);

  useEffect(() => {
    if (playing) {
      intervalRef.current = setInterval(() => {
        setCurrentIndex(prev => (prev + 1) % images.length);
      }, 200); // 1 second per frame
    } else {
      clearInterval(intervalRef.current);
    }
    return () => clearInterval(intervalRef.current);
  }, [playing, images.length]);

  const handleSeek = (e) => {
    setCurrentIndex(parseInt(e.target.value));
    setPlaying(false); // stop playing if user seeks
  };

  const currentImage = images[currentIndex];

  return (
    <div style={{
      borderRadius: "0.75rem",
      boxShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",
      overflow: "hidden",
      background: "#fff",
      padding: "0.5rem"
    }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "0.5rem"
      }}>
        <div>
        <span style={{ marginRight: "0.5rem" }}>
          {replayTheDay ? "(PVC watermarked) Replay the day" : "(S3 original) Timelapse"} for Camera {cameraId}
        </span>
        </div>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}
      {currentImage && (
        <div style={{ 
            position: "relative", 
            display: "inline-block"}}>
            <img
              src={
                replayTheDay
                  ? (() => {
                    const fullPath_pvc = currentImage.watermarked_pvc_path;
                    const baseUrl = pvcUrl;
                    const simplifiedPath = fullPath_pvc;
                    const relativePath = fullPath_pvc? "watermarked" + simplifiedPath.split("watermarked")[1]: "";
                    return `${baseUrl}/${relativePath}`;
                      
                    })()
                  : (() => {
                        const fullPath_s3 = currentImage.watermarked_s3_path;
                        const baseUrl = s3BucketUrl;
                        return `${baseUrl}/${fullPath_s3}`;
                  })()
              }
              className="replay-frame"
              alt={`frame ${currentIndex + 1}`}
              style={{
                display: "block",
                width: "420px",
                height: "auto",
                maxHeight: "420px",
                borderRadius: "0.5rem",
                boxShadow: "0 2px 8px rgba(0,0,0,0.1)"
              }}
            />
        </div>
      )}

      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-start",
        padding: "0.5rem"
      }}>
        <button onClick={() => setCurrentIndex(0)}>{"<<"}</button>
        <button onClick={() => setPlaying(!playing)}>{playing ? "⏸" : "▶"}</button>
        <button onClick={() => setCurrentIndex((currentIndex + 1) % images.length)}>{">>"}</button>
        <input
            type="range"
            min="0"
            max={images.length - 1}
            value={currentIndex}
            onChange={handleSeek}
            style={{ marginLeft: "0.5rem", width: "620px", height: "4px" }}
        />
      </div>
    </div>
  );
};

export default ReplayFrame;