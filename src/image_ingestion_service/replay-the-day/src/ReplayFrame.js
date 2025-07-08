import React, { useEffect, useState, useRef } from "react";
import axios from "axios";

const ReplayTheDay = ({ cameraId, apiUrl, s3BucketUrl, pvcUrl, replayTheDay }) => {
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
                    const fullPath = currentImage.path;
                    const parts = fullPath.split("/");
                    let baseUrl = "";
                      if (s3BucketUrl) {
                        baseUrl = s3BucketUrl;
                        console.log(`Using S3 bucket URL: ${baseUrl}`); // Debug log
                        // console.log(`Base URL: ${baseUrl}, Filename: ${filename}`);
                        return `${baseUrl}/${fullPath}`;
                      }
                      else if(pvcUrl) {
                        baseUrl = pvcUrl;
                        console.log(`Using PVC URL: ${baseUrl}`); // Debug log
                        const simplifiedPath = `${parts[0]}/${parts[parts.length - 1]}`;
                        console.log(simplifiedPath); // Output: "343/1751992248460.jpg" 
                        // console.log(`Base URL: ${baseUrl}, Filename: ${filename}`);
                        return `${baseUrl}/watermarked/${simplifiedPath}`;
                      }
                      
                    })()
                  : `${s3BucketUrl}/${currentImage.path}`
              }
              className="replay-frame"
              alt={`frame ${currentIndex + 1}`}
              style={{
                display: "block",
                width: "380px",
                height: "auto",
                maxHeight: "420px",
                borderRadius: "0.5rem",
                boxShadow: "0 2px 8px rgba(0,0,0,0.1)"
              }}
            />
          <div style={{
            position: "absolute",
            bottom: "8px",
            right: "8px",
            background: "rgba(0, 0, 0, 0.6)",
            color: "#fff",
            padding: "2px 6px",
            borderRadius: "4px",
            fontSize: "0.85rem"
          }}>
            {new Date(currentImage.timestamp).toLocaleString()}
          </div>
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

export default ReplayTheDay;